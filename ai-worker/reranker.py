"""
Two-Stage Reranker for MRL Cross-Modal Retrieval.

Strategy:
    Stage 1: 64-dim FAISS retrieval -> top-K candidates  (fast, ~3ms)
    Stage 2a: 512-dim cosine rerank                       (precise, ~1ms extra)
    Stage 2b: Cross-encoder rerank                        (best quality, ~20-50ms extra)

Usage:
    reranker = TwoStageReranker(mode='cosine')  # or 'cross_encoder'
    results = reranker.rerank(query_vec_512, db_vecs_512, candidate_indices, top_k=10)
"""

import torch
import torch.nn.functional as F
import numpy as np
from typing import List, Tuple, Literal

# =====================================================================
# Cross-encoder model name. Change if you want a different model.
# Options:
#   - "cross-encoder/ms-marco-MiniLM-L-6-v2"   (fast, general)
#   - "cross-encoder/ms-marco-MiniLM-L-12-v2"  (slower, better)
#   - "cross-encoder/stsb-roberta-base"         (semantic similarity)
# =====================================================================
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class TwoStageReranker:
    """
    Two-stage reranker that improves Recall@1 without retraining.

    Stage 1 (fast): Use low-dim (e.g. 64) cosine similarity to get top-K candidates.
    Stage 2 (precise): Rerank candidates using either:
        - 'cosine': Full 512-dim cosine similarity
        - 'cross_encoder': Cross-encoder model for text-image caption matching
    """

    def __init__(self, mode: Literal['cosine', 'cross_encoder'] = 'cosine'):
        """
        Args:
            mode: Reranking strategy.
                  'cosine'         - Rerank using full 512-dim cosine similarity. No extra model needed.
                  'cross_encoder'  - Rerank using a cross-encoder. Requires sentence-transformers.
        """
        self.mode = mode
        self._cross_encoder = None  # Lazy load to avoid import cost when not used

        if mode == 'cross_encoder':
            self._load_cross_encoder()

    def _load_cross_encoder(self):
        """Lazily load the cross-encoder model."""
        try:
            from sentence_transformers.cross_encoder import CrossEncoder  # type: ignore
            print(f"[Reranker] Loading cross-encoder: {CROSS_ENCODER_MODEL}")
            self._cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
            print("[Reranker] Cross-encoder loaded successfully.")
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for cross-encoder reranking.\n"
                "Install it with: pip install sentence-transformers"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank_with_cosine(
        self,
        query_vec_512: torch.Tensor,
        db_vecs_512: torch.Tensor,
        candidate_indices: List[int],
        top_k: int = 10,
    ) -> List[Tuple[int, float]]:
        """
        Rerank candidates using full 512-dim cosine similarity.

        Args:
            query_vec_512:      Query vector of shape [1, 512] or [512].
            db_vecs_512:        Database vectors of shape [N, 512] (full DB, not normalized).
            candidate_indices:  List of candidate indices from Stage 1 (top-K from 64-dim search).
            top_k:              Number of final results to return.

        Returns:
            List of (original_db_index, cosine_score) sorted by score descending.
        """
        if query_vec_512.dim() == 1:
            query_vec_512 = query_vec_512.unsqueeze(0)  # [1, 512]

        # Extract candidate vectors from DB
        candidate_vecs = db_vecs_512[candidate_indices]  # [K, 512]

        # L2 normalize both for cosine similarity
        q_norm = F.normalize(query_vec_512, dim=-1)            # [1, 512]
        c_norm = F.normalize(candidate_vecs.float(), dim=-1)   # [K, 512]

        # Cosine scores: [1, K]
        scores = (q_norm @ c_norm.T).squeeze(0)  # [K]

        # Sort descending
        sorted_order = scores.argsort(descending=True)[:top_k]

        results = [
            (candidate_indices[i.item()], scores[i].item()) # type: ignore
            for i in sorted_order
        ]
        return results

    def rerank_with_cross_encoder(
        self,
        query_text: str,
        candidate_captions: List[str],
        candidate_indices: List[int],
        top_k: int = 10,
    ) -> List[Tuple[int, float]]:
        """
        Rerank candidates using a cross-encoder model (text-to-caption matching).

        Args:
            query_text:         The original text query string.
            candidate_captions: List of captions/descriptions for candidate images.
            candidate_indices:  List of candidate indices from Stage 1.
            top_k:              Number of final results to return.

        Returns:
            List of (original_db_index, cross_encoder_score) sorted by score descending.
        """
        if self._cross_encoder is None:
            self._load_cross_encoder()

        # Build (query, candidate_caption) pairs for cross-encoder
        pairs = [(query_text, cap) for cap in candidate_captions]

        # Predict relevance scores
        scores = self._cross_encoder.predict(pairs)  # type: ignore # numpy array [K]

        # Sort descending
        sorted_order = np.argsort(scores)[::-1][:top_k]

        results = [
            (candidate_indices[i], float(scores[i]))
            for i in sorted_order
        ]
        return results

    def rerank(
        self,
        query_vec_512: torch.Tensor,
        db_vecs_512: torch.Tensor,
        candidate_indices: List[int],
        top_k: int = 10,
        # Extra kwargs for cross_encoder mode
        query_text: str = "",
        candidate_captions: List[str] | None = None,
    ) -> List[Tuple[int, float]]:
        """
        Unified rerank call. Dispatches to cosine or cross_encoder based on self.mode.

        For 'cross_encoder' mode, query_text and candidate_captions must be provided.
        """
        if self.mode == 'cosine':
            return self.rerank_with_cosine(
                query_vec_512, db_vecs_512, candidate_indices, top_k
            )
        elif self.mode == 'cross_encoder':
            if not query_text or candidate_captions is None:
                raise ValueError(
                    "cross_encoder mode requires 'query_text' and 'candidate_captions'."
                )
            return self.rerank_with_cross_encoder(
                query_text, candidate_captions, candidate_indices, top_k
            )
        else:
            raise ValueError(f"Unknown reranker mode: {self.mode}. Use 'cosine' or 'cross_encoder'.")


# ======================================================================
# Quick smoke test
# ======================================================================
if __name__ == "__main__":
    print("=== TwoStageReranker Smoke Test ===")
    torch.manual_seed(42)

    N_DB = 100
    DIM = 512

    db_vecs = torch.randn(N_DB, DIM)
    query_vec = torch.randn(1, DIM)
    candidates = list(range(50))  # Simulate 50 candidates from Stage 1

    # Test cosine mode
    reranker = TwoStageReranker(mode='cosine')
    results = reranker.rerank(query_vec, db_vecs, candidates, top_k=10)
    print(f"Cosine reranking top-10: {results[:3]}...")  # Show first 3

    print("\nSmoke test passed.")
