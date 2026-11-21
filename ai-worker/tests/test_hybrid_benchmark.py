"""Benchmark labels and release gates cannot turn proxy scores into proof."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from ai_worker.benchmarks.hybrid import (
    DEFAULT_QUERIES, METHODS, SHORT_GROUPS, evaluate_gate, load_qrels,
    load_queries, proxy_grades, ranking_metrics, run_benchmark,
)
from ai_worker.retrieval.hybrid import HybridRetriever


def gate_fixture():
    queries = [{"id": f"test-{i}", "split": "test", "group": SHORT_GROUPS[i % 6]} for i in range(40)]
    queries += [{"id": f"control-{i}", "split": "control", "group": "full_caption"} for i in range(10)]
    metric = {"ndcg_at_10": 0.5, "queries": 40}
    summary = {
        method: {"test": dict(metric), "controls": {"ndcg_at_10": 0.8},
                 "groups": {group: dict(metric) for group in SHORT_GROUPS}}
        for method in METHODS
    }
    summary["hybrid"]["test"]["ndcg_at_10"] = 0.6
    report = {"index_version": "fixture", "queries": queries, "summary": summary, "lexical_available": True, "lexical_and_fusion_ms": {"p95": 20.0}}
    pool = [{"query_id": query["id"], "product_id": "p"} for query in queries]
    qrels = {"index_version": "fixture", "source": "human", "independently_judged": True,
             "judgments": {query["id"]: {"p": 3} for query in queries}}
    return report, qrels, pool


class ArrayIndex:
    def __init__(self, vectors):
        self.vectors = vectors

    def search(self, query, k):
        scores = self.vectors @ query[0]
        ids = np.argsort(-scores, kind="stable")[:k]
        output_ids = np.full((1, k), -1, dtype=np.int64)
        output_scores = np.full((1, k), -np.inf, dtype=np.float32)
        output_ids[0, :len(ids)] = ids
        output_scores[0, :len(ids)] = scores[ids]
        return output_scores, output_ids


class HybridBenchmarkTests(unittest.TestCase):
    def test_fixture_has_stratified_short_holdouts_and_controls(self):
        fixture = json.loads(DEFAULT_QUERIES.read_text(encoding="utf-8"))["queries"]
        self.assertEqual(len(fixture), 75)
        short = [query for query in fixture if query["group"] in SHORT_GROUPS]
        self.assertEqual(len(short), 60)
        self.assertEqual(sum(query["split"] == "dev" for query in short), 20)
        self.assertEqual(sum(query["split"] == "test" for query in short), 40)
        for group in SHORT_GROUPS:
            grouped = [query for query in short if query["group"] == group]
            self.assertEqual(len(grouped), 10)
            self.assertTrue(any(query["split"] == "dev" for query in grouped))
            self.assertTrue(any(query["split"] == "test" for query in grouped))
        self.assertEqual(sum(query["group"] == "full_caption" for query in fixture), 10)
        self.assertEqual(sum(query["group"] == "unknown" for query in fixture), 5)

    def test_full_caption_controls_are_deterministic_product_quantiles(self):
        documents = [dict(product_id="z", description="Last caption"), dict(product_id="a", description="First caption")]
        first = load_queries(DEFAULT_QUERIES, documents)
        second = load_queries(DEFAULT_QUERIES, list(reversed(documents)))
        self.assertEqual(first, second)
        controls = [query for query in first if query["group"] == "full_caption"]
        self.assertEqual(controls[0]["target_product_id"], "a")
        self.assertEqual(controls[-1]["target_product_id"], "z")

    def test_metrics_use_product_dedup_and_fixed_precision_denominator(self):
        result = ranking_metrics(["best", "best", "irrelevant", "okay"], {"best": 3, "okay": 1})
        self.assertEqual(result["precision_at_10"], 0.2)
        self.assertEqual(result["unique_products_at_10"], 3)
        self.assertGreater(result["ndcg_at_10"], 0.95)
        self.assertLess(result["ndcg_at_10"], 1)
        self.assertEqual(ranking_metrics(["none"], {})["ndcg_at_10"], 0)

    def test_proxy_labels_distinguish_brand_fallback_and_paired_caption(self):
        documents = [dict(product_id="brand", brand="adidas Originals", category="JACKETS & COATS", description="Blue jacket"),
                     dict(product_id="fallback", brand="Other", category="JACKETS & COATS", description="Blue jacket"),
                     dict(product_id="wrong", brand="Other", category="DRESSES", description="Blue dress")]
        query = {"proxy": {"brand_prefix": "adidas", "category_any": ["JACKETS & COATS"], "terms": ["blue"]}}
        self.assertEqual(proxy_grades(query, documents), {"brand": 3, "fallback": 2})
        self.assertEqual(proxy_grades({"target_product_id": "wrong"}, documents), {"wrong": 3})
        self.assertEqual(proxy_grades({"proxy": {"no_relevant": True}}, documents), {})

    def test_good_numeric_metrics_cannot_pass_without_independent_judgments(self):
        report, qrels, pool = gate_fixture()
        self.assertTrue(evaluate_gate(report, qrels, pool)["passed"])
        for supplied in (None, dict(qrels, source="metadata_proxy"), dict(qrels, independently_judged=False)):
            gate = evaluate_gate(report, supplied, pool)
            self.assertFalse(gate["passed"])
            self.assertFalse(gate["independently_judged"])
        reviewed = dict(qrels, source="independent_review", judgment_modality="catalog_text")
        self.assertTrue(evaluate_gate(report, reviewed, pool)["passed"])

    def test_every_heldout_and_control_pool_candidate_must_be_judged(self):
        report, qrels, pool = gate_fixture()
        pool.append({"query_id": "test-0", "product_id": "unjudged"})
        gate = evaluate_gate(report, qrels, pool)
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["pooled_judgments_missing"], 1)
        qrels["judgments"]["test-0"]["unjudged"] = 0
        self.assertTrue(evaluate_gate(report, qrels, pool)["passed"])

    def test_independent_qrels_must_match_index_and_query_provenance(self):
        report, qrels, pool = gate_fixture()
        self.assertFalse(evaluate_gate(report, dict(qrels, index_version="old"), pool)["passed"])
        report.update(queries_sha256="query-hash", search_documents_sha256="document-hash")
        self.assertFalse(evaluate_gate(report, qrels, pool)["passed"])
        qrels.update(queries_sha256="query-hash", search_documents_sha256="document-hash")
        self.assertTrue(evaluate_gate(report, qrels, pool)["passed"])

    def test_gate_rejects_group_or_control_regressions_and_latency(self):
        for mutation in ("uplift", "group", "control", "latency", "baseline", "subset", "lexical"):
            report, qrels, pool = gate_fixture()
            if mutation == "uplift":
                report["summary"]["hybrid"]["test"]["ndcg_at_10"] = 0.51
            elif mutation == "group":
                report["summary"]["hybrid"]["groups"]["synonym"]["ndcg_at_10"] = 0.4
            elif mutation == "control":
                report["summary"]["hybrid"]["controls"]["ndcg_at_10"] = 0.7
            elif mutation == "latency":
                report["lexical_and_fusion_ms"]["p95"] = 50.1
            elif mutation == "baseline":
                report["summary"]["product_dense"]["test"]["ndcg_at_10"] = 0
            elif mutation == "subset":
                report["queries"] = report["queries"][:10]
            elif mutation == "lexical":
                report["lexical_available"] = False
            self.assertFalse(evaluate_gate(report, qrels, pool)["passed"], mutation)

    def test_qrels_require_integer_grades_zero_through_three(self):
        path = Path("fixture-qrels.json")
        for grade in (-1, 4, 1.5, True, "3"):
            with patch.object(Path, "read_text", return_value=json.dumps({"judgments": {"q": {"p": grade}}})):
                with self.assertRaises(ValueError):
                    load_qrels(path)
        with patch.object(Path, "read_text", return_value=json.dumps({"judgments": {"q": {"p": 0}}})):
            self.assertEqual(load_qrels(path)["judgments"]["q"]["p"], 0)

    def test_ablations_share_each_encoding_and_export_unjudged_pool(self):
        vectors = np.zeros((2, 512), dtype=np.float32)
        vectors[:, 0] = 1
        vectors[1, 1] = 1
        engine = HybridRetriever(
            [dict(product_id="a", vector_ids=[0], brand="adidas Originals", name="Jacket", description="Blue jacket", category="JACKETS & COATS"),
             dict(product_id="b", vector_ids=[1], brand="Other", name="Shirt", description="White shirt", category="SHIRTS")],
            vectors,
        )
        snapshot = dict(product_retriever=engine, active_version="fixture", image_indexes={64: ArrayIndex(engine._vectors[64])},
                        product_ids=["a", "b"], image_paths=["a.png", "b.png"])
        queries = [{"id": "q", "query": "adidas jacket", "group": "brand_attribute", "split": "test",
                    "proxy": {"brand_prefix": "adidas", "category_any": ["JACKETS & COATS"]}}]
        calls = []
        def encode(query):
            calls.append(query)
            return vectors[0], 2.0
        report, pool = run_benchmark(snapshot, queries, repeats=2, warmup=1, encoder=encode)
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["judgment_source"], "metadata_proxy")
        self.assertEqual(set(report["summary"]), set(METHODS))
        self.assertEqual(report["shared_encode_ms"]["p50"], 2)
        self.assertFalse(report["gate"]["passed"])
        self.assertTrue(pool)
        self.assertTrue(all(row["relevance"] is None for row in pool))
        human = {"source": "human", "independently_judged": True, "judgments": {"q": {"a": 3, "b": 0}}}
        independent, _ = run_benchmark(snapshot, queries, qrels=human, repeats=1, warmup=0, encoder=encode)
        self.assertEqual(independent["judgment_source"], "human")
        self.assertFalse(independent["gate"]["passed"])
        unjudged, _ = run_benchmark(snapshot, queries, qrels=dict(human, judgments={}), repeats=1, warmup=0, encoder=encode)
        self.assertIsNone(unjudged["queries"][0]["metrics"])
        self.assertEqual(unjudged["queries"][0]["judgment_source"], "unjudged")
        self.assertIsNone(unjudged["summary"]["hybrid"]["test"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
