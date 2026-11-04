"""Publish the verified local FashionGen corpus into the SQL storefront.

Read-only source mounts; immutable serving artifacts; SQL activation last.
Real photos/descriptions and trained MRL features. Price/stock are explicitly
synthetic demo commerce data because the extracted CSV has neither field.
Rerunning after success preserves prices, inventory, users and newer rebuilds.
"""
import csv
import gc
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import shutil
from uuid import NAMESPACE_URL, uuid5

import faiss
from minio import Minio
import psycopg
from psycopg.types.json import Jsonb
import torch


ARTIFACTS = {
    "image_embeddings.index": "image_index_sha256",
    "text_embeddings.index": "text_index_sha256",
    "image_paths.json": "image_paths_sha256",
    "captions.json": "captions_sha256",
}
DATA_NOTE = "FashionGen photos and descriptions. Prices and inventory are simulated for this demonstration."


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def identity(kind, source_id):
    return str(uuid5(NAMESPACE_URL, f"aurafind:fashiongen:val:{kind}:{source_id}"))


def source_id(value):
    return str(value).strip().strip("[]").strip()


def prepare_source(root=Path("/source/index"), dataset=Path("/source/dataset"), checkpoints=Path("/source/checkpoints")):
    meta = json.loads((root / "index_meta.json").read_text(encoding="utf-8"))
    if meta.get("dataset_name") != "FashionGen" or meta.get("dataset_split") != "val":
        raise ValueError("Expected the verified FashionGen validation index")
    if meta.get("clip_model_name") != "openai/clip-vit-base-patch16" or meta.get("supported_dims") != [16, 32, 64, 128, 256, 512]:
        raise ValueError("Expected the trained B/16 MRL configuration")
    csv_path = dataset / "metadata.csv"
    if digest(csv_path) != meta["source_csv_sha256"]:
        raise ValueError("CSV provenance mismatch; rebuild/verify the source index first")
    for name, field in ARTIFACTS.items():
        if digest(root / name) != meta[field]:
            raise ValueError(f"Source index hash mismatch: {name}")
    checkpoint_name = Path(meta["checkpoint_path"].replace("\\", "/")).name
    checkpoint = checkpoints / checkpoint_name
    if digest(checkpoint) != meta["checkpoint_sha256"]:
        raise ValueError("Source checkpoint hash mismatch")
    # Match the source index builder's universal-newline decoding, including
    # embedded CRLFs inside quoted FashionGen descriptions.
    with csv_path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    paths = json.loads((root / "image_paths.json").read_text())
    captions = json.loads((root / "captions.json").read_text())
    ids = json.loads((root / "product_ids.json").read_text())
    if not rows or not (len(rows) == len(paths) == len(captions) == len(ids) == meta["num_vectors"]):
        raise ValueError("Source row counts differ")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate source image paths")
    if len(set(map(source_id, ids))) != meta["num_products"]:
        raise ValueError("Source product count differs from manifest")
    for n, (row, filename, caption, pid) in enumerate(zip(rows, paths, captions, ids)):
        if Path(filename).name != filename or Path(row["image_path"].replace("\\", "/")).name != filename:
            raise ValueError("Source image order/path mismatch")
        if not (dataset / "images" / filename).is_file() or row["text"] != caption or source_id(row["product_id"]) != source_id(pid):
            raise ValueError(f"Source row {n} mismatch: file={filename}, exists={(dataset / 'images' / filename).is_file()}, caption_match={row['text'] == caption}, id_match={source_id(row['product_id']) == source_id(pid)}")
    for name in ("image_embeddings.index", "text_embeddings.index"):
        index = faiss.read_index(str(root / name))
        if index.d != 512 or index.ntotal != len(rows):
            raise ValueError("FAISS source shape mismatch")
    print(f"PASS source hashes and every row mapping: {len(rows):,} images / {len(set(map(source_id, ids))):,} products", flush=True)
    return root, dataset, checkpoint, meta, rows, paths


def main():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        active = db.execute("SELECT metadata FROM ai_index_versions WHERE is_active").fetchone()
        if active and active[0].get("catalog_source") == "FashionGen":
            print("FashionGen is already installed; preserving catalog, stock and active version.", flush=True)
            return
        root, dataset, checkpoint, source_meta, rows, paths = prepare_source()
        # Same locks as the live index consumer and fixture seed.
        for lock in (19860513, 19860512):
            if not db.execute("SELECT pg_try_advisory_lock(%s)", (lock,)).fetchone()[0]:
                raise RuntimeError("Stop index-worker before importing; another publisher owns the lock")
        active = db.execute("SELECT metadata FROM ai_index_versions WHERE is_active").fetchone()
        if active and active[0].get("catalog_source") == "FashionGen":
            print("FashionGen is already installed; preserving catalog, stock and active version.", flush=True)
            return
        if db.execute("SELECT EXISTS(SELECT 1 FROM products WHERE metadata->>'source_dataset'='FashionGen')").fetchone()[0]:
            raise RuntimeError("FashionGen products already exist with a different active source; inspect before importing")
        version = identity("version", source_meta["checkpoint_sha256"] + source_meta["image_index_sha256"] + source_meta["source_csv_sha256"])
        output = Path(os.environ.get("VECTOR_DB_DIR", "/data/vector_db")) / "versions" / version
        building = output.with_name(version + ".importing")
        building.mkdir(parents=True, exist_ok=True)
        image_root = Path(os.environ.get("IMG_BASE_DIR", "/data/images"))
        image_root.mkdir(parents=True, exist_ok=True)
        store = Minio(os.environ["MINIO_ENDPOINT"], access_key=os.environ["MINIO_ACCESS_KEY"], secret_key=os.environ["MINIO_SECRET_KEY"], secure=os.environ.get("MINIO_SECURE") == "true")
        for bucket in ("products", "reviews"):
            if not store.bucket_exists(bucket):
                store.make_bucket(bucket)
        store.set_bucket_policy("products", json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]}, "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::products/*"]}]}))

        def upload(filename):
            source = dataset / "images" / filename
            target = image_root / filename
            if target.exists() and digest(target) != digest(source):
                raise ValueError(f"Serving image filename collision: {filename}")
            if not target.exists():
                shutil.copyfile(source, target)
            store.fput_object("products", f"fashiongen/val/{filename}", str(source), content_type="image/jpeg")

        with ThreadPoolExecutor(max_workers=8) as pool:
            for n, _ in enumerate(pool.map(upload, paths), 1):
                if n % 2000 == 0 or n == len(paths):
                    print(f"Images staged: {n:,}/{len(paths):,}", flush=True)
        # Copy the offline B/16 cache, dereferencing Windows cache links.
        hf_target = Path(os.environ.get("HF_HOME", "/data/huggingface")) / "hub" / "models--openai--clip-vit-base-patch16"
        shutil.copytree("/source/hf-model", hf_target, dirs_exist_ok=True)
        if not output.exists():
            print("Preparing model-only serving checkpoint (training state stays in source)...", flush=True)
            raw = torch.load(checkpoint, map_location="cpu", weights_only=True)
            weights = raw.get("model_state_dict", raw)
            torch.save(weights, building / "checkpoint.pt")
            del weights, raw
            gc.collect()
            for name in ARTIFACTS:
                shutil.copyfile(root / name, building / name)
            catalog_ids = [identity("product", source_id(row["product_id"])) for row in rows]
            (building / "product_ids.json").write_text(json.dumps(catalog_ids))
            meta = dict(source_meta)
            meta.update(index_version=version, checkpoint_path=str(output / "checkpoint.pt"), checkpoint_sha256=digest(building / "checkpoint.pt"), source_checkpoint_sha256=source_meta["checkpoint_sha256"], source_index_version=source_meta["index_version"], catalog_source="FashionGen", dataset_split="catalog", source_dataset_split="val", image_root=str(image_root), model_kind="trained-mrl", commerce_data_kind="simulated", commerce_data_note=DATA_NOTE, built_at=datetime.now(timezone.utc).isoformat(), product_ids_sha256=digest(building / "product_ids.json"))
            (building / "index_meta.json").write_text(json.dumps(meta, indent=2))
            building.rename(output)
        meta = json.loads((output / "index_meta.json").read_text())
        for name, field in {**ARTIFACTS, "product_ids.json": "product_ids_sha256", "checkpoint.pt": "checkpoint_sha256"}.items():
            if digest(output / name) != meta[field]:
                raise ValueError(f"Staged artifact hash mismatch: {name}")
        products = {}
        for row in rows:
            products.setdefault(source_id(row["product_id"]), row)
        with db.transaction():
            with db.cursor() as cur:
                for pid, row in products.items():
                    product = identity("product", pid)
                    variant = identity("variant", pid)
                    # Reproducible fictional commerce values, explicitly marked.
                    price = Decimal(29 + int(hashlib.sha256(pid.encode()).hexdigest()[:6], 16) % 271) + Decimal("0.00")
                    title = row["text"].split(". ", 2)
                    name = (title[1] if len(title) > 1 and title[0] == row.get("brand") else title[0])[:190]
                    metadata = {"source_dataset": "FashionGen", "source_split": "val", "source_product_id": pid, "subcategory": row.get("subcategory", ""), "commerce_data_kind": "simulated", "commerce_data_note": DATA_NOTE, "variant_options_kind": "unspecified"}
                    cur.execute("INSERT INTO products(id,handle,name,description,brand,category,base_price,is_featured,search_status,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,true,'ready',%s)", (product, "fashiongen-" + pid, name, row["text"], row.get("brand", ""), row["category"], price, Jsonb(metadata)))
                    cur.execute("INSERT INTO product_variants(id,product_id,sku,price,stock) VALUES(%s,%s,%s,%s,20)", (variant, product, "FG-VAL-" + pid, price))
                    cur.execute("UPDATE products SET default_variant_id=%s WHERE id=%s", (variant, product))
                positions = {}
                for row, filename in zip(rows, paths):
                    pid = source_id(row["product_id"])
                    position = positions.get(pid, 0)
                    positions[pid] = position + 1
                    cur.execute("INSERT INTO product_images(id,product_id,object_key,alt_text,position,is_primary) VALUES(%s,%s,%s,%s,%s,%s)", (identity("image", filename), identity("product", pid), f"fashiongen/val/{filename}", row["text"][:200], position, position == 0))
                # Retain demo rows/images/old versions for history, hide from shop.
                cur.execute("UPDATE products SET is_active=false,search_revision=search_revision+1 WHERE metadata->>'demo'='true'")
                cur.execute("UPDATE ai_index_versions SET is_active=false WHERE is_active")
                cur.execute("INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,num_vectors,supported_dims,index_path,is_active,metadata) VALUES(%s,%s,'checkpoint.pt',%s,%s,%s,%s,true,%s)", (version, "fashiongen-catalog-" + version, meta["checkpoint_sha256"], len(rows), meta["supported_dims"], str(output), Jsonb(meta)))
                cur.executemany("INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES(%s,%s,%s)", [(version, n, identity("image", filename)) for n, filename in enumerate(paths)])
        print(f"PUBLISHED: {len(products):,} real FashionGen products / {len(rows):,} images. Prices/stock simulated. Restart inference to switch model. Version {version}", flush=True)


if __name__ == "__main__":
    main()
