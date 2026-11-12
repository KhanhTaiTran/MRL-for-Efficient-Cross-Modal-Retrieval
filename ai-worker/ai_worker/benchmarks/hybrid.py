"""Compare short-query retrieval with shared encodings and honest judgments.

Without --qrels, relevance scores are explicitly metadata proxies. They are
useful diagnostics, but can never satisfy the optional release gate. Export the
pooled candidates, judge them independently (0..3), and supply a qrels JSON file:

{"source": "independent_review", "independently_judged": true,
 "judgment_modality": "catalog_text",
 "judgments": {"query_id": {"catalog_product_id": 0}}}

Only --gate turns the acceptance checks into a failing process exit status.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
import json
import hashlib
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np

from ai_worker.retrieval.hybrid import normalize_text, tokenize_text


METHODS = ("legacy_dense", "product_dense", "bm25", "hybrid")
SHORT_GROUPS = ("brand", "brand_attribute", "category", "color_category", "material_category", "synonym")
DEFAULT_QUERIES = Path(__file__).with_name("fixtures") / "hybrid_queries.json"
INDEPENDENT_SOURCES = frozenset(("human", "independent_human", "independent_review"))


def _judgment_source(qrels):
    return qrels.get("judgment_source", qrels.get("source")) if qrels else None


def load_queries(path: Path, documents: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload["queries"]
    if len({record["id"] for record in queries}) != len(queries):
        raise ValueError("Query IDs must be unique")
    products = sorted(documents, key=lambda item: str(item["product_id"]))
    resolved = []
    for record in queries:
        query = dict(record)
        if "caption_fraction" in query:
            if not products:
                raise ValueError("Full-caption controls need a nonempty corpus")
            fraction = float(query["caption_fraction"])
            if not 0 <= fraction <= 1:
                raise ValueError("Caption quantiles must be between zero and one")
            product = products[round(fraction * (len(products) - 1))]
            query["query"] = str(product.get("description") or product.get("name") or "")
            query["target_product_id"] = str(product["product_id"])
        if not str(query.get("query", "")).strip():
            raise ValueError(f"Empty query: {query['id']}")
        resolved.append(query)
    return resolved


def load_qrels(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    judgments = payload.get("judgments")
    if not isinstance(judgments, dict):
        raise ValueError("Qrels must contain a judgments object keyed by query ID")
    for query_id, grades in judgments.items():
        if not isinstance(query_id, str) or not isinstance(grades, dict):
            raise ValueError("Qrels must map each query ID to product grades")
        for product_id, grade in grades.items():
            if not isinstance(product_id, str) or type(grade) is not int or not 0 <= grade <= 3:
                raise ValueError("Each relevance judgment must be an integer from 0 to 3")
    return payload


def proxy_grades(query: Mapping[str, Any], documents: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Catalog-derived labels; never presented as independent ground truth."""
    if query.get("target_product_id"):
        return {str(query["target_product_id"]): 3}
    constraint = query.get("proxy", {})
    if constraint.get("no_relevant"):
        return {}
    brand = normalize_text(constraint.get("brand_prefix", ""))
    categories = {normalize_text(value) for value in constraint.get("category_any", [])}
    subcategories = {normalize_text(value) for value in constraint.get("subcategory_any", [])}
    required_terms = set(tokenize_text(" ".join(constraint.get("terms", []))))
    grades = {}
    for document in documents:
        actual_brand = normalize_text(document.get("brand", ""))
        brand_match = bool(brand and (actual_brand == brand or actual_brand.startswith(brand + " ")))
        type_match = not (categories or subcategories) or (
            normalize_text(document.get("category", "")) in categories
            or normalize_text(document.get("subcategory", "")) in subcategories
        )
        if required_terms:
            content = " ".join(str(document.get(field, "") or "") for field in ("name", "description", "tags"))
            attributes_match = required_terms.issubset(tokenize_text(content))
        else:
            attributes_match = True
        relevant = type_match and attributes_match
        if brand:
            grade = 3 if brand_match and relevant else 1 if brand_match else 2 if relevant and (categories or subcategories or required_terms) else 0
        else:
            grade = 3 if relevant else 1 if type_match else 0
        if grade:
            grades[str(document["product_id"])] = grade
    return grades


def ranking_metrics(ranking: Sequence[str], grades: Mapping[str, int], k: int = 10) -> dict[str, float]:
    unique = list(dict.fromkeys(ranking))[:k]
    dcg = sum((2 ** grades.get(pid, 0) - 1) / math.log2(rank + 2) for rank, pid in enumerate(unique))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(ideal))
    return {
        "ndcg_at_10": dcg / idcg if idcg else 0.0,
        "precision_at_10": sum(grades.get(pid, 0) > 0 for pid in unique) / k,
        "unique_products_at_10": float(len(unique)),
    }


def _percentiles(values: Sequence[float]) -> dict[str, float]:
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95))} if values else {"p50": 0.0, "p95": 0.0}


def _encode(snapshot, text):
    import torch
    if snapshot["device"] == "cuda":
        torch.cuda.synchronize()
    started = time.perf_counter()
    tokens = snapshot["tokenizer"](text, padding="max_length", truncation=True, max_length=77, return_tensors="pt")
    with torch.inference_mode():
        features = snapshot["model"].extract_text_features(
            tokens["input_ids"].to(snapshot["device"]), tokens["attention_mask"].to(snapshot["device"])
        )
    if snapshot["device"] == "cuda":
        torch.cuda.synchronize()
    return features.detach().cpu().numpy().reshape(512), (time.perf_counter() - started) * 1000


def _legacy_ranking(snapshot, engine, features):
    """Original top-50 images -> cosine rerank -> top-10 images -> dedup."""
    query = np.asarray(features, dtype=np.float32)
    query = query / np.linalg.norm(query)
    dim = 64 if 64 in snapshot["image_indexes"] else 512
    first_query = query[:dim].copy()
    first_query /= np.linalg.norm(first_query)
    limit = 50 if dim == 64 else 10
    _, positions = snapshot["image_indexes"][dim].search(first_query[None, :], limit)
    positions = [int(index) for index in positions[0] if index >= 0]
    if dim == 64:
        scores = engine._vectors[512][positions] @ query
        positions = [positions[i] for i in np.argsort(-scores, kind="stable")[:10]]
    return list(dict.fromkeys(str(snapshot["product_ids"][index]) for index in positions[:10]))


def _mean_metrics(records, method):
    records = [row for row in records if row.get("metrics") is not None]
    if not records:
        return None
    keys = ("ndcg_at_10", "precision_at_10", "unique_products_at_10")
    result = {key: float(np.mean([row["metrics"][method][key] for row in records])) for key in keys}
    accuracies = [row["metrics"][method]["brand_accuracy_at_10"] for row in records if row["metrics"][method].get("brand_accuracy_at_10") is not None]
    result["brand_accuracy_at_10"] = float(np.mean(accuracies)) if accuracies else None
    result["queries"] = len(records)
    return result


def evaluate_gate(report: Mapping[str, Any], qrels: Mapping[str, Any] | None, pool: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reasons = []
    independent = bool(qrels and qrels.get("independently_judged") is True and _judgment_source(qrels) in INDEPENDENT_SOURCES)
    if not independent:
        reasons.append("Independent relevance qrels are required; metadata proxies cannot pass the gate")
    if independent and (not report.get("index_version") or qrels.get("index_version") != report["index_version"]):
        reasons.append("Independent qrels must identify the evaluated index version")
    for field in ("queries_sha256", "search_documents_sha256"):
        if independent and report.get(field) and qrels.get(field) != report[field]:
            reasons.append(f"Independent qrels provenance differs: {field}")
    judgments = qrels.get("judgments", {}) if qrels else {}
    required_queries = [row for row in report["queries"] if row["split"] in ("test", "control")]
    if sum(row["split"] == "test" for row in required_queries) != 40 or sum(row["group"] == "full_caption" for row in required_queries) != 10:
        reasons.append("The complete 40-query held-out set and ten full-caption controls are required")
    required_ids = {row["id"] for row in required_queries}
    missing = [(row["query_id"], row["product_id"]) for row in pool if row["query_id"] in required_ids and row["product_id"] not in judgments.get(row["query_id"], {})]
    if missing or any(query_id not in judgments for query_id in required_ids):
        reasons.append(f"Held-out/control pooled candidates are not fully judged ({len(missing)} missing product grades)")
    summary = report["summary"]
    baseline = summary["product_dense"]["test"]
    hybrid = summary["hybrid"]["test"]
    uplift = None
    if not baseline or not hybrid or baseline["ndcg_at_10"] <= 0:
        reasons.append("A nonzero product-dense held-out baseline is required")
    else:
        uplift = hybrid["ndcg_at_10"] / baseline["ndcg_at_10"] - 1
        if uplift < 0.10:
            reasons.append("Held-out hybrid nDCG@10 uplift is below 10% versus product-dense")
    for group in SHORT_GROUPS:
        before = summary["product_dense"]["groups"].get(group)
        after = summary["hybrid"]["groups"].get(group)
        if not before or not after:
            reasons.append(f"Missing held-out metrics for {group}")
        elif after["ndcg_at_10"] + 1e-12 < 0.95 * before["ndcg_at_10"]:
            reasons.append(f"Held-out {group} nDCG@10 regressed more than 5%")
    for method in ("legacy_dense", "product_dense", "hybrid"):
        if not summary[method]["controls"]:
            reasons.append(f"Missing full-caption control metrics for {method}")
    before = summary["product_dense"]["controls"]
    after = summary["hybrid"]["controls"]
    if before and after and after["ndcg_at_10"] + 1e-12 < 0.98 * before["ndcg_at_10"]:
        reasons.append("Full-caption control nDCG@10 regressed more than 2%")
    if report["lexical_and_fusion_ms"]["p95"] > 50:
        reasons.append("Lexical plus fusion p95 exceeds 50 ms")
    if not report.get("lexical_available"):
        reasons.append("The loaded index does not include validated lexical documents")
    return {"passed": not reasons, "reasons": reasons, "heldout_ndcg_relative_uplift": uplift,
            "independently_judged": independent, "pooled_judgments_missing": len(missing)}


def run_benchmark(snapshot, queries, *, qrels=None, repeats=3, warmup=1, encoder=None):
    if repeats < 1 or warmup < 0:
        raise ValueError("Repeats must be positive and warmup nonnegative")
    engine = snapshot.get("product_retriever")
    if engine is None:
        raise RuntimeError("The loaded snapshot has no product retriever")
    encoder = encoder or (lambda query: _encode(snapshot, query))
    documents = engine.documents
    by_product = {str(document["product_id"]): document for document in documents}
    latencies = {method: [] for method in METHODS}
    encode_times, overhead_times = [], []
    records, pool = [], []
    if queries:
        for _ in range(warmup):
            features, _ = encoder(queries[0]["query"])
            engine.search(queries[0]["query"], features)
            engine.search(queries[0]["query"], features, retrieval_mode="dense")
            _legacy_ranking(snapshot, engine, features)
    for query in queries:
        rankings = None
        for repeat in range(repeats):
            features, encode_ms = encoder(query["query"])
            encode_times.append(float(encode_ms))
            started = time.perf_counter()
            legacy = _legacy_ranking(snapshot, engine, features)
            latencies["legacy_dense"].append((time.perf_counter() - started) * 1000)
            outcomes = {}
            for mode in (("hybrid", "dense") if repeat % 2 else ("dense", "hybrid")):
                started = time.perf_counter()
                outcomes[mode] = engine.search(query["query"], features, retrieval_mode=mode)
                latencies["product_dense" if mode == "dense" else "hybrid"].append((time.perf_counter() - started) * 1000)
            hybrid = outcomes["hybrid"]
            overhead_times.append(hybrid["timing"]["lexical_ms"] + hybrid["timing"]["fusion_ms"])
            latencies["bm25"].append(hybrid["timing"]["lexical_ms"])
            lexical = sorted((item for item in hybrid["data"] if item.get("lexical_rank") is not None), key=lambda item: item["lexical_rank"])
            rankings = {
                "legacy_dense": legacy,
                "product_dense": [item["catalog_product_id"] for item in outcomes["dense"]["data"]],
                "bm25": [item["catalog_product_id"] for item in lexical],
                "hybrid": [item["catalog_product_id"] for item in hybrid["data"]],
            }
        judged = qrels is None or query["id"] in qrels["judgments"]
        grades = qrels["judgments"].get(query["id"], {}) if qrels is not None else proxy_grades(query, documents)
        metrics = {method: ranking_metrics(rankings[method], grades) for method in METHODS} if judged else None
        brand = normalize_text(query.get("proxy", {}).get("brand_prefix", ""))
        for method in METHODS:
            hits = rankings[method][:10]
            if metrics is not None:
                metrics[method]["brand_accuracy_at_10"] = (
                sum(normalize_text(by_product[pid].get("brand", "")) == brand or normalize_text(by_product[pid].get("brand", "")).startswith(brand + " ") for pid in hits) / 10
                ) if brand else None
        records.append({"id": query["id"], "query": query["query"], "group": query["group"], "split": query["split"],
                        "judgment_source": "metadata_proxy" if qrels is None else _judgment_source(qrels) if judged else "unjudged",
                        "metrics": metrics, "top_10": {method: ranking[:10] for method, ranking in rankings.items()}})
        pooled = {}
        for method, ranking in rankings.items():
            for rank, pid in enumerate(ranking[:20], 1):
                pooled.setdefault(pid, {})[method] = rank
        for pid, methods in sorted(pooled.items()):
            document = by_product[pid]
            vector_id = document["vector_ids"][0]
            pool.append({"query_id": query["id"], "query": query["query"], "group": query["group"], "split": query["split"],
                         "product_id": pid, "name": document.get("name", ""), "brand": document.get("brand", ""),
                         "category": document.get("category", ""), "description": document.get("description", ""),
                         "image_path": snapshot.get("image_paths", [])[vector_id] if snapshot.get("image_paths") else None,
                         "methods": methods, "relevance": None})
    summary = {}
    for method in METHODS:
        summary[method] = {
            "test": _mean_metrics([row for row in records if row["split"] == "test"], method),
            "dev": _mean_metrics([row for row in records if row["split"] == "dev"], method),
            "controls": _mean_metrics([row for row in records if row["group"] == "full_caption"], method),
            "groups": {group: _mean_metrics([row for row in records if row["split"] == "test" and row["group"] == group], method) for group in SHORT_GROUPS},
            "retrieval_ms": _percentiles(latencies[method]),
        }
    source = "metadata_proxy" if qrels is None else _judgment_source(qrels) if qrels.get("independently_judged") is True and _judgment_source(qrels) in INDEPENDENT_SOURCES else "supplied_unverified"
    report = {"schema_version": 1, "index_version": snapshot.get("active_version"),
              "search_documents_sha256": snapshot.get("meta", {}).get("search_documents_sha256"),
              "queries_sha256": hashlib.sha256(json.dumps(
                  [{key: query[key] for key in ("id", "query", "group", "split")} for query in queries],
                  sort_keys=True, ensure_ascii=False, separators=(",", ":")
              ).encode("utf-8")).hexdigest(),
              "judgment_source": source, "lexical_available": engine.lexical_available,
              "judgment_modality": qrels.get("judgment_modality", "unspecified") if qrels else "catalog_metadata_proxy",
              "candidate_pool_per_branch": engine.candidate_pool_size, "legacy_image_pool": 50,
              "latency_scope": "Retrieval-only; encoding measured once per query/repeat and shared across all ablations. BM25 latency is its measured shared lexical branch.",
              "shared_encode_ms": _percentiles(encode_times), "lexical_and_fusion_ms": _percentiles(overhead_times),
              "repeats": repeats, "query_counts": dict(Counter(row["group"] for row in records)),
              "pool_depth_per_method": 20, "pool_size": len(pool), "summary": summary, "queries": records}
    report["gate"] = evaluate_gate(report, qrels, pool)
    return report, pool


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--qrels", type=Path, help="Independent 0..3 relevance judgments in the documented JSON envelope")
    parser.add_argument("--export-pool", type=Path, help="Export pooled top-20 candidates per method for independent judgment (.json or .jsonl)")
    parser.add_argument("--output", type=Path, help="Write the metrics JSON here instead of stdout")
    parser.add_argument("--gate", action="store_true", help="Exit nonzero unless all independently judged acceptance checks pass")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="Diagnostic subset; cannot satisfy the complete release gate")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch
    from ai_worker.api import server
    torch.set_num_threads(args.threads)
    with redirect_stdout(sys.stderr):
        server.setup_inference_engine()
    snapshot = server.state
    if not server.inference_ready():
        parser.error("The matching model/index snapshot is not ready")
    engine = snapshot.get("product_retriever")
    if engine is None:
        parser.error("The snapshot does not expose a product retriever")
    queries = load_queries(args.queries, engine.documents)
    if args.limit:
        queries = queries[:args.limit]
    report, pool = run_benchmark(snapshot, queries, qrels=load_qrels(args.qrels), repeats=args.repeats, warmup=args.warmup)
    if args.export_pool:
        args.export_pool.parent.mkdir(parents=True, exist_ok=True)
        if args.export_pool.suffix.lower() == ".jsonl":
            content = "\n".join(json.dumps(row, ensure_ascii=False) for row in pool) + "\n"
        else:
            content = json.dumps({"index_version": report["index_version"], "candidates": pool}, ensure_ascii=False, indent=2)
        args.export_pool.write_text(content, encoding="utf-8")
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    if args.gate and not report["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
