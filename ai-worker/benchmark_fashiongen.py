import argparse
import json
import os
import time
from collections import defaultdict
from typing import Dict, List, Tuple

import torch
import torch.nn.functional as F

import config_fashiongen as cfg
from extract_features_mrl_fashiongen import MRL_IMG_FEATS, MRL_TXT_FEATS, MRL_PRODUCT_IDS

# const
WARMUP_ITERS = 3
TIMED_ITERS  = 10

EMBEDDING_PATHS = {
    "zeroshot": (cfg.VAL_IMG_FEATS, cfg.VAL_TXT_FEATS, cfg.VAL_PRODUCT_IDS),
    "mrl": (MRL_IMG_FEATS, MRL_TXT_FEATS, MRL_PRODUCT_IDS),
}

# latency
def _sync(device: str) -> None:
    if device == "cuda":
        torch.cuda.synchronize()

def _timed_search(query: torch.Tensor, gallery: torch.Tensor, device: str) -> float:
    """Latency (ms) for a single query vs full gallery."""
    q = query.unsqueeze(0)  # [1, d]
    for _ in range(WARMUP_ITERS):
        _ = q @ gallery.T
    _sync(device)

    times = []
    for _ in range(TIMED_ITERS):
        _sync(device)
        t0 = time.perf_counter()
        _ = q @ gallery.T
        _sync(device)
        times.append((time.perf_counter() - t0) * 1000.0)

    return sum(times) / len(times)

# data loading
def load_embeddings(
    device: str, emb_prefix: str = "zeroshot"
) -> Tuple[torch.Tensor, torch.Tensor, List[str]]:
    """Load val embeddings (zero-shot or MRL trained)."""
    img_path, txt_path, pid_path = EMBEDDING_PATHS[emb_prefix]

    for path in [img_path, txt_path, pid_path]:
        if not os.path.exists(path):
            script = "extract_features_fashiongen.py" if emb_prefix == "zeroshot" else "extract_features_mrl.py"
            raise FileNotFoundError(f"Missing: {path}\nRun '{script}' first.")

    img_feats   = torch.load(img_path, map_location=device, weights_only=True)
    txt_feats   = torch.load(txt_path, map_location=device, weights_only=True)
    with open(pid_path, encoding="utf-8") as f:
        product_ids = json.load(f)

    print(f"Embeddings : [{emb_prefix.upper()}]")
    print(f"Image features : {tuple(img_feats.shape)}")
    print(f"Text  features : {tuple(txt_feats.shape)}")
    print(f"Product IDs : {len(product_ids):,} entries, {len(set(product_ids)):,} unique products")
    return img_feats, txt_feats, product_ids

def build_gt_index(product_ids: List[str]) -> Dict[str, List[int]]:
    """Map product_id -> list of gallery indices."""
    gt: Dict[str, List[int]] = defaultdict(list)
    for idx, pid in enumerate(product_ids):
        gt[pid].append(idx)
    return gt

def compute_recall(
    query_feats  : torch.Tensor,        # [N, d] - L2-normalised query vectors
    gallery_feats: torch.Tensor,        # [M, d] - L2-normalised gallery vectors
    query_ids    : List[str],           # product_id for each query
    gt_index     : Dict[str, List[int]],# product_id -> gallery indices
    ks           : Tuple[int, ...] = (1, 5, 10),
    batch_size   : int = 256,
) -> Dict:
    N    = query_feats.shape[0]
    hits   = {k: 0 for k in ks}
    rr_sum = 0.0

    for start in range(0, N, batch_size):
        end         = min(start + batch_size, N)
        q_batch     = query_feats[start:end]            # [B, d]
        scores      = q_batch @ gallery_feats.T          # [B, M]
        ranked      = torch.argsort(scores, dim=1, descending=True)  # [B, M]

        for batch_idx, global_idx in enumerate(range(start, end)):
            pid     = query_ids[global_idx]
            gt_set  = set(gt_index[pid])
            ranking = ranked[batch_idx].tolist()

            # Recall@K
            for k in ks:
                if any(r in gt_set for r in ranking[:k]):
                    hits[k] += 1

    recall = {k: hits[k] / N for k in ks}
    return {"recall": recall, "n_queries": N}

# per-dim computation
def run_one_dim(
    dim          : int,
    img_feats512 : torch.Tensor,
    txt_feats512 : torch.Tensor,
    product_ids  : List[str],
    gt_index     : Dict[str, List[int]],
    device       : str,
) -> Dict:
    """Slice to target dim, L2-normalise, then compute T2I + I2T metrics."""
    img_d = F.normalize(img_feats512[:, :dim], dim=-1)
    txt_d = F.normalize(txt_feats512[:, :dim], dim=-1)

    # Latency: T2I direction (text query -> image gallery)
    lat_ms = _timed_search(txt_d[0], img_d, device)

    # T2I: text queries->image gallery
    t2i = compute_recall(txt_d, img_d, product_ids, gt_index)

    # I2T: image queries->text gallery
    i2t = compute_recall(img_d, txt_d, product_ids, gt_index)

    return {
        "dim"       : dim,
        "latency_ms": lat_ms,
        "t2i"       : t2i,
        "i2t"       : i2t,
    }

def print_table(results: List[Dict], emb_prefix: str) -> None:
    # Column headers
    print()
    header = (f"  {'Dim':<6} "
              f"{'T2I R@1':>8} {'T2I R@5':>8} {'T2I R@10':>9}  "
              f"{'I2T R@1':>8} {'I2T R@5':>8} {'I2T R@10':>9}  "
              f"{'Latency':>9} ")
    print(header)
    print("  " + "-" * 84)

    base_t2i_r1 = results[0]["t2i"]["recall"][1]  # 512-dim is first after sort

    for m in results:
        dim   = m["dim"]
        t2i   = m["t2i"]
        i2t   = m["i2t"]
        lat   = m["latency_ms"]

        print(f"  {dim:<6} "
              f"{t2i['recall'][1]*100:>7.2f}% {t2i['recall'][5]*100:>7.2f}% {t2i['recall'][10]*100:>8.2f}%  "
              f"{i2t['recall'][1]*100:>7.2f}% {i2t['recall'][5]*100:>7.2f}% {i2t['recall'][10]*100:>8.2f}%  "
              f"{lat:>8.2f}ms ")

    print("=" * 86)
    print()

def main():
    parser = argparse.ArgumentParser(description="FashionGen MRL Benchmark (T2I + I2T)")
    parser.add_argument(
        "--dim", type=int, default=None,
        help="Run a single MRL dimension only (e.g. --dim 64). Default: all dims."
    )
    parser.add_argument(
        "--emb_prefix", type=str, default="zeroshot", choices=["zeroshot", "mrl"],
        help="'zeroshot' (default) or 'mrl' (fine-tuned)."
    )
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nDevice: {device}")

    print(f"Loading embeddings ({args.emb_prefix})...")
    img_feats, txt_feats, product_ids = load_embeddings(device, args.emb_prefix)

    print("Building ground-truth index...")
    gt_index = build_gt_index(product_ids)
    print(f"{len(gt_index):,} unique products in gallery")

    dims = [args.dim] if args.dim else cfg.NESTING_LIST[::-1]  # 512 -> 16
    print(f"Running T2I + I2T benchmark for dims: {dims}")

    results = []
    baseline_512 = None

    for dim in dims:
        print(f"dim={dim:>3} ...", end=" ", flush=True)
        m = run_one_dim(dim, img_feats, txt_feats, product_ids, gt_index, device)
        results.append(m)
        print(f"T2I R@1={m['t2i']['recall'][1]*100:.2f}%  "
              f"I2T R@1={m['i2t']['recall'][1]*100:.2f}%  "
              f"latency={m['latency_ms']:.2f}ms")
        if dim == 512:
            baseline_512 = m

    if baseline_512 is None:
        baseline_512 = results[0]

    # Sort 512 -> 16 for display
    results.sort(key=lambda x: x["dim"], reverse=True)
    print_table(results, args.emb_prefix)

if __name__ == "__main__":
    main()
