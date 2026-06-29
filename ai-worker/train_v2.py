"""
Training Pipeline v2 — MRL with Hard Negative Mining
=====================================================
Improvements over train.py (v1):
    1. Uses MRL_InfoNCE_HardNeg_Loss instead of standard InfoNCE
       → forces model to learn hard cases (similar-looking fashion items)
    2. Validation Recall@1 computed after every epoch (early stopping)
    3. Best checkpoint saved based on val Recall@1 (not loss)
    4. Cosine LR schedule with warmup
    5. Gradient clipping for stable training
    6. Longer training (10 epochs) with early stopping patience

Usage:
    python train_v2.py

    # Or on Google Colab with custom paths:
    DATA_CSV=/path/to/data.csv DATA_IMG=/path/to/images python train_v2.py
"""

import os
import time

import torch
import torch.nn.functional as F
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from tqdm import tqdm

from dataset import create_dataloaders
from model import MRL_CrossModal_Model
from loss import MRL_InfoNCE_HardNeg_Loss


# =========== CONFIG ===========
if os.path.exists('/content'):
    print("[System] Running on Google Colab...")
    DATA_CSV = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data.csv"
    DATA_IMG = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data_images"
else:
    print("[System] Running on Local machine...")
    DATA_CSV = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.csv"
    DATA_IMG = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"

NUM_EPOCHS       = 10    # Max epochs (early stopping may exit earlier)
BATCH_SIZE       = 32
LR               = 5e-6  # Lower than v1 to avoid destroying pretrained weights
WEIGHT_DECAY     = 1e-4
HARD_NEG_RATIO   = 0.5   # Keep top-50% hardest negatives per batch
EARLY_STOP_PAT   = 3     # Stop if val Recall@1 doesn't improve for N epochs
GRAD_CLIP        = 1.0   # Max gradient norm
NESTING_LIST     = [16, 32, 64, 128, 256, 512]
CHECKPOINT_DIR   = "checkpoints"
BEST_CKPT_PATH   = os.path.join(CHECKPOINT_DIR, "mrl_v2_best.pt")
# ==============================


def compute_val_recall_at_1(model, val_loader, device: str) -> float:
    """
    Run inference on the validation set and return Recall@1.
    Uses full 512-dim embeddings for accuracy measurement.
    """
    model.eval()
    all_img, all_txt = [], []

    with torch.no_grad():
        for images, input_ids, attention_masks in val_loader:
            images         = images.to(device)
            input_ids      = input_ids.to(device)
            attention_masks = attention_masks.to(device)

            img_emb = model.extract_image_features(images)             # [B, 512]
            txt_emb = model.extract_text_features(input_ids, attention_masks)  # [B, 512]

            all_img.append(img_emb.cpu())
            all_txt.append(txt_emb.cpu())

    img_all = torch.cat(all_img, dim=0)   # [N_val, 512]
    txt_all = torch.cat(all_txt, dim=0)   # [N_val, 512]

    img_norm = F.normalize(img_all, dim=-1)
    txt_norm = F.normalize(txt_all, dim=-1)

    sim = txt_norm @ img_norm.T            # [N_val, N_val]
    N = sim.shape[0]

    _, topk = sim.topk(1, dim=1)
    targets = torch.arange(N).view(-1, 1)
    recall_1 = ((topk == targets).sum(dim=1) > 0).float().mean().item() * 100.0
    return recall_1


def train():
    print("=== MRL FINE-TUNING PIPELINE v2 (Hard Negative Mining) ===\n")

    # 1. DataLoaders
    train_loader, val_loader, _, _ = create_dataloaders(
        csv_file=DATA_CSV,
        img_dir=DATA_IMG,
        batch_size=BATCH_SIZE,
        num_workers=2,
    )

    # 2. Model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}\n")
    model = MRL_CrossModal_Model().to(device)

    # Optional: load from v1 checkpoint to continue fine-tuning
    v1_ckpt = os.path.join(CHECKPOINT_DIR, "mrl_clip_epoch_3.pt")
    if os.path.exists(v1_ckpt):
        model.load_state_dict(torch.load(v1_ckpt, map_location=device))
        print(f"Loaded v1 checkpoint from {v1_ckpt} — continuing fine-tune.\n")
    else:
        print("No v1 checkpoint found — starting from CLIP pretrained weights.\n")

    # 3. Loss, Optimizer, Scheduler
    criterion = MRL_InfoNCE_HardNeg_Loss(
        nesting_list=NESTING_LIST,
        temperature=0.07,
        hard_neg_ratio=HARD_NEG_RATIO,
    )

    optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    # Cosine annealing: LR gradually drops to near-zero over NUM_EPOCHS
    scheduler = CosineAnnealingLR(optimizer, T_max=NUM_EPOCHS, eta_min=1e-7)

    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    best_val_r1   = 0.0
    no_improve    = 0          # Early stopping counter
    history       = []

    print(f"{'Epoch':<8} {'Train Loss':<14} {'Val Recall@1':<16} {'LR':<12} {'Time'}")
    print("-" * 65)

    for epoch in range(1, NUM_EPOCHS + 1):
        # ── Training ──────────────────────────────────────────────────
        model.train()
        total_loss = 0.0
        t_start = time.time()

        loop = tqdm(train_loader, desc=f"Epoch {epoch}/{NUM_EPOCHS}", leave=False)
        for images, input_ids, attention_masks in loop:
            images          = images.to(device)
            input_ids       = input_ids.to(device)
            attention_masks = attention_masks.to(device)

            optimizer.zero_grad()
            img_emb, txt_emb = model(images, input_ids, attention_masks)
            loss = criterion(img_emb, txt_emb)
            loss.backward()

            # Gradient clipping — prevents exploding gradients with small LR
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)

            optimizer.step()
            total_loss += loss.item()
            loop.set_postfix(loss=f"{loss.item():.4f}")

        avg_loss  = total_loss / len(train_loader)
        scheduler.step()
        current_lr = scheduler.get_last_lr()[0]

        # ── Validation ────────────────────────────────────────────────
        val_r1 = compute_val_recall_at_1(model, val_loader, device)
        elapsed = time.time() - t_start

        history.append({"epoch": epoch, "loss": avg_loss, "val_r1": val_r1})
        marker = ""

        if val_r1 > best_val_r1:
            best_val_r1 = val_r1
            no_improve  = 0
            torch.save(model.state_dict(), BEST_CKPT_PATH)
            marker = " ◄ BEST"
        else:
            no_improve += 1

        print(
            f"{epoch:<8} {avg_loss:<14.4f} {val_r1:<16.2f} "
            f"{current_lr:<12.2e} {elapsed:.0f}s{marker}"
        )

        # Per-epoch checkpoint
        ckpt_path = os.path.join(CHECKPOINT_DIR, f"mrl_v2_epoch_{epoch}.pt")
        torch.save(model.state_dict(), ckpt_path)

        # ── Early stopping ────────────────────────────────────────────
        if no_improve >= EARLY_STOP_PAT:
            print(f"\nEarly stopping: Val Recall@1 did not improve for {EARLY_STOP_PAT} epochs.")
            break

    print("-" * 65)
    print(f"\nTraining complete. Best Val Recall@1: {best_val_r1:.2f}%")
    print(f"Best checkpoint saved to: {BEST_CKPT_PATH}")

    # Print learning curve summary
    print("\n--- Learning Curve ---")
    for h in history:
        print(f"  Epoch {h['epoch']:>2}: Loss={h['loss']:.4f}  Val R@1={h['val_r1']:.2f}%")


if __name__ == "__main__":
    train()
