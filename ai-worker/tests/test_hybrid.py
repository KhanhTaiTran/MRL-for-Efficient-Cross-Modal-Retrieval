"""Product-level retrieval behavior without model downloads or a database."""
import unittest
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ai_worker.retrieval.hybrid import HybridRetriever, normalize_text, tokenize_text


def vector(head=1.0, side=0.0, tail=0.0):
    value = np.zeros(512, dtype=np.float32)
    value[0], value[1], value[100] = head, side, tail
    return value


def document(pid, ids, **fields):
    return dict(product_id=pid, vector_ids=ids, **fields)


class HybridRetrievalTests(unittest.TestCase):
    def test_lexical_only_product_survives_without_an_invented_dense_vote(self):
        engine = HybridRetriever(
            [document("dense", [0], name="Cotton shirt"),
             document("middle", [1], name="Plain shirt"),
             document("rare", [2], description="Meteorite scarf")],
            np.stack([vector(), vector(0.8, 0.6), vector(0.2, 1)]),
            candidate_pool_size=1,
        )
        result = engine.search("meteorite", vector(), search_mode="direct")
        self.assertEqual(len(result["data"]), 2)
        rare = next(item for item in result["data"] if item["catalog_product_id"] == "rare")
        self.assertAlmostEqual(rare["rank_score"], 1 / 61)
        self.assertAlmostEqual(rare["similarity_score"], 0.2 / np.sqrt(1.04), places=6)
        self.assertEqual(rare["vector_id"], 2)
        self.assertTrue(result["truncated"])

    def test_many_photos_do_not_consume_the_unique_product_pool(self):
        documents = [document("many-photos", list(range(14)))]
        vectors = [vector()] * 14
        for i in range(9):
            documents.append(document(f"other-{i}", [14 + i]))
            vectors.append(vector(0.9 - i * 0.03, 0.4))
        engine = HybridRetriever(documents, np.stack(vectors), candidate_pool_size=10)
        result = engine.search("shirt", vector(), search_mode="direct", retrieval_mode="dense")
        self.assertEqual(len(result["data"]), 10)
        self.assertEqual(len({item["catalog_product_id"] for item in result["data"]}), 10)
        first = result["data"][0]
        self.assertEqual(first["catalog_product_id"], "many-photos")
        self.assertEqual(len(first["image_candidates"]), 14)
        self.assertEqual(first["vector_id"], 0)
        self.assertFalse(result["truncated"])

    def test_adaptive_reranks_all_photos_of_the_selected_product(self):
        engine = HybridRetriever(
            [document("two-views", [0, 1]), document("other", [2])],
            np.stack([vector(1, 0, -1), vector(1, 0.1, 1), vector(0.8, 0.6)]),
            candidate_pool_size=1,
        )
        result = engine.search("look", vector(1, 0, 1), retrieval_mode="dense")
        self.assertEqual(result["stage1_dim"], 64)
        self.assertEqual(result["stage2_dim"], 512)
        self.assertEqual(result["data"][0]["vector_id"], 1)
        self.assertGreater(result["data"][0]["similarity_score"], 0.99)

    def test_direct_respects_requested_dimension(self):
        engine = HybridRetriever(
            [document("prefix-winner", [0]), document("full-winner", [1])],
            np.stack([vector(1, 0, -2), vector(0.5, 0.5, 2)]),
        )
        direct = engine.search("look", vector(1, 0, 1), 16, "direct", "dense")
        adaptive = engine.search("look", vector(1, 0, 1), 16, "adaptive", "dense")
        self.assertEqual(direct["data"][0]["catalog_product_id"], "prefix-winner")
        self.assertAlmostEqual(direct["data"][0]["similarity_score"], 1.0)
        self.assertEqual(adaptive["data"][0]["catalog_product_id"], "full-winner")

    def test_eligibility_is_applied_before_both_branch_limits(self):
        engine = HybridRetriever(
            [document("excluded", [0], name="Leather jacket"),
             document("allowed", [1], description="Leather jacket")],
            np.stack([vector(), vector(0.1, 1)]),
            candidate_pool_size=1,
        )
        result = engine.search("leather jacket", vector(), eligible_product_ids=["allowed"])
        self.assertEqual([item["catalog_product_id"] for item in result["data"]], ["allowed"])
        self.assertAlmostEqual(result["data"][0]["rank_score"], 2 / 61)
        empty = engine.search("jacket", vector(), eligible_product_ids=[])
        self.assertEqual(empty["data"], [])

    def test_brand_family_is_prioritized_with_other_brand_fallback(self):
        engine = HybridRetriever(
            [document("other", [0], brand="Other", name="Jacket"),
             document("originals", [1], brand="adidas Originals", name="Jacket"),
             document("hyke", [2], brand="adidas Originals by Hyke", name="Sandals")],
            np.stack([vector(), vector(0.5, 0.8), vector(0.3, 1)]),
        )
        result = engine.search("ADIDAS jacket", vector(), search_mode="direct")
        ids = [item["catalog_product_id"] for item in result["data"]]
        self.assertEqual(ids[-1], "other")
        self.assertEqual(set(ids[:2]), {"originals", "hyke"})
        self.assertEqual(result["matched_brand"], "adidas")
        exact = engine.search("adidas Originals by Hyke sandals", vector(), search_mode="direct")
        self.assertEqual(exact["matched_brand"], "adidas originals by hyke")
        self.assertEqual(exact["data"][0]["catalog_product_id"], "hyke")
        dense = engine.search("adidas", vector(), search_mode="direct", retrieval_mode="dense")
        self.assertEqual(dense["data"][0]["catalog_product_id"], "other")
        self.assertIsNone(dense["matched_brand"])
        unmatched = engine.search("adidasx", vector(), search_mode="direct")
        self.assertIsNone(unmatched["matched_brand"])

    def test_residual_attributes_order_the_branded_lexical_branch(self):
        engine = HybridRetriever(
            [document("adidas-shoes", [0], brand="adidas Originals", name="Shoes"),
             document("adidas-jacket", [1], brand="adidas by Stella McCartney", name="Jacket")],
            np.stack([vector(), vector(0.3, 1)]), candidate_pool_size=1,
        )
        result = engine.search("adidas jacket", vector(), search_mode="direct")
        jacket = next(item for item in result["data"] if item["catalog_product_id"] == "adidas-jacket")
        self.assertAlmostEqual(jacket["rank_score"], 1 / 61)

    def test_full_description_does_not_promote_unrelated_same_brand_items(self):
        engine = HybridRetriever(
            [document("brand-only", [0], brand="adidas Originals", name="Blue shorts"),
             document("description-match", [1], brand="Other", name="Black cotton shirt",
                      description="Long sleeve black cotton shirt with raw edges and tonal stitching")],
            np.stack([vector(0.1, 1), vector()]),
        )
        caption = "adidas Originals. Long sleeve black cotton shirt with raw edges and tonal stitching."
        result = engine.search(caption, vector(), search_mode="direct")
        self.assertIsNone(result["matched_brand"])
        self.assertEqual(result["data"][0]["catalog_product_id"], "description-match")
        short = engine.search("adidas black shirt", vector(), search_mode="direct")
        self.assertEqual(short["matched_brand"], "adidas")
        self.assertEqual(short["data"][0]["catalog_product_id"], "brand-only")

    def test_unicode_punctuation_stemming_and_field_weights(self):
        self.assertEqual(normalize_text(" ＡＤＩＤＡＳ—T-SHIRTS "), "adidas t shirts")
        self.assertEqual(tokenize_text("T-SHIRTS"), tokenize_text("t shirt"))
        self.assertEqual(tokenize_text("adidas", stem=False), ("adidas",))
        engine = HybridRetriever(
            [document("title", [0], name="Jackets"),
             document("description", [1], name="Other", description="Jacket")],
            np.stack([vector(), vector(0.5, 1)]),
        )
        scores = engine._lexical_scores("jacket")
        self.assertGreater(scores[0], scores[1])
        with ThreadPoolExecutor(max_workers=8) as workers:
            tokens = list(workers.map(tokenize_text, ["jackets shirts hoodies"] * 64))
        self.assertEqual(len(set(tokens)), 1)

    def test_oov_or_stopwords_do_not_create_lexical_votes(self):
        engine = HybridRetriever(
            [document("a", [0], brand="The Row", name="Shirt"),
             document("b", [1], name="Jacket")], np.stack([vector(), vector(0.1, 1)]),
        )
        for query in ("qwertyuiop", "the and of"):
            result = engine.search(query, vector(), search_mode="direct")
            self.assertEqual(len(result["data"]), 2)
            self.assertAlmostEqual(result["data"][0]["rank_score"], 1 / 61)

    def test_legacy_lexical_fallback_is_explicit(self):
        engine = HybridRetriever(
            [document("p", [0])], np.stack([vector()]), lexical_available=False,
        )
        result = engine.search("shirt", vector())
        self.assertEqual(result["effective_retrieval_mode"], "dense")
        self.assertEqual(result["fallback_reason"], "lexical_index_unavailable")
        self.assertEqual(result["data"][0]["catalog_product_id"], "p")

    def test_ties_are_deterministic_by_product_then_vector_id(self):
        engine = HybridRetriever(
            [document("z", [0]), document("a", [2, 1])],
            np.stack([vector(), vector(), vector()]),
        )
        results = [engine.search("shirt", vector(), search_mode="direct") for _ in range(2)]
        self.assertEqual(results[0]["data"], results[1]["data"])
        self.assertEqual(results[0]["data"][0]["catalog_product_id"], "a")
        self.assertEqual(results[0]["data"][0]["vector_id"], 1)

    def test_rejects_ambiguous_or_incomplete_vector_mappings(self):
        vectors = np.stack([vector(), vector()])
        for documents in (
            [document("p", [0])],
            [document("p", [0]), document("p", [1])],
            [document("p", [0]), document("q", [0, 1])],
            [document("p", [0, 2])],
            [document("p", [])],
        ):
            with self.assertRaises(ValueError):
                HybridRetriever(documents, vectors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
