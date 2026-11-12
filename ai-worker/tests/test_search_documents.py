"""Lexical snapshots must preserve product identity and immutable vector mappings."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ai_worker.indexing.search_documents import (
    ARTIFACT_NAME, NORMALIZER_VERSION, build_search_documents,
    validate_search_documents, write_search_documents,
)


class SearchDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [
            dict(product_id="[12]", brand="adidas Originals", text="adidas Originals. Blue jacket.", category="JACKETS", subcategory="DENIM", tags=["summer"]),
            dict(product_id="[12]", brand="adidas Originals", text="adidas Originals. Blue jacket.", category="JACKETS", subcategory="DENIM", tags=["summer"]),
            dict(product_id="24", brand="Diesel Black Gold", name="Black jeans", description="Slim jeans", category="JEANS"),
        ]
        self.ids = ["12", "12", "24"]
        self.payload = build_search_documents(self.rows, self.ids)
        self.meta = write_search_documents(self.root, self.payload)

    def rewrite(self, payload):
        data = json.dumps(payload).encode("utf-8")
        (self.root / ARTIFACT_NAME).write_bytes(data)
        self.meta["search_documents_sha256"] = hashlib.sha256(data).hexdigest()

    def test_roundtrip_groups_images_and_preserves_metadata(self):
        result = validate_search_documents(self.root, self.meta, self.ids, 3)
        self.assertEqual(result, self.payload)
        first = result["documents"][0]
        self.assertEqual(first["vector_ids"], [0, 1])
        self.assertEqual(first["name"], "Blue jacket.")
        self.assertEqual(first["tags"], ["summer"])
        self.assertEqual(result["brand_aliases"], {"adidas": ["adidas Originals"], "diesel": ["Diesel Black Gold"]})
        self.assertEqual(result["normalizer_version"], NORMALIZER_VERSION)

    def test_import_remaps_every_document_to_uuid(self):
        ids = ["uuid-one", "uuid-one", "uuid-two"]
        payload = build_search_documents(self.rows, ids)
        meta = write_search_documents(self.root, payload)
        loaded = validate_search_documents(self.root, meta, ids, 3)
        self.assertEqual([doc["product_id"] for doc in loaded["documents"]], ["uuid-one", "uuid-two"])
        with self.assertRaisesRegex(ValueError, "ID mismatch"):
            validate_search_documents(self.root, meta, self.ids, 3)

    def test_aliases_use_brand_boundaries_and_catalog_only(self):
        rows = [dict(product_id=str(i), brand=brand) for i, brand in enumerate(
            ["adidas", "adidas by Stella McCartney", "adidasx", "Not adidas", "Diesel", "Diesel Black Gold", "Diesel Jeans"])]
        aliases = build_search_documents(rows)["brand_aliases"]
        self.assertEqual(aliases["adidas"], ["adidas", "adidas by Stella McCartney"])
        self.assertEqual(aliases["diesel"], ["Diesel", "Diesel Black Gold"])

    def test_legacy_manifest_returns_none_without_lexical_file(self):
        (self.root / ARTIFACT_NAME).unlink()
        self.assertIsNone(validate_search_documents(self.root, {}, self.ids, 3))

    def test_partial_declared_manifest_is_rejected(self):
        for field, value in self.meta.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_search_documents(self.root, {field: value}, self.ids, 3)

    def test_missing_or_changed_artifact_is_rejected(self):
        (self.root / ARTIFACT_NAME).write_text("{}")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            validate_search_documents(self.root, self.meta, self.ids, 3)
        (self.root / ARTIFACT_NAME).unlink()
        with self.assertRaisesRegex(ValueError, "missing or unreadable"):
            validate_search_documents(self.root, self.meta, self.ids, 3)

    def test_semantic_corruption_rejected_even_with_updated_checksum(self):
        mutations = [
            lambda p: p.update(schema_version=2),
            lambda p: p.update(normalizer_version="different"),
            lambda p: p["documents"][0].update(product_id="wrong"),
            lambda p: p["documents"][0].update(vector_ids=[0]),
            lambda p: p["documents"][0].update(vector_ids=[0, 0]),
            lambda p: p["documents"][0].update(vector_ids=[0, True]),
            lambda p: p["documents"][0].update(vector_ids=[0, 99]),
            lambda p: p["documents"][0].update(tags="summer"),
            lambda p: p["documents"][0].update(name=None),
            lambda p: p["documents"].append(copy.deepcopy(p["documents"][0])),
            lambda p: p["brand_aliases"].update(adidas=["Diesel"]),
        ]
        for n, mutate in enumerate(mutations):
            payload = copy.deepcopy(self.payload)
            mutate(payload)
            self.rewrite(payload)
            with self.subTest(mutation=n), self.assertRaises(ValueError):
                validate_search_documents(self.root, self.meta, self.ids, 3)

    def test_builder_rejects_conflicting_identity_and_metadata(self):
        with self.assertRaisesRegex(ValueError, "count differs"):
            build_search_documents(self.rows, ["one"])
        with self.assertRaisesRegex(ValueError, "remapping is inconsistent"):
            build_search_documents(self.rows, ["one", "two", "three"])
        rows = copy.deepcopy(self.rows)
        rows[1]["brand"] = "Different"
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            build_search_documents(rows, self.ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
