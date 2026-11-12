"""Publish lexical metadata for an existing SQL index without encoding images.

Run in the AI image with DATABASE_URL and VECTOR_DB_DIR. Stop index-worker first.
The original version, images, commerce rows, checkpoint and embeddings remain
unchanged. A fresh immutable version is activated only after full validation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
import shutil

import faiss
import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_worker.indexing.search_documents import (
    build_search_documents, validate_search_documents, write_search_documents,
)


LOCKS = (19860513, 19860512)
ARTIFACTS = {
    "image_embeddings.index": "image_index_sha256",
    "text_embeddings.index": "text_index_sha256",
    "image_paths.json": "image_paths_sha256",
    "captions.json": "captions_sha256",
    "product_ids.json": "product_ids_sha256",
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def managed(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Catalog index/checkpoint path is outside VECTOR_DB_DIR")
    return path


def validate_source(root, source):
    folder = managed(root, source["index_path"])
    meta = json.loads((folder / "index_meta.json").read_text(encoding="utf-8"))
    if meta.get("index_version") not in (str(source["id"]), source["version_tag"]):
        raise ValueError("Selected SQL version and source manifest differ")
    if source["metadata"].get("index_version") != meta["index_version"]:
        raise ValueError("Active SQL metadata and source manifest differ")
    count = meta.get("num_vectors")
    if type(count) is not int or count <= 0 or source["num_vectors"] != count:
        raise ValueError("Source vector count differs from SQL")
    if meta.get("supported_dims") != source["supported_dims"] or 512 not in source["supported_dims"]:
        raise ValueError("Source dimensions differ from SQL")
    for filename, field in ARTIFACTS.items():
        if not meta.get(field) or digest(folder / filename) != meta[field]:
            raise ValueError(f"Source artifact checksum mismatch: {filename}")
    checkpoint = managed(root, meta["checkpoint_path"])
    if not meta.get("checkpoint_sha256") or source["checkpoint_sha"] != meta["checkpoint_sha256"] or digest(checkpoint) != meta["checkpoint_sha256"]:
        raise ValueError("Source checkpoint checksum differs from manifest/SQL")
    for filename in ("image_embeddings.index", "text_embeddings.index"):
        index = faiss.read_index(str(folder / filename))
        if index.d != 512 or index.ntotal != count:
            raise ValueError("Source FAISS index must contain matching nonempty 512D vectors")
        vectors = index.reconstruct_n(0, count)
        if not np.isfinite(vectors).all() or (np.linalg.norm(vectors, axis=1) == 0).any():
            raise ValueError("Source FAISS vectors contain invalid values")
    values = {name: json.loads((folder / name).read_text(encoding="utf-8"))
              for name in ("product_ids.json", "image_paths.json", "captions.json")}
    if any(not isinstance(value, list) or len(value) != count or any(not isinstance(item, str) for item in value)
           for value in values.values()):
        raise ValueError("Source mappings differ from vector count")
    ids = values["product_ids.json"]
    for pid in ids:
        try:
            if str(UUID(pid)) != pid:
                raise ValueError()
        except (ValueError, AttributeError) as exc:
            raise ValueError("Catalog product IDs must be canonical SQL UUIDs") from exc
    if len(set(ids)) != meta.get("num_products"):
        raise ValueError("Source product count differs from product mapping")
    lexical = validate_search_documents(folder, meta, ids, count)
    return folder, checkpoint, meta, ids, lexical


def mapping_rows(db, version, product_ids):
    rows = db.execute("""SELECT m.vector_id,m.product_image_id::text image_id,
        p.id::text product_id,p.name,COALESCE(p.description,'') description,
        COALESCE(p.brand,'') brand,COALESCE(p.category,'') category,
        COALESCE(p.metadata->>'subcategory','') subcategory,p.tags,p.search_revision
        FROM index_vector_mappings m
        JOIN product_images i ON i.id=m.product_image_id
        JOIN products p ON p.id=i.product_id
        WHERE m.index_version_id=%s ORDER BY m.vector_id""", (version,)).fetchall()
    # Inactive views/products are intentionally included: every immutable source
    # vector must retain its owner. Runtime SQL eligibility handles visibility.
    if len(rows) != len(product_ids) or len({row["image_id"] for row in rows}) != len(rows):
        raise ValueError("SQL mappings do not cover every source vector exactly once")
    for vector_id, (row, pid) in enumerate(zip(rows, product_ids)):
        if row["vector_id"] != vector_id or row["product_id"] != pid:
            raise ValueError("SQL vector/image/product ownership differs from source mapping")
    return rows


def _active(db):
    source = db.execute("""SELECT id,version_tag,index_path,num_vectors,supported_dims,
        checkpoint_sha,metadata FROM ai_index_versions WHERE is_active""").fetchone()
    if not source:
        raise ValueError("No active SQL catalog index is configured")
    return source


def _version(db, version):
    try:
        version = str(UUID(str(version)))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Source version must be a UUID") from exc
    source = db.execute("""SELECT id,version_tag,index_path,num_vectors,supported_dims,
        checkpoint_sha,metadata FROM ai_index_versions WHERE id=%s""", (version,)).fetchone()
    if not source:
        raise ValueError("Selected source version does not exist")
    return source


def _reject_running_job(db):
    if db.execute("SELECT EXISTS(SELECT 1 FROM ai_index_jobs WHERE status='running') running").fetchone()["running"]:
        raise RuntimeError("A catalog index job is running; let it finish before metadata upgrade")


def upgrade(database_url=None, vector_db_dir=None, *, dry_run=False, source_version=None):
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    root = Path(vector_db_dir or os.environ.get("VECTOR_DB_DIR", "/data/vector_db")).resolve()
    if not root.is_dir():
        raise ValueError("VECTOR_DB_DIR must be an existing managed index root")
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=5,
                         options="-c lock_timeout=5000 -c statement_timeout=30000") as db:
        acquired = []
        try:
            for lock in LOCKS:
                if not db.execute("SELECT pg_try_advisory_lock(%s) acquired", (lock,)).fetchone()["acquired"]:
                    raise RuntimeError("Stop index-worker/seed before metadata upgrade; a publisher owns the lock")
                acquired.append(lock)
            _reject_running_job(db)
            previous_active = _active(db)
            source = _version(db, source_version) if source_version is not None else previous_active
            folder, checkpoint, meta, ids, lexical = validate_source(root, source)
            with db.transaction():
                # SHARE permits storefront reads while blocking edits to all
                # captured metadata/ownership. Publication uses the same snapshot.
                db.execute("LOCK TABLE products,product_images,index_vector_mappings,ai_index_jobs IN SHARE MODE")
                db.execute("LOCK TABLE ai_index_versions IN SHARE ROW EXCLUSIVE MODE")
                _reject_running_job(db)
                if _active(db) != previous_active or _version(db, source["id"]) != source:
                    raise RuntimeError("Active or selected source version changed during metadata validation")
                rows = mapping_rows(db, source["id"], ids)
                payload = build_search_documents(rows, ids)
                if lexical is not None and source["id"] == previous_active["id"]:
                    return dict(status="unchanged", index_version=meta["index_version"],
                                num_vectors=len(ids), num_products=len(payload["documents"]), activated=False)
                if dry_run:
                    return dict(status="validated", source_index_version=meta["index_version"],
                                previous_active_version=str(previous_active["id"]),
                                num_vectors=len(ids), num_products=len(payload["documents"]), activated=False)
                version = str(uuid4())
                destination = managed(root, root / "versions" / version)
                building = managed(root, root / "versions" / (version + ".hybrid-building"))
                building.mkdir(parents=True, exist_ok=False)
                for filename, field in ARTIFACTS.items():
                    shutil.copy2(folder / filename, building / filename)
                    if digest(building / filename) != meta[field]:
                        raise ValueError(f"Copied artifact checksum mismatch: {filename}")
                shutil.copy2(checkpoint, building / "checkpoint.pt")
                if digest(building / "checkpoint.pt") != meta["checkpoint_sha256"]:
                    raise ValueError("Copied checkpoint checksum mismatch")
                updated = dict(meta, index_version=version, checkpoint_path=str(destination / "checkpoint.pt"),
                               source_index_version=meta["index_version"], metadata_upgrade_only=True,
                               built_at=datetime.now(timezone.utc).isoformat())
                updated.update(write_search_documents(building, payload))
                validate_search_documents(building, updated, ids, len(ids))
                (building / "index_meta.json").write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                building.rename(destination)
                # Files are complete before SQL sees the candidate. Any failure
                # rolls back SQL and leaves a harmless unreferenced debug folder.
                db.execute("""INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,
                    num_vectors,supported_dims,index_path,is_active,metadata)
                    VALUES(%s,%s,'checkpoint.pt',%s,%s,%s,%s,false,%s)""",
                    (version, "hybrid-" + version, updated["checkpoint_sha256"], len(ids),
                     updated["supported_dims"], str(destination), Jsonb(updated)))
                copied = db.execute("""INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id)
                    SELECT %s,vector_id,product_image_id FROM index_vector_mappings WHERE index_version_id=%s""",
                    (version, source["id"])).rowcount
                if copied != len(ids):
                    raise RuntimeError("Published SQL mapping count differs from source")
                deactivated = db.execute("UPDATE ai_index_versions SET is_active=false WHERE id=%s AND is_active", (previous_active["id"],)).rowcount
                if deactivated != 1:
                    raise RuntimeError("Previously active SQL version changed before publication")
                db.execute("UPDATE ai_index_versions SET is_active=true WHERE id=%s", (version,))
            return dict(status="upgraded", index_version=version, source_index_version=meta["index_version"],
                        previous_active_version=str(previous_active["id"]),
                        index_path=str(destination), num_vectors=len(ids), num_products=len(payload["documents"]), activated=True)
        finally:
            for lock in reversed(acquired):
                db.execute("SELECT pg_advisory_unlock(%s)", (lock,))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate source and SQL mappings without publishing")
    parser.add_argument("--source-version", help="Deliberately upgrade this existing version instead of the currently active SQL version")
    args = parser.parse_args()
    print(json.dumps(upgrade(dry_run=args.dry_run, source_version=args.source_version), indent=2), flush=True)
