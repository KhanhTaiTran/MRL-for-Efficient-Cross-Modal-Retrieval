"""Opt-in real Go -> Python -> PostgreSQL hybrid catalog integration.

Set HYBRID_TEST_ADMIN_DATABASE_URL to a disposable PostgreSQL cluster URL. This
test creates and drops its own uniquely named database, starts only owned hidden
services, and retains fixture artifacts/logs under repository tmp for diagnosis.
It does not start/stop PostgreSQL, touch the storefront catalog, or load MinIO.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4, uuid5

import faiss
import numpy as np
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import requests

from ai_worker.indexing.search_documents import build_search_documents, write_search_documents
from ai_worker.paths import REPOSITORY_ROOT, WORKER_ROOT, worker_path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def prepare_fixture(source, fixture, run_id):
    """Subset real vectors/documents, while remapping every image to SQL UUIDs."""
    meta = json.loads((source / "index_meta.json").read_text(encoding="utf-8"))
    payload = json.loads((source / "search_documents.json").read_text(encoding="utf-8"))
    source_docs = payload["documents"]
    adidas = [doc for doc in source_docs if doc["brand"].casefold().startswith("adidas") and len(doc["vector_ids"]) >= 2]
    others = [doc for doc in source_docs if not doc["brand"].casefold().startswith("adidas")]
    if len(adidas) < 20 or len(others) < 210:
        raise ValueError("Integration fixture needs 20 Adidas and 210 other real products")
    selected = adidas[:20] + others[:210]
    paths = json.loads((source / "image_paths.json").read_text(encoding="utf-8"))
    captions = json.loads((source / "captions.json").read_text(encoding="utf-8"))
    rows, ids, names, texts, original_vectors, products, images = [], [], [], [], [], [], []
    for position, doc in enumerate(selected):
        product_id = str(uuid5(run_id, "product:" + doc["product_id"]))
        product = dict(doc, product_id=product_id, price=40 + (position % 20) * 5,
                       featured=position % 2 == 0, active=position != len(selected) - 1,
                       images_active=position != len(selected) - 2)
        products.append(product)
        for image_position, original_vector in enumerate(doc["vector_ids"]):
            vector_id = len(rows)
            image_id = str(uuid5(run_id, "image:" + str(original_vector)))
            rows.append(dict(doc, product_id=product_id))
            ids.append(product_id)
            names.append(paths[original_vector])
            texts.append(captions[original_vector])
            original_vectors.append(original_vector)
            images.append(dict(id=image_id, product_id=product_id, vector_id=vector_id,
                               object_key="fixture/" + image_id + ".jpg", position=image_position,
                               active=product["images_active"]))
    index_root = fixture / "indexes"
    index_root.mkdir()
    version = str(uuid4())
    output = index_root / version
    output.mkdir()
    faiss.omp_set_num_threads(1)
    for name in ("image_embeddings.index", "text_embeddings.index"):
        old = faiss.read_index(str(source / name))
        vectors = np.ascontiguousarray(np.vstack([old.reconstruct(i) for i in original_vectors]), dtype=np.float32)
        index = faiss.IndexFlatIP(512)
        index.add(vectors)
        faiss.write_index(index, str(output / name))
    for name, values in [("image_paths.json", names), ("captions.json", texts), ("product_ids.json", ids)]:
        (output / name).write_text(json.dumps(values), encoding="utf-8")
    updated = dict(meta, index_version=version, checkpoint_path=str(worker_path(meta["checkpoint_path"]).resolve()),
                   num_vectors=len(rows), num_products=len(products), dataset_split="catalog",
                   dataset_name="Isolated FashionGen hybrid integration fixture", metadata_upgrade_only=False)
    for name, field in [("image_embeddings.index", "image_index_sha256"), ("text_embeddings.index", "text_index_sha256"),
                        ("image_paths.json", "image_paths_sha256"), ("captions.json", "captions_sha256"),
                        ("product_ids.json", "product_ids_sha256")]:
        updated[field] = digest(output / name)
    updated.update(write_search_documents(output, build_search_documents(rows, ids)))
    (output / "index_meta.json").write_text(json.dumps(updated, indent=2), encoding="utf-8")
    return index_root, output, updated, products, images


def populate(db_url, index_path, meta, products, images):
    with psycopg.connect(db_url) as db:
        for path in sorted((REPOSITORY_ROOT / "infra" / "migrations").glob("*.up.sql")):
            db.execute(path.read_text(encoding="utf-8"), prepare=False)
        for product in products:
            db.execute("""INSERT INTO products(id,handle,name,description,brand,category,base_price,
                       is_featured,is_active,search_status,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready',%s)""",
                       (product["product_id"], "test-" + product["product_id"], product["name"], product["description"],
                        product["brand"], product["category"], product["price"], product["featured"], product["active"],
                        Jsonb(dict(subcategory=product["subcategory"], integration_fixture=True))))
        db.execute("""INSERT INTO ai_index_versions(id,version_tag,checkpoint_name,checkpoint_sha,
                   num_vectors,supported_dims,index_path,is_active,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,true,%s)""",
                   (meta["index_version"], meta["index_version"], Path(meta["checkpoint_path"]).name,
                    meta["checkpoint_sha256"], meta["num_vectors"], meta["supported_dims"], str(index_path), Jsonb(meta)))
        for image in images:
            db.execute("""INSERT INTO product_images(id,product_id,object_key,position,is_primary,is_active)
                       VALUES(%s,%s,%s,%s,%s,%s)""", (image["id"], image["product_id"], image["object_key"],
                       image["position"], image["position"] == 0, image["active"]))
            db.execute("INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES(%s,%s,%s)",
                       (meta["index_version"], image["vector_id"], image["id"]))


def main():
    admin_url = os.environ.get("HYBRID_TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        raise ValueError("Set HYBRID_TEST_ADMIN_DATABASE_URL to a disposable PostgreSQL cluster")
    source = worker_path(os.environ.get("HYBRID_TEST_SOURCE_INDEX", "vector_db.hybrid-20261111")).resolve()
    infer_port = int(os.environ.get("HYBRID_TEST_INFER_PORT", "18201"))
    api_port = int(os.environ.get("HYBRID_TEST_API_PORT", "18280"))
    if infer_port == api_port:
        raise ValueError("Test service ports must differ")
    for port in (infer_port, api_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Integration port {port} is occupied") from exc
    run_id = uuid4()
    database_name = "hybrid_catalog_" + run_id.hex
    db_url = make_conninfo(admin_url, dbname=database_name)
    fixture = REPOSITORY_ROOT / "tmp" / database_name
    fixture.mkdir(parents=True)
    processes, created_database = [], False
    try:
        index_root, index_path, meta, products, images = prepare_fixture(source, fixture, run_id)
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        populate(db_url, index_path, meta, products, images)
        binary = fixture / ("gateway.exe" if os.name == "nt" else "gateway")
        subprocess.run(["go", "build", "-o", str(binary), "./cmd/server"], cwd=REPOSITORY_ROOT / "core-api", check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        env = dict(os.environ, DATABASE_URL=db_url, VECTOR_DB_DIR=str(index_root),
                   CHECKPOINT_PATH=meta["checkpoint_path"], HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", INFERENCE_CONCURRENCY="2", PYTHONUNBUFFERED="1",
                   IMG_BASE_DIR=meta["image_root"], INFER_TIMEOUT="30s",
                   JWT_SECRET="isolated-hybrid-catalog-integration-secret-123456789", GIN_MODE="release")
        env.pop("MINIO_ENDPOINT", None)
        env.pop("TEXT_RETRIEVAL_MODE_DEFAULT", None)
        for name, command, cwd, extra in [
            ("worker", [sys.executable, "-m", "uvicorn", "ai_worker.api.server:app", "--host", "127.0.0.1", "--port", str(infer_port)], WORKER_ROOT, {}),
            ("gateway", [str(binary)], REPOSITORY_ROOT / "core-api", dict(PORT=str(api_port), INFER_API_URL=f"http://127.0.0.1:{infer_port}")),
        ]:
            with (fixture / (name + ".log")).open("w", encoding="utf-8") as log:
                processes.append(subprocess.Popen(command, cwd=cwd, env={**env, **extra}, stdout=log, stderr=subprocess.STDOUT,
                                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        session = requests.Session()
        session.trust_env = False
        base = f"http://127.0.0.1:{api_port}"
        for _ in range(180):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError(f"Fixture service exited; inspect {fixture}")
            try:
                if session.get(base + "/health/ready", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise TimeoutError(f"Fixture startup timed out; inspect {fixture}")

        def post_search(query="adidas", **extra):
            response = session.post(base + "/api/search/text", data=dict(query=query, mrl_dimension=512,
                                    search_mode="adaptive", retrieval_mode="hybrid", **extra), timeout=40)
            response.raise_for_status()
            return response.json()

        def catalog(**extra):
            params = dict(q="adidas", retrieval_mode="hybrid", mrl_dimension=512,
                          search_mode="adaptive", sort="relevance", limit=10, page=1)
            params.update(extra)
            response = session.get(base + "/api/products", params=params, timeout=40)
            response.raise_for_status()
            return response.json()

        found = post_search()
        assert found["index_version"] == meta["index_version"]
        hits = found["data"]
        assert len(hits) == len({item["catalog_product_id"] for item in hits}) == 10
        assert all(item["brand"].casefold().startswith("adidas") for item in hits)
        assert all(-1 <= item["similarity_score"] <= 1 and item["rank_score"] > 0 for item in hits)
        assert found["search_config"]["effective_retrieval_mode"] == "hybrid"
        print("PASS hybrid search: 10 distinct Adidas products, UUID mappings, real cosine", flush=True)
        page1, page2 = catalog(), catalog(page=2)
        assert [item["id"] for item in page1["data"]] == [item["catalog_product_id"] for item in hits]
        assert not ({item["id"] for item in page1["data"]} & {item["id"] for item in page2["data"]})
        assert page1["pagination"]["total"] == page2["pagination"]["total"] >= 200
        assert page1["search"]["truncated"] is True
        assert page1["search"]["index_version"] == meta["index_version"]
        # A term absent from all catalog metadata has exactly the bounded dense
        # pool. This makes total/truncated semantics deterministic.
        bounded = catalog(q="zzzintegrationnomatchzzz")
        assert bounded["pagination"]["total"] == 200 and bounded["search"]["truncated"] is True
        print("PASS shared rank parity, disjoint pagination, bounded total=200/truncated=true", flush=True)

        eligible = [product for product in products if product["active"] and product["images_active"]]
        chosen_category = products[0]["category"]
        for params, predicate in [
            (dict(category=chosen_category), lambda p: p["category"] == chosen_category),
            (dict(min_price=70, max_price=90), lambda p: 70 <= p["price"] <= 90),
            (dict(featured="true"), lambda p: p["featured"]),
            (dict(category=chosen_category, min_price=40, max_price=130, featured="true"),
             lambda p: p["category"] == chosen_category and 40 <= p["price"] <= 130 and p["featured"]),
        ]:
            expected = {p["product_id"] for p in eligible if predicate(p)}
            filtered = catalog(limit=100, **params)
            assert 0 < len(expected) <= 200
            assert filtered["pagination"]["total"] == len(expected), (params, filtered["pagination"], len(expected))
            assert filtered["search"]["truncated"] is False
            actual = {item["id"] for item in filtered["data"]}
            assert actual <= expected and len(actual) == min(100, len(expected))
        empty = catalog(category="__absent_fixture_category__")
        assert empty["data"] == [] and empty["pagination"]["total"] == 0
        assert empty["search"]["truncated"] is False
        print("PASS category/price/featured prefilters and explicit empty eligibility", flush=True)

        # Archive the actual winning image while leaving alternative real views
        # active. Immutable index mappings remain unchanged during hydration.
        winner = hits[0]
        archived = next(image for image in images if image["vector_id"] == winner["vector_id"])
        with psycopg.connect(db_url) as db:
            db.execute("UPDATE product_images SET is_active=false WHERE id=%s", (archived["id"],))
        after = post_search()["data"]
        replacement = next(item for item in after if item["catalog_product_id"] == winner["catalog_product_id"])
        assert replacement["vector_id"] != winner["vector_id"]
        assert replacement["image_url"] != winner["image_url"]
        assert len(after) == len({item["catalog_product_id"] for item in after}) == 10
        with psycopg.connect(db_url) as db:
            assert db.execute("SELECT count(*) FROM index_vector_mappings WHERE index_version_id=%s", (meta["index_version"],)).fetchone()[0] == len(images)
        print("PASS archived winning image uses active alternate and preserves product/mappings", flush=True)
        summary = dict(status="passed", fixture=str(fixture), products=len(products), vectors=len(images),
                       index_version=meta["index_version"], checks=5, database_cleaned=True)
        (fixture / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if created_database:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
            print("CLEANED owned services/database " + database_name, flush=True)


if __name__ == "__main__":
    main()
