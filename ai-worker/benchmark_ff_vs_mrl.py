import argparse
import os
import time

import torch
import torch.nn.functional as F
from tqdm import tqdm

from dataset import create_dataloaders
from model import MRL_CrossModal_Model
from typing import cast, Sized

SUPPORTED_DIMS = [16, 32, 64, 128, 256, 512]

if os.path.exists('/content'):
    print("[System] Running on Google Colab...")
    DEFAULT_DATA_CSV = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data.csv"
    DEFAULT_DATA_IMG = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data_images"
    DEFAULT_CKPT_DIR = "/content/drive/MyDrive/Train_MRL_test_19-6/checkpoints"
else:
    print("[System] Running on Local machine...")
    DEFAULT_DATA_CSV = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.csv"
    DEFAULT_DATA_IMG = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"
    DEFAULT_CKPT_DIR = "checkpoints"


def evaluate_retrieval_metrics(img_embeds: torch.Tensor, txt_embeds: torch.Tensor, k: int = 5) -> dict:
    """Compute Top-1, Top-K, Precision@K, and mAP@K."""
    img_norm = F.normalize(img_embeds, dim=-1)
    txt_norm = F.normalize(txt_embeds, dim=-1)
    sim = txt_norm @ img_norm.T
    N = sim.shape[0]

    _, topk_indices = sim.topk(max(k, 1), dim=1)
    targets = torch.arange(N, device=sim.device).view(-1, 1)
    results = (topk_indices == targets)

    top1 = (results[:, 0]).float().mean().item() * 100.0
    topk = (results[:, :k].sum(dim=1) > 0).float().mean().item() * 100.0
    p_at_k = (results[:, :k].sum(dim=1).float() / k).mean().item() * 100.0

    ap = torch.zeros(N, device=sim.device)
    nonzero_idx = results[:, :k].nonzero(as_tuple=False)
    if nonzero_idx.numel() > 0:
        row_indices = nonzero_idx[:, 0]
        col_indices = nonzero_idx[:, 1]
        ap[row_indices] = 1.0 / (col_indices.float() + 1.0)
    map_at_k = ap.mean().item() * 100.0

    return {
        "recall@1": top1,
        f"recall@{k}": topk,
        f"precision@{k}": p_at_k,
        f"mAP@{k}": map_at_k,
    }


def extract_full_features(model, dataloader, device):
    """Extract full 512-dim image & text features for the dataset."""
    model.eval()
    img_list, txt_list = [], []
    with torch.no_grad():
        for images, input_ids, attention_masks in tqdm(dataloader, desc="Extracting features", leave=False):
            images = images.to(device)
            input_ids = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            img_list.append(model.extract_image_features(images, dim=512).cpu())
            txt_list.append(model.extract_text_features(input_ids, attention_masks, dim=512).cpu())
    return torch.cat(img_list, dim=0), torch.cat(txt_list, dim=0)


def main():
    parser = argparse.ArgumentParser(description="Benchmark FF vs MRL Checkpoints")
    parser.add_argument("--data_csv", type=str, default=DEFAULT_DATA_CSV)
    parser.add_argument("--data_img", type=str, default=DEFAULT_DATA_IMG)
    parser.add_argument("--checkpoint_dir", type=str, default=DEFAULT_CKPT_DIR)
    parser.add_argument("--batch_size", type=int, default=64)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}\n")
    
    _, _, test_loader, _ = create_dataloaders(
        csv_file=args.data_csv,
        img_dir=args.data_img,
        batch_size=args.batch_size,
        num_workers=2,
    )
    test_dataset = cast(Sized, test_loader.dataset)
    print(f"[Data] Evaluating on TEST split: {len(test_dataset)} samples\n")

    preferred_mrl_ckpt = os.path.join(args.checkpoint_dir, "mrl_v3_best.pt")
    fallback_mrl_ckpt = os.path.join(args.checkpoint_dir, "mrl_v2_best.pt")

    if os.path.exists(preferred_mrl_ckpt):
        mrl_ckpt_path = preferred_mrl_ckpt
    elif os.path.exists(fallback_mrl_ckpt):
        mrl_ckpt_path = fallback_mrl_ckpt
        print("=" * 80)
        print("[MRL] !!! WARNING: mrl_v3_best.pt NOT FOUND !!!")
        print(f"[MRL] !!! Falling back to mrl_v2_best.pt -- results will NOT match")
        print(f"[MRL] !!! the v3 numbers reported elsewhere in the thesis (Ch.6). !!!")
        print(f"[MRL] !!! checkpoint_dir checked: {args.checkpoint_dir}")
        print("=" * 80)
    else:
        mrl_ckpt_path = None

    # 1. Evaluate MRL (single model sliced across D)
    mrl_results = {}
    if mrl_ckpt_path is not None:
        try:
            from benchmark import load_embeddings
            img_512, txt_512 = load_embeddings(device)
            if img_512 is None or txt_512 is None:
                raise ValueError("Embeddings not found")
            print(f"[MRL] Successfully loaded pre-extracted MRL embeddings from disk.\n")
        except Exception as e:
            print(f"[MRL] Falling back to feature extraction: {e}")
            print(f"[MRL] Loading MRL checkpoint: {mrl_ckpt_path}")
            model_mrl = MRL_CrossModal_Model().to(device)
            model_mrl.load_state_dict(torch.load(mrl_ckpt_path, map_location=device))
            img_512, txt_512 = extract_full_features(model_mrl, test_loader, device)
            print(f"[MRL] Extracted features for {img_512.shape[0]} samples "
                  f"({img_512.shape[1]}-dim)\n")

        for d in SUPPORTED_DIMS:
            m = evaluate_retrieval_metrics(img_512[:, :d], txt_512[:, :d], k=5)
            mrl_results[d] = m
    else:
        print(f"[MRL] WARNING: Could not find any MRL checkpoint in "
              f"{args.checkpoint_dir} (looked for mrl_v3_best.pt, mrl_v2_best.pt).")

    # 2. Evaluate Fixed Feature (FF) checkpoints (each trained independently at D)
    ff_results = {}
    for d in SUPPORTED_DIMS:
        ff_ckpt_path = os.path.join(args.checkpoint_dir, f"ff_dim_{d}_best.pt")
        if os.path.exists(ff_ckpt_path):
            print(f"[FF] Evaluating checkpoint for dim {d}: {ff_ckpt_path}")
            model_ff = MRL_CrossModal_Model().to(device)
            model_ff.load_state_dict(torch.load(ff_ckpt_path, map_location=device))
            img_d, txt_d = extract_full_features(model_ff, test_loader, device)
            m = evaluate_retrieval_metrics(img_d[:, :d], txt_d[:, :d], k=5)
            ff_results[d] = m
        else:
            ff_results[d] = None

    # Print Markdown Comparison Table
    print("\n" + "=" * 80)
    print("### Fixed Feature (FF) vs. MRL Comparison Table")
    print("=" * 80)
    print("| Dimension | FF Recall@1 (%) | MRL Recall@1 (%) | Δ R@1 (MRL - FF) | FF Recall@5 (%) | MRL Recall@5 (%) |")
    print("| :---: | :---: | :---: | :---: | :---: | :---: |")

    for d in SUPPORTED_DIMS:
        ff_r1 = f"{ff_results[d]['recall@1']:.2f}" if ff_results.get(d) else "N/A"
        ff_r5 = f"{ff_results[d]['recall@5']:.2f}" if ff_results.get(d) else "N/A"
        mrl_r1_val = mrl_results[d]['recall@1'] if d in mrl_results else None
        mrl_r5_val = mrl_results[d]['recall@5'] if d in mrl_results else None

        mrl_r1 = f"{mrl_r1_val:.2f}" if mrl_r1_val is not None else "N/A"
        mrl_r5 = f"{mrl_r5_val:.2f}" if mrl_r5_val is not None else "N/A"

        if ff_results.get(d) and mrl_r1_val is not None:
            delta = mrl_r1_val - ff_results[d]['recall@1']
            delta_str = f"{delta:+.2f}"
        else:
            delta_str = "-"

        print(f"| **{d}** | {ff_r1} | {mrl_r1} | **{delta_str}** | {ff_r5} | {mrl_r5} |")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()