"""
Training Pipeline for Fixed Feature (FF) Baselines
===================================================
Trains independent models fixed at individual dimensions D in {16, 32, 64, 128, 256, 512}
to serve as traditional Fixed Feature baselines for proving MRL effectiveness.

Each FF model is trained completely independently, starting from raw CLIP
pretrained weights (NOT from any MRL checkpoint), so it can serve as a fair,
independent oracle upper bound when compared against MRL nested embeddings.

Hyperparameters exactly match `train_v3.py` for fair, apples-to-apples comparison:
    - BATCH_SIZE     = 64
    - LR             = 3e-6
    - TEMPERATURE    = 0.05
    - HARD_NEG_RATIO = 0.3
    - NUM_EPOCHS     = 15

Usage:
    # Train a single dimension (e.g. 64):
    python train_ff.py --dim 64

    # Train all dimensions sequentially (16, 32, 64, 128, 256, 512):
    python train_ff.py --all

    # Run on Google Colab with custom paths if needed:
    python train_ff.py --dim 64 --checkpoint_dir /content/drive/MyDrive/checkpoints
"""

import argparse
import json
import os
import time

import torch
import torch.nn.functional as F
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts
from tqdm import tqdm

from dataset import create_dataloaders
from model import MRL_CrossModal_Model
from loss import MRL_InfoNCE_HardNeg_Loss


# =========== DEFAULT CONFIG ===========
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
# ======================================


def linear_warmup_lr(optimizer, step: int, warmup_steps: int, base_lr: float):
    """Linearly scale LR from 0 to base_lr over warmup_steps."""
    if step < warmup_steps:
        lr = base_lr * (step + 1) / warmup_steps
        for pg in optimizer.param_groups:
            pg['lr'] = lr


def compute_val_recall_at_1(model, val_loader, device: str, target_dim: int) -> float:
    """Compute validation Recall@1 explicitly truncated at target_dim."""
    model.eval()
    all_img, all_txt = [], []
    with torch.no_grad():
        for images, input_ids, attention_masks in val_loader:
            images          = images.to(device)
            input_ids       = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            img_feats = model.extract_image_features(images, dim=target_dim).cpu()
            txt_feats = model.extract_text_features(input_ids, attention_masks, dim=target_dim).cpu()
            all_img.append(img_feats)
            all_txt.append(txt_feats)

    img_all = F.normalize(torch.cat(all_img), dim=-1)
    txt_all = F.normalize(torch.cat(all_txt), dim=-1)
    sim     = txt_all @ img_all.T
    N       = sim.shape[0]
    _, topk = sim.topk(1, dim=1)
    targets = torch.arange(N).view(-1, 1)
    return ((topk == targets).sum(dim=1) > 0).float().mean().item() * 100.0


def train_ff_dimension(
    target_dim: int,
    data_csv: str,
    data_img: str,
    checkpoint_dir: str,
    epochs: int,
    batch_size: int,
    lr: float,
    temperature: float,
    hard_neg_ratio: float,
    warmup_epochs: int = 2,
    early_stop_patience: int = 4,
    grad_clip: float = 0.5,
):
    print("=" * 65)
    print(f"=== FIXED FEATURE (FF) BASELINE TRAINING @ DIM = {target_dim} ===")
    print("=" * 65)
    print(f"Config: dim={target_dim}, batch={batch_size}, lr={lr}, temp={temperature}, hard_neg={hard_neg_ratio}")

    os.makedirs(checkpoint_dir, exist_ok=True)
    best_ckpt_path = os.path.join(checkpoint_dir, f"ff_dim_{target_dim}_best.pt")
    history_path   = os.path.join(checkpoint_dir, f"ff_dim_{target_dim}_history.json")

    # 1. DataLoaders
    train_loader, val_loader, _, _ = create_dataloaders(
        csv_file=data_csv,
        img_dir=data_img,
        batch_size=batch_size,
        num_workers=2,
    )

    # 2. Model — FF baseline must start from raw CLIP pretrained weights, NOT from
    # any MRL checkpoint. This is required for a fair, independent oracle comparison
    # against MRL: FF represents "what a model trained from scratch specifically for
    # this single dimension can achieve", so it cannot inherit any representation
    # already shaped by MRL's multi-dimension nested training.
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}\n")
    model = MRL_CrossModal_Model().to(device)
    print("Starting from CLIP pretrained weights (independent of MRL pipeline).\n")

    # 3. Loss & Optimizer (Only compute loss on target_dim!)
    criterion = MRL_InfoNCE_HardNeg_Loss(
        nesting_list=[target_dim],
        temperature=temperature,
        hard_neg_ratio=hard_neg_ratio,
    )

    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = CosineAnnealingWarmRestarts(optimizer, T_0=5, T_mult=1, eta_min=1e-8)

    warmup_steps = warmup_epochs * len(train_loader)
    global_step  = 0

    best_val_r1 = 0.0
    no_improve  = 0
    history     = []

    print(f"{'Epoch':<8} {'Train Loss':<14} {'Val R@1 (%)':<16} {'LR':<12} {'Time'}")
    print("-" * 65)

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        t_start    = time.time()

        loop = tqdm(train_loader, desc=f"Dim {target_dim} - Epoch {epoch}/{epochs}", leave=False)
        for images, input_ids, attention_masks in loop:
            images          = images.to(device)
            input_ids       = input_ids.to(device)
            attention_masks = attention_masks.to(device)

            linear_warmup_lr(optimizer, global_step, warmup_steps, lr)

            optimizer.zero_grad()
            img_feats, txt_feats = model(images, input_ids, attention_masks)
            loss = criterion(img_feats, txt_feats)
            loss.backward()

            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip)
            optimizer.step()

            if global_step >= warmup_steps:
                scheduler.step(epoch - 1 + loop.n / len(train_loader))

            total_loss += loss.item()
            global_step += 1
            loop.set_postfix(loss=f"{loss.item():.4f}")

        avg_loss = total_loss / len(train_loader)
        val_r1   = compute_val_recall_at_1(model, val_loader, device, target_dim=target_dim)
        elapsed  = time.time() - t_start
        cur_lr   = optimizer.param_groups[0]['lr']

        print(f"{epoch:<8} {avg_loss:<14.4f} {val_r1:<16.2f} {cur_lr:<12.2e} {elapsed:.1f}s")

        history.append({
            "epoch": epoch,
            "train_loss": round(avg_loss, 4),
            "val_recall_at_1": round(val_r1, 2),
            "lr": cur_lr,
        })

        if val_r1 > best_val_r1:
            best_val_r1 = val_r1
            no_improve  = 0
            torch.save(model.state_dict(), best_ckpt_path)
            print(f"  --> Saved new best FF model @ dim {target_dim}: R@1 = {best_val_r1:.2f}%")
        else:
            no_improve += 1
            if no_improve >= early_stop_patience:
                print(f"  --> Early stopping triggered at epoch {epoch} (no improvement for {early_stop_patience} epochs).")
                break

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"\nCompleted FF training for dim={target_dim}. Best Val R@1 = {best_val_r1:.2f}%")
    print(f"Saved best checkpoint to: {best_ckpt_path}\n")
    return best_val_r1


def main():
    parser = argparse.ArgumentParser(description="Train Fixed Feature (FF) Baseline Models")
    parser.add_argument("--dim", type=int, choices=SUPPORTED_DIMS, default=None,
                        help="Specific dimension to train (16, 32, 64, 128, 256, 512)")
    parser.add_argument("--all", action="store_true",
                        help="Train all dimensions sequentially")
    parser.add_argument("--data_csv", type=str, default=DEFAULT_DATA_CSV)
    parser.add_argument("--data_img", type=str, default=DEFAULT_DATA_IMG)
    parser.add_argument("--checkpoint_dir", type=str, default=DEFAULT_CKPT_DIR)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-6)
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--hard_neg_ratio", type=float, default=0.3)
    args = parser.parse_args()

    if not args.all and args.dim is None:
        parser.error("Please specify either --dim <D> or --all.")

    dims_to_train = SUPPORTED_DIMS if args.all else [args.dim]

    results_summary = {}
    for d in dims_to_train:
        best_r1 = train_ff_dimension(
            target_dim=d,
            data_csv=args.data_csv,
            data_img=args.data_img,
            checkpoint_dir=args.checkpoint_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            temperature=args.temperature,
            hard_neg_ratio=args.hard_neg_ratio,
        )
        results_summary[d] = best_r1

    print("=" * 65)
    print("FIXED FEATURE (FF) TRAINING SUMMARY")
    print("=" * 65)
    for d, r1 in results_summary.items():
        print(f"  Dimension {d:3d}: Best Val R@1 = {r1:.2f}%")
    print("=" * 65)


if __name__ == "__main__":
    main()