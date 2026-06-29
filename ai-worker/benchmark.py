"""
MRL Retrieval Benchmark — Extended Version
==========================================
Measures Recall@1 and Recall@5 across multiple retrieval strategies:

    [A] MRL Baseline:   Direct cosine search at various dimensions (16 → 512)
    [B] Two-Stage Reranking:
        B1 - 64-dim → rerank with 512-dim cosine
        B2 - 64-dim → rerank with cross-encoder (requires sentence-transformers)
    [C] Alpha Query Expansion (AQE):
        Tuned across alpha ∈ {0.5…0.9} and top_k ∈ {3, 5, 10}
    [D] Combined:
        AQE + 512-dim Cosine Reranking (stacked)

Run:
    python benchmark.py                  # Full benchmark (all strategies)
    python benchmark.py --mode baseline  # Only MRL baseline table
    python benchmark.py --mode rerank    # Only reranking comparison
    python benchmark.py --mode aqe       # Only AQE hyperparameter sweep
    python benchmark.py --mode combined  # AQE + reranking stacked
"""

import argparse
import os
import time
from typing import List

import torch
import torch.nn.functional as F


# ======================================================================
# Core metric
# ======================================================================

def compute_metrics(similarity_matrix: torch.Tensor, k: int = 5) -> dict:
    """
    Calculate Top-1, Top-K, Precision@K, and mAP@K.
    similarity_matrix: Tensor [N, N]. Rows = Query (Text), Cols = Database (Image).
    Ground-truth labels are on the main diagonal (i == j).
    """
    N = similarity_matrix.shape[0]
    _, topk_indices = similarity_matrix.topk(max(k, 1), dim=1)
    targets = torch.arange(N, device=similarity_matrix.device).view(-1, 1)
    results = (topk_indices == targets)
    
    top1 = (results[:, 0]).float().mean().item() * 100.0
    topk = (results[:, :k].sum(dim=1) > 0).float().mean().item() * 100.0
    p_at_k = (results[:, :k].sum(dim=1).float() / k).mean().item() * 100.0
    
    ap = torch.zeros(N, device=similarity_matrix.device)
    nonzero_idx = results[:, :k].nonzero(as_tuple=False)
    if nonzero_idx.numel() > 0:
        row_indices = nonzero_idx[:, 0]
        col_indices = nonzero_idx[:, 1]
        ap[row_indices] = 1.0 / (col_indices.float() + 1.0)
    map_at_k = ap.mean().item() * 100.0
    
    return {
        "top1": top1,
        f"top{k}": topk,
        f"p{k}": p_at_k,
        f"map{k}": map_at_k
    }


# ======================================================================
# Section A — MRL Baseline
# ======================================================================

def run_baseline_benchmark(image_features: torch.Tensor, text_features: torch.Tensor):
    """Original MRL benchmark: vary dimension from 16 to 512."""
    device = image_features.device
    N = image_features.shape[0]
    test_dims = [16, 32, 64, 128, 256, 512]

    print("\n" + "=" * 110)
    print("  [A] MRL BASELINE — Direct Cosine Search")
    print("=" * 110)
    print(f"{'Dimension':<14} | {'Storage (MB)':<12} | {'Latency (ms)':<12} | {'Top-1 (%)':<10} | {'Top-5 (%)':<10} | {'P@5 (%)':<8} | {'mAP@5 (%)'}")
    print("-" * 110)

    for dim in test_dims:
        img_d = F.normalize(image_features[:, :dim], dim=-1)
        txt_d = F.normalize(text_features[:, :dim], dim=-1)

        storage_mb = (N * dim * 4) / (1024 * 1024)

        start = time.time()
        sim = txt_d @ img_d.T
        latency_ms = (time.time() - start) * 1000.0

        metrics = compute_metrics(sim, k=5)
        r1, r5 = metrics["top1"], metrics["top5"]
        p5, map5 = metrics["p5"], metrics["map5"]
        label = f"{dim} (Base)" if dim == 512 else f"{dim} (MRL)"

        print(f"{label:<14} | {storage_mb:<12.2f} | {latency_ms:<12.2f} | {r1:<10.2f} | {r5:<10.2f} | {p5:<8.2f} | {map5:.2f}")

    print("-" * 110)


# ======================================================================
# Section B — Two-Stage Reranking
# ======================================================================

def run_reranking_benchmark(
    image_features: torch.Tensor,
    text_features: torch.Tensor,
    candidate_pool_size: int = 50,
    try_cross_encoder: bool = False,
    captions: List[str] | None = None,
):
    """
    Benchmark two-stage reranking.
    Stage 1: 64-dim fast search → top-K candidates
    Stage 2: Rerank candidates with 512-dim cosine (and optionally cross-encoder)
    """
    from reranker import TwoStageReranker

    device = image_features.device
    N = image_features.shape[0]

    print("\n" + "=" * 95)
    print(f"  [B] TWO-STAGE RERANKING  (Stage-1: 64-dim, candidate pool={candidate_pool_size})")
    print("=" * 95)

    # --- Baseline: full 512-dim direct ---
    img_512 = F.normalize(image_features, dim=-1)
    txt_512 = F.normalize(text_features, dim=-1)
    t0 = time.time()
    sim_baseline = txt_512 @ img_512.T
    baseline_latency = (time.time() - t0) * 1000.0
    baseline_metrics = compute_metrics(sim_baseline, k=5)
    baseline_r1, baseline_r5 = baseline_metrics["top1"], baseline_metrics["top5"]
    baseline_p5, baseline_map5 = baseline_metrics["p5"], baseline_metrics["map5"]

    print(f"\n  {'Strategy':<35} {'Top-1':<7} {'Top-5':<7} {'P@5':<7} {'mAP@5':<7} {'dTop-1':<8} {'Latency'}")
    print(f"  {'-'*95}")
    print(f"  {'Baseline: 512-dim direct':<35} {baseline_r1:<7.2f} {baseline_r5:<7.2f} {baseline_p5:<7.2f} {baseline_map5:<7.2f} {'—':<8} {baseline_latency:.1f}ms")

    # --- Stage 1: 64-dim ANN ---
    img_64 = F.normalize(image_features[:, :64], dim=-1)
    txt_64 = F.normalize(text_features[:, :64], dim=-1)

    # Precompute stage-1 candidates for all queries
    sim_64 = txt_64 @ img_64.T   # [N, N]
    _, stage1_indices = sim_64.topk(candidate_pool_size, dim=1)  # [N, pool]

    # Move full vectors to CPU for reranking loop (more memory-efficient)
    db_vecs_cpu = image_features.cpu()
    txt_vecs_cpu = text_features.cpu()

    # --- Stage 2a: 512-dim cosine reranking ---
    reranker_cos = TwoStageReranker(mode='cosine')
    correct_r1 = 0
    correct_r5 = 0
    sum_p5 = 0.0
    sum_map5 = 0.0
    t0 = time.time()

    for q_idx in range(N):
        query_vec = txt_vecs_cpu[q_idx]                       # [512]
        candidates = stage1_indices[q_idx].cpu().tolist()     # [pool]
        ranked = reranker_cos.rerank_with_cosine(
            query_vec, db_vecs_cpu, candidates, top_k=10
        )
        ranked_indices = [r[0] for r in ranked]

        if q_idx in ranked_indices[:1]:
            correct_r1 += 1
        if q_idx in ranked_indices[:5]:
            correct_r5 += 1
            rank = ranked_indices[:5].index(q_idx) + 1
            sum_p5 += 1.0 / 5.0
            sum_map5 += 1.0 / rank

    total_latency = (time.time() - t0) * 1000.0
    r1_cos = (correct_r1 / N) * 100.0
    r5_cos = (correct_r5 / N) * 100.0
    p5_cos = (sum_p5 / N) * 100.0
    map5_cos = (sum_map5 / N) * 100.0
    delta_r1_cos = r1_cos - baseline_r1

    print(
        f"  {'Stage2a: 64→512 Cosine Rerank':<35} {r1_cos:<7.2f} {r5_cos:<7.2f} {p5_cos:<7.2f} {map5_cos:<7.2f} "
        f"{delta_r1_cos:+.2f}%   {total_latency:.1f}ms total"
    )

    # --- Stage 2b: Cross-encoder reranking (optional, slow) ---
    if try_cross_encoder and captions is not None:
        try:
            reranker_ce = TwoStageReranker(mode='cross_encoder')
            correct_r1_ce = 0
            correct_r5_ce = 0
            sum_p5_ce = 0.0
            sum_map5_ce = 0.0
            t0 = time.time()

            for q_idx in range(N):
                candidates = stage1_indices[q_idx].cpu().tolist()
                # Use the text from the text embedding as query
                # NOTE: We approximate query text from captions[q_idx] since
                # at benchmark time we only have embeddings, not raw text.
                # For a fair cross-encoder eval, pass actual query strings.
                query_text = captions[q_idx] if q_idx < len(captions) else ""
                candidate_caps = [captions[i] for i in candidates if i < len(captions)]

                ranked = reranker_ce.rerank_with_cross_encoder(
                    query_text, candidate_caps, candidates[:len(candidate_caps)], top_k=10
                )
                ranked_indices = [r[0] for r in ranked]

                if q_idx in ranked_indices[:1]:
                    correct_r1_ce += 1
                if q_idx in ranked_indices[:5]:
                    correct_r5_ce += 1
                    rank = ranked_indices[:5].index(q_idx) + 1
                    sum_p5_ce += 1.0 / 5.0
                    sum_map5_ce += 1.0 / rank

            total_latency_ce = (time.time() - t0) * 1000.0
            r1_ce = (correct_r1_ce / N) * 100.0
            r5_ce = (correct_r5_ce / N) * 100.0
            p5_ce = (sum_p5_ce / N) * 100.0
            map5_ce = (sum_map5_ce / N) * 100.0
            delta_r1_ce = r1_ce - baseline_r1

            print(
                f"  {'Stage2b: 64→Cross-Encoder Rerank':<35} {r1_ce:<7.2f} {r5_ce:<7.2f} {p5_ce:<7.2f} {map5_ce:<7.2f} "
                f"{delta_r1_ce:+.2f}%   {total_latency_ce:.1f}ms total"
            )
        except ImportError as e:
            print(f"  [Cross-Encoder] Skipped: {e}")
    elif try_cross_encoder:
        print("  [Cross-Encoder] Skipped: captions list not provided.")

    print(f"  {'-'*90}")


# ======================================================================
# Section C — AQE Hyperparameter Sweep
# ======================================================================

def run_aqe_benchmark(image_features: torch.Tensor, text_features: torch.Tensor):
    """Sweep alpha and top_k for Alpha Query Expansion."""
    from query_expansion import AlphaQueryExpander

    device = image_features.device

    # Baseline
    img_norm = F.normalize(image_features, dim=-1)
    txt_norm = F.normalize(text_features, dim=-1)
    base_metrics = compute_metrics(txt_norm @ img_norm.T, k=5)
    baseline_r1, baseline_r5 = base_metrics["top1"], base_metrics["top5"]
    baseline_p5, baseline_map5 = base_metrics["p5"], base_metrics["map5"]

    print("\n" + "=" * 100)
    print("  [C] ALPHA QUERY EXPANSION (AQE) — Hyperparameter Sweep")
    print("=" * 100)
    print(f"  Baseline (512-dim, no AQE): Top-1={baseline_r1:.2f}%  Top-5={baseline_r5:.2f}%  P@5={baseline_p5:.2f}%  mAP@5={baseline_map5:.2f}%\n")
    print(f"  {'alpha':<7} {'top_k':<7} {'Top-1':<7} {'Top-5':<7} {'P@5':<7} {'mAP@5':<7} {'dTop-1':<8} {'Latency (ms)'}")
    print(f"  {'-'*95}")

    alpha_values = [0.5, 0.6, 0.7, 0.8, 0.9]
    top_k_values = [3, 5, 10]
    best_r1 = 0.0
    best_config = {}

    for alpha in alpha_values:
        for top_k in top_k_values:
            expander = AlphaQueryExpander(alpha=alpha, top_k=top_k)

            t0 = time.time()
            refined_txt = expander.expand_batch(text_features, image_features)
            latency_ms = (time.time() - t0) * 1000.0

            sim_aqe = refined_txt @ img_norm.T
            aqe_metrics = compute_metrics(sim_aqe, k=5)
            r1, r5 = aqe_metrics["top1"], aqe_metrics["top5"]
            p5, map5 = aqe_metrics["p5"], aqe_metrics["map5"]
            delta = r1 - baseline_r1

            marker = " << BEST" if r1 > best_r1 else ""
            if r1 > best_r1:
                best_r1 = r1
                best_config = {"alpha": alpha, "top_k": top_k}

            print(
                f"  {alpha:<7.1f} {top_k:<7} {r1:<7.2f} {r5:<7.2f} {p5:<7.2f} {map5:<7.2f} "
                f"{delta:+.2f}%   {latency_ms:.1f}ms{marker}"
            )

    print(f"  {'-'*95}")
    print(f"  Best: alpha={best_config.get('alpha')}, top_k={best_config.get('top_k')} → Top-1={best_r1:.2f}%")

    return best_config


# ======================================================================
# Section D — Combined: AQE + Cosine Reranking
# ======================================================================

def run_combined_benchmark(
    image_features: torch.Tensor,
    text_features: torch.Tensor,
    aqe_alpha: float = 0.7,
    aqe_top_k: int = 5,
    candidate_pool_size: int = 50,
):
    """
    Stack AQE on top of two-stage cosine reranking:
        1. AQE-refine the query
        2. 64-dim fast search on refined query → top-K candidates
        3. 512-dim cosine rerank candidates
    """
    from query_expansion import AlphaQueryExpander
    from reranker import TwoStageReranker

    device = image_features.device
    N = image_features.shape[0]

    print("\n" + "=" * 95)
    print(f"  [D] COMBINED: AQE (α={aqe_alpha}, k={aqe_top_k}) + 64→512 Cosine Rerank")
    print("=" * 95)

    # Baseline
    img_norm_512 = F.normalize(image_features, dim=-1)
    txt_norm_512 = F.normalize(text_features, dim=-1)
    base_metrics = compute_metrics(txt_norm_512 @ img_norm_512.T, k=5)
    baseline_r1 = base_metrics["top1"]

    # Step 1: AQE refinement
    expander = AlphaQueryExpander(alpha=aqe_alpha, top_k=aqe_top_k)
    t0 = time.time()
    refined_txt_512 = expander.expand_batch(text_features, image_features)  # [N, 512]
    aqe_time = (time.time() - t0) * 1000.0

    # Step 2: 64-dim search on refined query
    img_64 = F.normalize(image_features[:, :64], dim=-1)
    refined_64 = F.normalize(refined_txt_512[:, :64], dim=-1)
    sim_64 = refined_64 @ img_64.T
    _, stage1_indices = sim_64.topk(candidate_pool_size, dim=1)

    # Step 3: 512-dim cosine rerank
    db_vecs_cpu = image_features.cpu()
    refined_cpu = refined_txt_512.cpu()
    reranker = TwoStageReranker(mode='cosine')

    correct_r1 = 0
    correct_r5 = 0
    sum_p5 = 0.0
    sum_map5 = 0.0
    t0 = time.time()

    for q_idx in range(N):
        candidates = stage1_indices[q_idx].cpu().tolist()
        ranked = reranker.rerank_with_cosine(
            refined_cpu[q_idx], db_vecs_cpu, candidates, top_k=10
        )
        ranked_indices = [r[0] for r in ranked]

        if q_idx in ranked_indices[:1]:
            correct_r1 += 1
        if q_idx in ranked_indices[:5]:
            correct_r5 += 1
            rank = ranked_indices[:5].index(q_idx) + 1
            sum_p5 += 1.0 / 5.0
            sum_map5 += 1.0 / rank

    rerank_time = (time.time() - t0) * 1000.0
    total_time = aqe_time + rerank_time
    r1 = (correct_r1 / N) * 100.0
    r5 = (correct_r5 / N) * 100.0
    p5 = (sum_p5 / N) * 100.0
    map5 = (sum_map5 / N) * 100.0

    print(f"\n  {'Strategy':<38} {'Top-1':<7} {'Top-5':<7} {'P@5':<7} {'mAP@5':<7} {'dTop-1':<8} {'Latency'}")
    print(f"  {'-'*95}")
    print(f"  {'Baseline: 512-dim direct':<38} {baseline_r1:<7.2f} {'—':<7} {'—':<7} {'—':<7} {'—':<8} —")
    print(
        f"  {'AQE + 64→512 Cosine Rerank':<38} {r1:<7.2f} {r5:<7.2f} {p5:<7.2f} {map5:<7.2f} "
        f"{r1 - baseline_r1:+.2f}%   {total_time:.1f}ms"
    )
    print(f"  {'-'*95}")
    print(f"  (AQE: {aqe_time:.1f}ms | Rerank: {rerank_time:.1f}ms)")


# ======================================================================
# Main entry point
# ======================================================================

def load_embeddings(device: str):
    img_path = 'embeddings/test_image_features.pt'
    txt_path = 'embeddings/test_text_features.pt'

    if not os.path.exists(img_path) or not os.path.exists(txt_path):
        print("Error: Embeddings not found. Run 'python extract_features.py' first.")
        return None, None

    image_features = torch.load(img_path, weights_only=True).to(device)
    text_features  = torch.load(txt_path, weights_only=True).to(device)

    print(f"Loaded embeddings: {image_features.shape[0]} samples, {image_features.shape[1]}-dim")
    return image_features, text_features


def main():
    parser = argparse.ArgumentParser(description="MRL Retrieval Benchmark")
    parser.add_argument(
        "--mode",
        choices=["baseline", "rerank", "aqe", "combined", "full"],
        default="full",
        help="Which benchmark section to run (default: full = all sections)",
    )
    parser.add_argument("--pool", type=int, default=50,
                        help="Candidate pool size for Stage 1 reranking (default: 50)")
    parser.add_argument("--aqe-alpha", type=float, default=0.7,
                        help="AQE alpha for combined benchmark (default: 0.7)")
    parser.add_argument("--aqe-top-k", type=int, default=5,
                        help="AQE top_k for combined benchmark (default: 5)")
    parser.add_argument("--cross-encoder", action="store_true",
                        help="Include cross-encoder reranking in benchmark (slow)")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n[Benchmark] Device: {device.upper()}")

    image_features, text_features = load_embeddings(device)
    if image_features is None or text_features is None:
        return

    N = image_features.shape[0]
    print(f"[Benchmark] Test set: {N} samples\n")

    if args.mode in ("baseline", "full"):
        run_baseline_benchmark(image_features, text_features)

    if args.mode in ("rerank", "full"):
        run_reranking_benchmark(
            image_features, text_features,
            candidate_pool_size=args.pool,
            try_cross_encoder=args.cross_encoder,
        )

    if args.mode in ("aqe", "full"):
        best_config = run_aqe_benchmark(image_features, text_features)
        # Use best config for combined if running full
        if args.mode == "full":
            args.aqe_alpha = best_config.get("alpha", 0.7)
            args.aqe_top_k = best_config.get("top_k", 5)

    if args.mode in ("combined", "full"):
        run_combined_benchmark(
            image_features, text_features,
            aqe_alpha=args.aqe_alpha,
            aqe_top_k=args.aqe_top_k,
            candidate_pool_size=args.pool,
        )

    print("\n[Benchmark] Done.")


if __name__ == "__main__":
    main()
