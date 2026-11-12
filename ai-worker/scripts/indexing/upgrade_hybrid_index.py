"""Copy a verified native FashionGen index into a new hybrid-capable snapshot.

No model is loaded and no embedding/checkpoint is modified or regenerated.
The source directory remains untouched. Select the printed output explicitly
when starting inference; this command never activates or restarts a service.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4

from ai_worker.indexing.search_documents import (
    build_search_documents, validate_search_documents, write_search_documents,
)


ARTIFACTS = {
    "image_embeddings.index": "image_index_sha256",
    "text_embeddings.index": "text_index_sha256",
    "image_paths.json": "image_paths_sha256",
    "captions.json": "captions_sha256",
    "product_ids.json": "product_ids_sha256",
}


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def upgrade(source, csv_path, output):
    source, csv_path, output = Path(source).resolve(), Path(csv_path).resolve(), Path(output).resolve()
    if not source.is_dir() or output.parent != source.parent or output == source or output.exists():
        raise ValueError("Output must be a new sibling directory of the source index")
    meta = json.loads((source / "index_meta.json").read_text(encoding="utf-8"))
    if meta.get("dataset_name") != "FashionGen" or meta.get("dataset_split") != "val":
        raise ValueError("Metadata upgrade requires a native FashionGen validation index")
    if not meta.get("source_csv_sha256") or _digest(csv_path) != meta["source_csv_sha256"]:
        raise ValueError("CSV provenance mismatch; use the verified source metadata")
    for filename, field in ARTIFACTS.items():
        expected = meta.get(field)
        # Older verified native manifests omitted only product_ids_sha256;
        # that mapping is checked against every source CSV row below.
        if (not expected and filename != "product_ids.json") or (expected and _digest(source / filename) != expected):
            raise ValueError(f"Source artifact checksum mismatch: {filename}")
    with csv_path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    ids = json.loads((source / "product_ids.json").read_text(encoding="utf-8"))
    paths = json.loads((source / "image_paths.json").read_text(encoding="utf-8"))
    captions = json.loads((source / "captions.json").read_text(encoding="utf-8"))
    if not rows or not (len(rows) == len(ids) == len(paths) == len(captions) == meta.get("num_vectors")):
        raise ValueError("Source CSV/vector mapping counts differ")
    clean_id = lambda value: str(value).strip().strip("[]").strip()
    for row, pid, filename, caption in zip(rows, ids, paths, captions):
        if clean_id(row["product_id"]) != str(pid) or row["text"] != caption or Path(row["image_path"].replace("\\", "/")).name != filename:
            raise ValueError("Source CSV/product/vector mapping differs")
    if len(set(ids)) != meta.get("num_products"):
        raise ValueError("Source product count differs")
    validate_search_documents(source, meta, ids, len(rows))
    payload = build_search_documents(rows, ids)
    staging = output.with_name(output.name + ".building-" + uuid4().hex[:8])
    staging.mkdir()
    try:
        for filename in ARTIFACTS:
            shutil.copyfile(source / filename, staging / filename)
        if (source / "products.json").is_file():
            shutil.copyfile(source / "products.json", staging / "products.json")
        updated = dict(meta)
        timestamp = datetime.now(timezone.utc)
        updated.update(index_version=meta["index_version"] + "-hybrid-" + timestamp.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
                       source_index_version=meta["index_version"], built_at=timestamp.isoformat(),
                       metadata_upgrade_only=True)
        for filename, field in ARTIFACTS.items():
            updated[field] = _digest(staging / filename)
        updated.update(write_search_documents(staging, payload))
        validate_search_documents(staging, updated, ids, len(rows))
        (staging / "index_meta.json").write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.rename(output)
    finally:
        if staging.exists():
            if staging.resolve().parent != output.parent or not staging.name.startswith(output.name + ".building-"):
                raise RuntimeError("Refusing cleanup outside the metadata-upgrade staging directory")
            shutil.rmtree(staging)
    return dict(output=str(output), index_version=updated["index_version"],
                source_index_version=meta["index_version"], num_products=len(payload["documents"]),
                num_vectors=len(ids), activated=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(upgrade(args.source, args.csv, args.output), indent=2), flush=True)
