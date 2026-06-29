"""
Alpha Query Expansion (AQE) for MRL Cross-Modal Retrieval.

Idea:
    A text query embedding is often imprecise compared to image embeddings
    in the shared space. AQE refines the query by interpolating it with
    the mean embedding of the top-k retrieved results.

    Refined query:  q* = normalize(alpha * q0 + (1 - alpha) * mean(top_k_db_vecs))

    Intuition:
        - q0 preserves the original query intent
        - mean(top_k) "pulls" the query toward the visual cluster it belongs to
        - alpha controls how aggressively we expand (0.7 = 70% original)

AQE is especially effective for:
    - Short/ambiguous queries ("red dress", "blue sneakers")
    - Fashion domain where visual clusters are tight

Usage:
    expander = AlphaQueryExpander(alpha=0.7)
    refined_q = expander.expand(query_vec_512, db_vecs_512, top_k=5)
    # Then use refined_q for final retrieval
"""

import torch
import torch.nn.functional as F
from typing import List, Tuple


class AlphaQueryExpander:
    """
    Alpha Query Expansion (AQE).

    Refines a query vector by blending it with the mean embedding of
    the top-k retrieved database vectors (pseudo-relevance feedback).

    Args:
        alpha: Weight for the original query (0 < alpha < 1).
               Higher alpha = closer to original query intent.
               Typical range: 0.6 – 0.9. Default: 0.7.
        top_k: Number of top-retrieved items to use for expansion. Default: 5.
    """

    def __init__(self, alpha: float = 0.7, top_k: int = 5):
        if not (0 < alpha < 1):
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self.top_k = top_k

    def expand(
        self,
        query_vec: torch.Tensor,
        db_vecs: torch.Tensor,
        candidate_indices: List[int] | None = None,
    ) -> torch.Tensor:
        """
        Expand and refine the query vector.

        Args:
            query_vec:         Query vector of shape [1, D] or [D].
            db_vecs:           Database vectors of shape [N, D].
            candidate_indices: Optional. If provided, use ONLY these indices
                               as the pool to pick top-k from (Stage-1 output).
                               If None, search the full DB.

        Returns:
            Refined query vector of shape [1, D], L2-normalized.
        """
        if query_vec.dim() == 1:
            query_vec = query_vec.unsqueeze(0)  # [1, D]

        device = query_vec.device
        db_vecs = db_vecs.to(device)

        # --- Normalize for cosine similarity ---
        q_norm = F.normalize(query_vec.float(), dim=-1)     # [1, D]

        if candidate_indices is not None:
            pool_vecs = db_vecs[candidate_indices]           # [K, D]
        else:
            pool_vecs = db_vecs                              # [N, D]

        pool_norm = F.normalize(pool_vecs.float(), dim=-1)  # [pool_size, D]

        # --- Find top-k most similar to query within pool ---
        scores = (q_norm @ pool_norm.T).squeeze(0)          # [pool_size]
        k = min(self.top_k, len(scores))
        top_k_local_indices = scores.topk(k).indices        # indices within pool

        # Map back to actual pool vectors
        top_k_vecs = pool_norm[top_k_local_indices]         # [k, D]

        # --- Blend: alpha * q + (1-alpha) * mean(top_k) ---
        mean_top_k = top_k_vecs.mean(dim=0, keepdim=True)   # [1, D]
        refined = self.alpha * q_norm + (1 - self.alpha) * mean_top_k
        refined = F.normalize(refined, dim=-1)               # [1, D]

        return refined

    def expand_batch(
        self,
        query_vecs: torch.Tensor,
        db_vecs: torch.Tensor,
    ) -> torch.Tensor:
        """
        Expand a batch of query vectors.

        Args:
            query_vecs: [B, D]
            db_vecs:    [N, D]

        Returns:
            Refined query vectors [B, D].
        """
        refined_list = []
        for i in range(query_vecs.shape[0]):
            refined = self.expand(query_vecs[i], db_vecs)
            refined_list.append(refined)
        return torch.cat(refined_list, dim=0)  # [B, D]


def benchmark_aqe(
    image_features: torch.Tensor,
    text_features: torch.Tensor,
    alpha_values: List[float] | None = None,
    top_k_values: List[int] | None = None,
) -> None:
    """
    Benchmark AQE across different alpha and top_k values.
    Prints a comparison table.

    Args:
        image_features: [N, 512] image embeddings from test set.
        text_features:  [N, 512] text  embeddings from test set.
        alpha_values:   List of alpha values to test.
        top_k_values:   List of top_k values to test.
    """
    import time
    from benchmark import compute_recall_at_k #type: ignore

    if alpha_values is None:
        alpha_values = [0.5, 0.6, 0.7, 0.8, 0.9]
    if top_k_values is None:
        top_k_values = [3, 5, 10]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    img_vecs = image_features.to(device)
    txt_vecs = text_features.to(device)

    # Baseline (no AQE) using full 512-dim
    img_norm = F.normalize(img_vecs, dim=-1)
    txt_norm = F.normalize(txt_vecs, dim=-1)
    sim_baseline = txt_norm @ img_norm.T
    baseline_r1 = compute_recall_at_k(sim_baseline, k=1)
    baseline_r5 = compute_recall_at_k(sim_baseline, k=5)

    print("\n=== AQE BENCHMARK ===")
    print(f"Baseline (512-dim, no AQE): Recall@1={baseline_r1:.2f}%  Recall@5={baseline_r5:.2f}%")
    print()
    print(f"{'alpha':<8} {'top_k':<8} {'Recall@1 (%)':<15} {'Recall@5 (%)':<15} {'dR@1':<10} {'Latency (ms)'}")
    print("-" * 75)

    best_r1 = 0.0
    best_config = {}

    for alpha in alpha_values:
        for top_k in top_k_values:
            expander = AlphaQueryExpander(alpha=alpha, top_k=top_k)

            start = time.time()
            refined_txt = expander.expand_batch(txt_vecs, img_vecs)
            latency_ms = (time.time() - start) * 1000.0

            # Refined similarity matrix
            sim_aqe = refined_txt @ img_norm.T
            r1 = compute_recall_at_k(sim_aqe, k=1)
            r5 = compute_recall_at_k(sim_aqe, k=5)
            delta_r1 = r1 - baseline_r1

            marker = " ◄ BEST" if r1 > best_r1 else ""
            if r1 > best_r1:
                best_r1 = r1
                best_config = {"alpha": alpha, "top_k": top_k}

            print(
                f"{alpha:<8.1f} {top_k:<8} {r1:<15.2f} {r5:<15.2f} "
                f"{delta_r1:+.2f}%    {latency_ms:<.1f}ms{marker}"
            )

    print("-" * 75)
    print(f"\nBest config: alpha={best_config.get('alpha')}, top_k={best_config.get('top_k')}")
    print(f"Best Recall@1: {best_r1:.2f}% (d = {best_r1 - baseline_r1:+.2f}%)")


# ======================================================================
# Quick smoke test
# ======================================================================
if __name__ == "__main__":
    print("=== AlphaQueryExpander Smoke Test ===")
    torch.manual_seed(42)

    N, DIM = 200, 512
    db_vecs = torch.randn(N, DIM)
    query_vec = torch.randn(1, DIM)

    expander = AlphaQueryExpander(alpha=0.7, top_k=5)
    refined = expander.expand(query_vec, db_vecs)

    print(f"Original query norm: {query_vec.norm():.4f}")
    print(f"Refined  query norm: {refined.norm():.4f}")  # Should be ~1.0 after normalize
    assert refined.shape == (1, DIM), f"Expected shape (1, {DIM}), got {refined.shape}"
    print("Smoke test passed.")
