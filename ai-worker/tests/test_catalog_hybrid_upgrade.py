"""Metadata-only migration validation and opt-in isolated PostgreSQL integration.

TEST_DATABASE_URL is an administrator URL. SQL tests create/drop only a uniquely
named test database; they never use its existing catalog.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import faiss
import numpy as np
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_worker.indexing import upgrade_hybrid as migration
from ai_worker.indexing.search_documents import validate_search_documents
from ai_worker.paths import REPOSITORY_ROOT


def fixture(root):
    version, product_a, product_b = str(uuid4()), str(uuid4()), str(uuid4())
    folder = root / version
    folder.mkdir()
    ids = [product_a, product_a, product_b]
    for filename in ("image_embeddings.index", "text_embeddings.index"):
        index = faiss.IndexFlatIP(512)
        vectors = np.eye(3, 512, dtype="float32")
        index.add(vectors)
        faiss.write_index(index, str(folder / filename))
    for filename, values in [("image_paths.json", ["a.jpg", "b.jpg", "c.jpg"]),
                             ("captions.json", ["old caption"] * 3), ("product_ids.json", ids)]:
        (folder / filename).write_text(json.dumps(values), encoding="utf-8")
    (folder / "checkpoint.pt").write_bytes(b"model weights are copied, never loaded")
    meta = dict(index_version=version, num_vectors=3, num_products=2, supported_dims=[512],
                checkpoint_path=str(folder / "checkpoint.pt"),
                checkpoint_sha256=migration.digest(folder / "checkpoint.pt"))
    meta.update({field: migration.digest(folder / filename) for filename, field in migration.ARTIFACTS.items()})
    (folder / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    source = dict(id=version, version_tag="catalog-" + version, index_path=str(folder),
                  num_vectors=3, supported_dims=[512], checkpoint_sha=meta["checkpoint_sha256"], metadata=meta)
    return source, folder, meta, ids


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.folder, self.meta, self.ids = fixture(self.root)

    def test_full_artifacts_and_canonical_uuid_mapping(self):
        result = migration.validate_source(self.root, self.source)
        self.assertEqual(result[3], self.ids)
        self.assertIsNone(result[4])

    def test_changed_embeddings_and_checkpoint_are_rejected(self):
        for filename in ("image_embeddings.index", "checkpoint.pt"):
            path = self.folder / filename
            before = path.read_bytes()
            path.write_bytes(b"changed")
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "checksum"):
                migration.validate_source(self.root, self.source)
            path.write_bytes(before)

    def test_outside_root_and_noncanonical_product_mapping_are_rejected(self):
        source = dict(self.source, index_path=str(self.root.parent))
        with self.assertRaisesRegex(ValueError, "outside VECTOR_DB_DIR"):
            migration.validate_source(self.root, source)
        path = self.folder / "product_ids.json"
        path.write_text('["numeric", "numeric", "numeric"]')
        self.meta["product_ids_sha256"] = migration.digest(path)
        (self.folder / "index_meta.json").write_text(json.dumps(self.meta))
        with self.assertRaisesRegex(ValueError, "canonical SQL UUIDs"):
            migration.validate_source(self.root, self.source)

    def test_rehashed_invalid_faiss_shape_is_rejected(self):
        index = faiss.IndexFlatIP(64)
        index.add(np.eye(3, 64, dtype="float32"))
        path = self.folder / "image_embeddings.index"
        faiss.write_index(index, str(path))
        self.meta["image_index_sha256"] = migration.digest(path)
        (self.folder / "index_meta.json").write_text(json.dumps(self.meta))
        with self.assertRaisesRegex(ValueError, "nonempty 512D"):
            migration.validate_source(self.root, self.source)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for isolated SQL migration integration")
class CatalogUpgradeSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_url = os.environ["TEST_DATABASE_URL"]
        cls.database_name = "hybrid_upgrade_test_" + uuid4().hex
        cls.db_url = make_conninfo(cls.admin_url, dbname=cls.database_name)
        with psycopg.connect(cls.admin_url, autocommit=True) as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        try:
            with psycopg.connect(cls.db_url) as db:
                for path in sorted((REPOSITORY_ROOT / "infra" / "migrations").glob("*.up.sql")):
                    db.execute(path.read_text(encoding="utf-8"), prepare=False)
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.admin_url, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.folder, self.meta, self.ids = fixture(self.root)
        self.image_ids = [str(uuid4()) for _ in self.ids]
        with psycopg.connect(self.db_url) as db:
            db.execute("TRUNCATE products,ai_index_versions,ai_index_jobs CASCADE")
            for n, pid in enumerate(dict.fromkeys(self.ids)):
                db.execute("""INSERT INTO products(id,handle,name,description,brand,category,base_price,
                    is_active,is_featured,tags,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s)""",
                    (pid, pid, "SQL title " + str(n), "Current SQL description", "adidas Originals" if n == 0 else "Diesel",
                     "TOPS", 79 + n, n == 0, ["cotton"], Jsonb(dict(subcategory="SHIRTS"))))
            self.insert_version(db, self.source, active=True)
            for n, (pid, iid) in enumerate(zip(self.ids, self.image_ids)):
                db.execute("INSERT INTO product_images(id,product_id,object_key,is_active) VALUES(%s,%s,%s,%s)",
                           (iid, pid, iid + ".jpg", n != 1))
                db.execute("INSERT INTO index_vector_mappings(index_version_id,vector_id,product_image_id) VALUES(%s,%s,%s)",
                           (self.source["id"], n, iid))

    @staticmethod
    def insert_version(db, source, active=False):
        db.execute("""INSERT INTO ai_index_versions(id,version_tag,index_path,num_vectors,supported_dims,
            checkpoint_name,checkpoint_sha,metadata,is_active) VALUES(%s,%s,%s,%s,%s,'checkpoint.pt',%s,%s,%s)""",
            (source["id"], source["version_tag"], source["index_path"], source["num_vectors"],
             source["supported_dims"], source["checkpoint_sha"], Jsonb(source["metadata"]), active))

    def state(self):
        with psycopg.connect(self.db_url, row_factory=dict_row) as db:
            return dict(active=str(db.execute("SELECT id FROM ai_index_versions WHERE is_active").fetchone()["id"]),
                        versions=db.execute("SELECT count(*) n FROM ai_index_versions").fetchone()["n"],
                        products=db.execute("SELECT id,base_price,is_active,search_revision FROM products ORDER BY id").fetchall())

    def test_publish_preserves_bytes_commerce_inactive_mappings_and_is_idempotent(self):
        before = self.state()
        files = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        result = migration.upgrade(self.db_url, self.root)
        self.assertTrue(result["activated"])
        self.assertEqual(result["previous_active_version"], self.source["id"])
        after = self.state()
        self.assertEqual(after["versions"], 2)
        self.assertEqual(after["products"], before["products"])
        self.assertEqual(files, {path.name: path.read_bytes() for path in self.folder.iterdir()})
        destination = Path(result["index_path"])
        for filename in (*migration.ARTIFACTS, "checkpoint.pt"):
            self.assertEqual((destination / filename).read_bytes(), files[filename])
        meta = json.loads((destination / "index_meta.json").read_text())
        payload = validate_search_documents(destination, meta, self.ids, 3)
        self.assertEqual(payload["documents"][0]["name"], "SQL title 0")
        self.assertEqual(payload["documents"][0]["vector_ids"], [0, 1])
        self.assertEqual(payload["documents"][1]["product_id"], self.ids[2])
        with psycopg.connect(self.db_url) as db:
            for version in (self.source["id"], result["index_version"]):
                self.assertEqual(db.execute("SELECT vector_id,product_image_id::text FROM index_vector_mappings WHERE index_version_id=%s ORDER BY vector_id", (version,)).fetchall(), list(enumerate(self.image_ids)))
        repeated = migration.upgrade(self.db_url, self.root)
        self.assertEqual(repeated["status"], "unchanged")
        self.assertEqual(self.state()["versions"], 2)

    def test_dry_run_changes_neither_sql_nor_files(self):
        before = self.state()
        result = migration.upgrade(self.db_url, self.root, dry_run=True)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(self.state(), before)
        self.assertEqual(list(self.root.iterdir()), [self.folder])

    def test_corrupt_source_and_wrong_product_ownership_cannot_publish(self):
        with psycopg.connect(self.db_url) as db:
            db.execute("UPDATE product_images SET product_id=%s WHERE id=%s", (self.ids[2], self.image_ids[1]))
        before = self.state()
        with self.assertRaisesRegex(ValueError, "ownership differs"):
            migration.upgrade(self.db_url, self.root)
        self.assertEqual(self.state(), before)
        (self.folder / "image_embeddings.index").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            migration.upgrade(self.db_url, self.root)
        self.assertEqual(self.state(), before)

    def test_running_job_or_owned_publisher_lock_are_rejected(self):
        with psycopg.connect(self.db_url) as db:
            db.execute("INSERT INTO ai_index_jobs(status) VALUES('running')")
        with self.assertRaisesRegex(RuntimeError, "job is running"):
            migration.upgrade(self.db_url, self.root)
        with psycopg.connect(self.db_url, autocommit=True) as db:
            db.execute("DELETE FROM ai_index_jobs")
            db.execute("SELECT pg_advisory_lock(%s)", (migration.LOCKS[0],))
            try:
                with self.assertRaisesRegex(RuntimeError, "publisher owns"):
                    migration.upgrade(self.db_url, self.root)
            finally:
                db.execute("SELECT pg_advisory_unlock(%s)", (migration.LOCKS[0],))
        self.assertEqual(self.state()["versions"], 1)

    def alternate_active(self):
        alternate, _, _, _ = fixture(self.root)
        with psycopg.connect(self.db_url) as db:
            db.execute("UPDATE ai_index_versions SET is_active=false WHERE is_active")
            self.insert_version(db, alternate, active=True)
        return alternate

    def test_explicit_inactive_source_preserves_previous_active_and_restores_selected_gallery(self):
        alternate = self.alternate_active()
        result = migration.upgrade(self.db_url, self.root, source_version=self.source["id"])
        self.assertEqual(result["previous_active_version"], alternate["id"])
        self.assertEqual(result["source_index_version"], self.source["id"])
        self.assertEqual(self.state()["active"], result["index_version"])
        self.assertEqual(self.state()["versions"], 3)

    def test_external_active_change_during_validation_is_rejected(self):
        original = migration.validate_source
        def change_after_validation(*args):
            result = original(*args)
            self.alternate_active()
            return result
        with patch.object(migration, "validate_source", side_effect=change_after_validation):
            with self.assertRaisesRegex(RuntimeError, "version changed"):
                migration.upgrade(self.db_url, self.root)
        self.assertEqual(self.state()["versions"], 2)
        self.assertFalse((self.root / "versions").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
