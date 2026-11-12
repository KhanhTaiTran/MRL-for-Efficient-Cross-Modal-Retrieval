"""Versioned, product-level lexical and visual retrieval.

This module owns no live catalog connection or global index. Build one retriever
from an immutable search-document/vector snapshot, then publish it with FAISS.
Scores from the two branches are combined by rank, never by their raw scale.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import re
import threading
import time
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import snowballstemmer


NORMALIZATION_VERSION = "english-snowball-v1"
BRAND_ALIASES_VERSION = 1
MAX_BRAND_INTENT_WORDS = 8
DEFAULT_BRAND_ALIASES = {"adidas": ["adidas"], "diesel": ["diesel"]}
FIELD_WEIGHTS = {
    "brand": 3.0,
    "name": 3.0,
    "category": 2.0,
    "subcategory": 2.0,
    "tags": 2.0,
    "description": 1.0,
}
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STEMMERS = threading.local()
_STOP_WORDS = frozenset(
    "a an and are as at be by for from in is it of on or that the this to with".split()
)


def normalize_text(value: Any) -> str:
    """Normalize punctuation/spacing without changing brand identity."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(_WORDS.findall(text))


@lru_cache(maxsize=32768)
def _stem_word(word: str) -> str:
    # Snowball's generated stemmer has mutable state, so each inference thread
    # gets its own instance. Cached immutable results can safely be shared.
    if not hasattr(_STEMMERS, "english"):
        _STEMMERS.english = snowballstemmer.stemmer("english")
    return _STEMMERS.english.stemWord(word)


def tokenize_text(value: Any, *, stem: bool = True) -> tuple[str, ...]:
    words = [word for word in normalize_text(value).split() if word not in _STOP_WORDS]
    return tuple(_stem_word(word) for word in words) if stem else tuple(words)


def _array(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32)


def _normalized(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=-1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms <= 0):
        raise ValueError("Embedding vectors must be finite and nonzero")
    return np.ascontiguousarray(values / norms, dtype=np.float32)


class _BM25Field:
    """Sparse BM25 postings with Lucene's nonnegative IDF formula."""

    def __init__(self, documents: Sequence[tuple[str, ...]], k1: float, b: float):
        self.size, self.k1 = len(documents), k1
        lengths = np.asarray([len(tokens) for tokens in documents], dtype=np.float64)
        nonempty = lengths[lengths > 0]
        count = len(nonempty)
        average = float(nonempty.mean()) if count else 1.0
        self.norm = k1 * (1.0 - b + b * lengths / average)
        posting_ids: dict[str, list[int]] = defaultdict(list)
        posting_tf: dict[str, list[int]] = defaultdict(list)
        for index, tokens in enumerate(documents):
            for token, frequency in Counter(tokens).items():
                posting_ids[token].append(index)
                posting_tf[token].append(frequency)
        self.postings = {}
        for token, ids in posting_ids.items():
            positions = np.asarray(ids, dtype=np.intp)
            tf = np.asarray(posting_tf[token], dtype=np.float64)
            idf = float(np.log1p((count - len(ids) + 0.5) / (len(ids) + 0.5)))
            scores = idf * tf * (k1 + 1.0) / (tf + self.norm[positions])
            self.postings[token] = (positions, scores)

    def score(self, query: Iterable[str]) -> np.ndarray:
        scores = np.zeros(self.size, dtype=np.float64)
        for token in sorted(set(query)):
            posting = self.postings.get(token)
            if posting is not None:
                ids, values = posting
                scores[ids] += values
        return scores


class HybridRetriever:
    """Combine visual cosine and field-weighted BM25 at product granularity.

    ``documents`` has exactly one record per product and collectively maps every
    vector once through ``vector_ids``. All filtering happens before either
    branch's top-product cutoff. Results include every ranked image of a product
    so the gateway can discard an archived image without discarding its product.
    """

    def __init__(
        self,
        documents: Sequence[Mapping[str, Any]],
        full_vectors: Any,
        supported_dims: Sequence[int] | None = None,
        *,
        lexical_available: bool = True,
        brand_aliases: Mapping[str, Sequence[str]] | None = None,
        candidate_pool_size: int = 200,
        rrf_k: int = 60,
    ):
        vectors = _array(full_vectors)
        if vectors.ndim != 2 or vectors.shape[1] != 512:
            raise ValueError("Hybrid retrieval requires an N x 512 vector matrix")
        if candidate_pool_size < 1 or rrf_k < 1:
            raise ValueError("Candidate pool size and RRF constant must be positive")
        dims = tuple(sorted(set(supported_dims or (16, 32, 64, 128, 256, 512))))
        if any(type(dim) is not int or not 1 <= dim <= 512 for dim in dims) or 512 not in dims:
            raise ValueError("Supported dimensions must include 512 and be in 1..512")
        self.supported_dims = dims
        self.candidate_pool_size = int(candidate_pool_size)
        self.rrf_k = int(rrf_k)
        self.lexical_available = bool(lexical_available)
        self.documents: tuple[dict[str, Any], ...] = tuple(dict(doc) for doc in documents)
        self.product_ids = tuple(str(doc["product_id"]) for doc in self.documents)
        if any(not pid for pid in self.product_ids) or len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("Search documents need distinct nonempty product IDs")
        self._product_positions = {pid: i for i, pid in enumerate(self.product_ids)}
        self._vector_ids = []
        vector_products = np.full(len(vectors), -1, dtype=np.intp)
        for index, doc in enumerate(self.documents):
            ids = doc.get("vector_ids", ())
            if not ids:
                raise ValueError("Each search document needs at least one vector")
            if any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) for value in ids):
                raise ValueError("Vector IDs must be integers")
            ids = np.asarray(ids, dtype=np.intp)
            if np.any(ids < 0) or np.any(ids >= len(vectors)) or len(set(ids.tolist())) != len(ids):
                raise ValueError("Search document has invalid vector IDs")
            if np.any(vector_products[ids] != -1):
                raise ValueError("A vector cannot belong to multiple products")
            vector_products[ids] = index
            ids.setflags(write=False)
            self._vector_ids.append(ids)
        if np.any(vector_products == -1):
            raise ValueError("Search documents must map every vector exactly once")
        self._vector_products = vector_products
        self._vectors = {}
        for dim in dims:
            matrix = _normalized(vectors[:, :dim]) if len(vectors) else vectors[:, :dim].copy()
            matrix.setflags(write=False)
            self._vectors[dim] = matrix
        self._brands = tuple(normalize_text(doc.get("brand", "")) for doc in self.documents)
        self._brand_patterns = self._build_brand_patterns(
            DEFAULT_BRAND_ALIASES if brand_aliases is None else brand_aliases
        )
        self._fields = {}
        if self.lexical_available:
            for field, weight in FIELD_WEIGHTS.items():
                tokens = []
                for doc in self.documents:
                    value = doc.get(field, "")
                    if isinstance(value, (list, tuple)):
                        value = " ".join(str(item) for item in value)
                    tokens.append(tokenize_text(value, stem=field != "brand"))
                self._fields[field] = (_BM25Field(tokens, 1.2, 0.75), weight)

    def _build_brand_patterns(self, aliases):
        patterns: dict[tuple[str, ...], frozenset[int]] = {}
        for brand in sorted(set(self._brands) - {""}):
            patterns[tuple(brand.split())] = frozenset(
                i for i, value in enumerate(self._brands) if value == brand
            )
        for alias, prefixes in aliases.items():
            phrase = tuple(normalize_text(alias).split())
            if not phrase:
                continue
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            normalized = [normalize_text(prefix) for prefix in prefixes]
            matches = frozenset(
                i for i, brand in enumerate(self._brands)
                if any(prefix and (brand == prefix or brand.startswith(prefix + " ")) for prefix in normalized)
            )
            if matches:
                patterns[phrase] = patterns.get(phrase, frozenset()) | matches
        return tuple(sorted(patterns.items(), key=lambda item: (-len(item[0]), item[0])))

    def _recognize_brand(self, query: str):
        words = tuple(normalize_text(query).split())
        # A catalog caption often starts with a brand but describes a precise
        # visual item. Brand-first tiers are shopping-query intent, not a reason
        # to place unrelated same-brand items ahead of a matching description.
        if len(words) > MAX_BRAND_INTENT_WORDS:
            return frozenset(), query, None
        for phrase, products in self._brand_patterns:
            for position in range(len(words) - len(phrase) + 1):
                if words[position:position + len(phrase)] == phrase:
                    residual = words[:position] + words[position + len(phrase):]
                    return products, " ".join(residual), " ".join(phrase)
        return frozenset(), query, None

    def _lexical_scores(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.documents), dtype=np.float64)
        for field, (index, weight) in self._fields.items():
            scores += weight * index.score(tokenize_text(query, stem=field != "brand"))
        return scores

    def _max_product_scores(self, image_scores: np.ndarray) -> np.ndarray:
        scores = np.full(len(self.documents), -np.inf, dtype=np.float32)
        np.maximum.at(scores, self._vector_products, image_scores)
        return scores

    def _dense_branch(self, query: np.ndarray, target_dim: int, search_mode: str, eligible: np.ndarray):
        started = time.perf_counter()
        adaptive = search_mode == "adaptive" and 64 in self._vectors
        stage1_dim = 64 if adaptive else target_dim
        q = _normalized(query[:stage1_dim])
        image_scores = self._vectors[stage1_dim] @ q
        product_scores = self._max_product_scores(image_scores)
        selected = sorted(
            np.flatnonzero(eligible).tolist(),
            key=lambda i: (-float(product_scores[i]), self.product_ids[i]),
        )[:self.candidate_pool_size]
        stage1_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        score_dim = 512 if adaptive else target_dim
        if adaptive:
            q = _normalized(query)
            for index in selected:
                ids = self._vector_ids[index]
                product_scores[index] = np.max(self._vectors[512][ids] @ q)
        selected.sort(key=lambda i: (-float(product_scores[i]), self.product_ids[i]))
        rerank_ms = (time.perf_counter() - started) * 1000.0 if adaptive else 0.0
        return selected, score_dim, stage1_dim, stage1_ms, rerank_ms

    def search(
        self,
        query: str,
        features512: Any,
        target_dim: int = 512,
        search_mode: str = "adaptive",
        retrieval_mode: str = "hybrid",
        eligible_product_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if target_dim not in self.supported_dims:
            raise ValueError("Unsupported target dimension")
        if search_mode not in ("direct", "adaptive"):
            raise ValueError("search_mode must be direct or adaptive")
        if retrieval_mode not in ("dense", "hybrid"):
            raise ValueError("retrieval_mode must be dense or hybrid")
        if not str(query).strip():
            raise ValueError("Query text cannot be empty")
        features = _array(features512)
        if features.shape == (1, 512):
            features = features[0]
        if features.shape != (512,):
            raise ValueError("Query embedding must have 512 dimensions")
        features = _normalized(features)
        eligible = np.ones(len(self.documents), dtype=bool)
        if eligible_product_ids is not None:
            allowed = {str(value) for value in eligible_product_ids}
            eligible = np.asarray([pid in allowed for pid in self.product_ids], dtype=bool)
        effective = retrieval_mode
        fallback_reason = None
        if retrieval_mode == "hybrid" and not self.lexical_available:
            effective, fallback_reason = "dense", "lexical_index_unavailable"
        dense, score_dim, stage1_dim, stage1_ms, rerank_ms = self._dense_branch(
            features, target_dim, search_mode, eligible
        )
        branch_started = time.perf_counter()
        brand_products, residual_query, matched_brand = self._recognize_brand(query)
        lexical = []
        lexical_count = 0
        if effective == "hybrid":
            lexical_scores = self._lexical_scores(query)
            residual_scores = self._lexical_scores(residual_query) if matched_brand else lexical_scores
            matches = np.flatnonzero(eligible & (lexical_scores > 0)).tolist()
            lexical_count = len(matches)
            lexical = sorted(
                matches,
                key=lambda i: (
                    -(i in brand_products), -float(residual_scores[i]),
                    -float(lexical_scores[i]), self.product_ids[i],
                ),
            )[:self.candidate_pool_size]
        lexical_ms = (time.perf_counter() - branch_started) * 1000.0
        branch_started = time.perf_counter()
        rank_scores: dict[int, float] = {}
        dense_ranks = {index: rank for rank, index in enumerate(dense, 1)}
        lexical_ranks = {index: rank for rank, index in enumerate(lexical, 1)}
        for ranking in (dense, lexical):
            for rank, index in enumerate(ranking, 1):
                rank_scores[index] = rank_scores.get(index, 0.0) + 1.0 / (self.rrf_k + rank)
        # Dense-only baselines remain actual cosine order; metadata tiering is
        # a hybrid behavior and must not alter reproducible dense experiments.
        ordered = sorted(
            rank_scores,
            key=lambda i: (
                -(effective == "hybrid" and i in brand_products),
                -rank_scores[i], self.product_ids[i],
            ),
        )
        image_query = _normalized(features[:score_dim])
        data = []
        for index in ordered:
            ids = self._vector_ids[index]
            scores = np.clip(self._vectors[score_dim][ids] @ image_query, -1.0, 1.0)
            candidates = sorted(
                ({"vector_id": int(vector_id), "similarity_score": float(score)} for vector_id, score in zip(ids, scores)),
                key=lambda item: (-item["similarity_score"], item["vector_id"]),
            )
            data.append({
                "catalog_product_id": self.product_ids[index],
                "vector_id": candidates[0]["vector_id"],
                "similarity_score": candidates[0]["similarity_score"],
                "rank_score": rank_scores[index],
                "dense_rank": dense_ranks.get(index),
                "lexical_rank": lexical_ranks.get(index),
                "image_candidates": candidates,
            })
        fusion_ms = (time.perf_counter() - branch_started) * 1000.0
        return {
            "data": data,
            "effective_retrieval_mode": effective,
            "fallback_reason": fallback_reason,
            "truncated": int(eligible.sum()) > len(dense) or lexical_count > len(lexical),
            "matched_brand": matched_brand if effective == "hybrid" else None,
            "stage1_dim": stage1_dim,
            "stage2_dim": 512 if stage1_dim == 64 and search_mode == "adaptive" else None,
            "timing": {
                "stage1_ms": round(stage1_ms, 2),
                "rerank_ms": round(rerank_ms, 2),
                "lexical_ms": round(lexical_ms, 2),
                "fusion_ms": round(fusion_ms, 2),
                "retrieval_total_ms": round((time.perf_counter() - started) * 1000.0, 2),
            },
        }
