"""Importer must reject mismatched provenance and preserve multiline captions."""
import json
from pathlib import Path
import tempfile
import unittest

import faiss
import numpy as np

from import_fashiongen import ARTIFACTS, digest, prepare_source, identity
from ai_worker.indexing.search_documents import build_search_documents, write_search_documents, validate_search_documents


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "images").mkdir()
        (self.root / "images" / "0000000.jpg").write_bytes(b"fixture")
        # A quoted CSV field with embedded Windows CRLF, as in the real corpus.
        (self.root / "metadata.csv").write_bytes(b'image_path,text,product_id,category\r\nimages/0000000.jpg,"Brand. First line\r\nsecond line",[123],JACKETS\r\n')
        for name, value in (("image_paths.json", ["0000000.jpg"]), ("captions.json", ["Brand. First line\nsecond line"]), ("product_ids.json", ["123"])):
            (self.root / name).write_text(json.dumps(value))
        for name in ("image_embeddings.index", "text_embeddings.index"):
            index = faiss.IndexFlatIP(512)
            index.add(np.ones((1, 512), dtype=np.float32))
            faiss.write_index(index, str(self.root / name))
        (self.root / "model.pt").write_bytes(b"source checkpoint hash fixture")
        self.meta = dict(dataset_name="FashionGen", dataset_split="val", clip_model_name="openai/clip-vit-base-patch16", supported_dims=[16, 32, 64, 128, 256, 512], checkpoint_path="checkpoints/model.pt", checkpoint_sha256=digest(self.root / "model.pt"), source_csv_sha256=digest(self.root / "metadata.csv"), num_vectors=1, num_products=1)
        self.meta.update({field: digest(self.root / name) for name, field in ARTIFACTS.items()})
        self.write_meta()

    def write_meta(self):
        (self.root / "index_meta.json").write_text(json.dumps(self.meta))

    def prepare(self):
        return prepare_source(self.root, self.root, self.root)

    def test_embedded_crlf_matches_index_builders_caption(self):
        result = self.prepare()
        self.assertEqual(result[4][0]["text"], "Brand. First line\nsecond line")

    def test_modified_csv_is_rejected(self):
        with (self.root / "metadata.csv").open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "CSV provenance"):
            self.prepare()

    def test_reordered_product_identity_is_rejected(self):
        (self.root / "product_ids.json").write_text('["999"]')
        with self.assertRaisesRegex(ValueError, "id_match=False"):
            self.prepare()

    def test_modified_checkpoint_is_rejected(self):
        (self.root / "model.pt").write_bytes(b"wrong weights")
        with self.assertRaisesRegex(ValueError, "checkpoint hash"):
            self.prepare()

    def test_hybrid_source_is_verified_and_remapped_for_catalog(self):
        rows = self.prepare()[4]
        self.meta.update(write_search_documents(self.root, build_search_documents(rows, ["123"])))
        self.write_meta()
        self.prepare()
        catalog_ids = [identity("product", "123")]
        mapped = build_search_documents(rows, catalog_ids)
        metadata = write_search_documents(self.root, mapped)
        result = validate_search_documents(self.root, metadata, catalog_ids, 1)
        self.assertEqual(result["documents"][0]["product_id"], catalog_ids[0])
        self.assertNotEqual(result["documents"][0]["product_id"], "123")

    def test_declared_corrupt_hybrid_source_is_rejected(self):
        rows = self.prepare()[4]
        self.meta.update(write_search_documents(self.root, build_search_documents(rows, ["123"])))
        self.write_meta()
        (self.root / "search_documents.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
