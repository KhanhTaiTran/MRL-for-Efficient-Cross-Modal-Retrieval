"""Metadata-only upgrades preserve embeddings and leave the active source intact."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.indexing.upgrade_hybrid_index import ARTIFACTS, upgrade
from ai_worker.indexing.search_documents import validate_search_documents


class HybridUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "vector_db"
        self.source.mkdir()
        self.output = self.root / "vector_db_hybrid"
        self.csv = self.root / "metadata.csv"
        self.csv.write_text('image_path,text,product_id,brand,category,subcategory\nimages/a.jpg,Diesel. Blue jacket.,[12],Diesel,JACKETS,DENIM\nimages/b.jpg,Diesel. Blue jacket.,[12],Diesel,JACKETS,DENIM\n', encoding="utf-8")
        for filename in ("image_embeddings.index", "text_embeddings.index"):
            (self.source / filename).write_bytes(("unchanged embeddings: " + filename).encode())
        for filename, values in [("image_paths.json", ["a.jpg", "b.jpg"]), ("captions.json", ["Diesel. Blue jacket."] * 2), ("product_ids.json", ["12", "12"])]:
            (self.source / filename).write_text(json.dumps(values))
        self.meta = dict(dataset_name="FashionGen", dataset_split="val", index_version="old",
                         num_vectors=2, num_products=1,
                         checkpoint_path="checkpoints/original.pt", checkpoint_sha256="f" * 64,
                         source_csv_sha256=self.digest(self.csv))
        self.meta.update({field: self.digest(self.source / name) for name, field in ARTIFACTS.items() if name != "product_ids.json"})
        self.write_meta()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_meta(self):
        (self.source / "index_meta.json").write_text(json.dumps(self.meta))

    def test_new_snapshot_preserves_source_and_embedding_bytes(self):
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        result = upgrade(self.source, self.csv, self.output)
        self.assertFalse(result["activated"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})
        for filename in ARTIFACTS:
            self.assertEqual((self.output / filename).read_bytes(), before[filename])
        meta = json.loads((self.output / "index_meta.json").read_text())
        self.assertNotEqual(meta["index_version"], "old")
        self.assertEqual(meta["checkpoint_sha256"], self.meta["checkpoint_sha256"])
        self.assertEqual(meta["checkpoint_path"], self.meta["checkpoint_path"])
        payload = validate_search_documents(self.output, meta, ["12", "12"], 2)
        self.assertEqual(payload["documents"][0]["vector_ids"], [0, 1])
        self.assertEqual(payload["documents"][0]["brand"], "Diesel")

    def test_existing_or_nonsibling_destination_is_rejected(self):
        self.output.mkdir()
        for target in [self.source, self.output, self.source / "inside"]:
            with self.subTest(target=str(target)), self.assertRaisesRegex(ValueError, "new sibling"):
                upgrade(self.source, self.csv, target)

    def test_modified_csv_or_embeddings_are_rejected(self):
        (self.source / "image_embeddings.index").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            upgrade(self.source, self.csv, self.output)
        self.csv.write_text("changed")
        with self.assertRaisesRegex(ValueError, "CSV provenance"):
            upgrade(self.source, self.csv, self.output)
        self.assertFalse(self.output.exists())

    def test_product_mapping_mismatch_is_rejected(self):
        (self.source / "product_ids.json").write_text('["wrong", "wrong"]')
        with self.assertRaisesRegex(ValueError, "mapping differs"):
            upgrade(self.source, self.csv, self.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
