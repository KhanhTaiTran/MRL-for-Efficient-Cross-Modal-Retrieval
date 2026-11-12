"""The first managed rebuild must archive lexical artifacts with its source."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_worker.indexing import worker
from ai_worker.indexing.search_documents import build_search_documents, write_search_documents, validate_search_documents


class FakeDB:
    def __init__(self):
        self.statements = []

    def execute(self, sql, args):
        self.statements.append((sql, args))


class IndexArchiveDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for filename, _ in worker.ARTIFACTS:
            (self.root / filename).write_bytes(b"fixture")
        (self.root / "product_ids.json").write_text('["one"]')
        checkpoint = self.root / "checkpoint.pt"
        checkpoint.write_bytes(b"unchanged checkpoint")
        self.meta = dict(index_version="old", num_vectors=1, checkpoint_path=str(checkpoint))
        self.meta.update({field: worker.digest(self.root / name) for name, field in worker.ARTIFACTS})
        self.db = FakeDB()

    def preserve(self):
        (self.root / "index_meta.json").write_text(json.dumps(self.meta))
        with patch.object(worker, "ROOT", self.root):
            return worker.preserve_source(self.db, dict(id="version-one", index_path=str(self.root)))

    def test_new_archive_copies_hashed_lexical_state(self):
        payload = build_search_documents([dict(product_id="one", brand="Diesel", name="Jeans")])
        self.meta.update(write_search_documents(self.root, payload))
        before = (self.root / "search_documents.json").read_bytes()
        folder, meta = self.preserve()
        self.assertEqual((folder / "search_documents.json").read_bytes(), before)
        self.assertEqual(validate_search_documents(folder, meta, ["one"], 1), payload)
        self.assertEqual((folder / "checkpoint.pt").read_bytes(), b"unchanged checkpoint")
        self.assertEqual(len(self.db.statements), 1)

    def test_legacy_archive_remains_legacy(self):
        folder, meta = self.preserve()
        self.assertFalse((folder / "search_documents.json").exists())
        self.assertIsNone(validate_search_documents(folder, meta, ["one"], 1))

    def test_corrupt_declared_source_never_updates_sql(self):
        payload = build_search_documents([dict(product_id="one", brand="Diesel")])
        self.meta.update(write_search_documents(self.root, payload))
        (self.root / "search_documents.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.preserve()
        self.assertFalse((self.root / "versions").exists())
        self.assertEqual(self.db.statements, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
