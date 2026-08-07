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


# =========== CONFIG ===========
if os.path.exists('/content'):
    print("[System] Running on Google Colab...")
    DATA_CSV = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data.csv"
    DATA_IMG = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data_images"
else:
    print("[System] Running on Local machine...")
    DATA_CSV = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.csv"
    DATA_IMG = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"

NUM_EPOCHS       = 15
BATCH_SIZE       = 64    # Larger batch = more hard negatives per step
LR               = 3e-6  # Even smaller to preserve v2 weights
WEIGHT_DECAY     = 1e-4
HARD_NEG_RATIO   = 0.3   # Only top-30% hardest negatives (harder curriculum than v2)
TEMPERATURE      = 0.05  # Sharper than v2 (0.07) → harder contrastive task
WARMUP_EPOCHS    = 2     # Linear warmup before cosine decay
EARLY_STOP_PAT   = 4
GRAD_CLIP        = 0.5   # Tighter clipping than v2
NESTING_LIST     = [16, 32, 64, 128, 256, 512]
CHECKPOINT_DIR   = "checkpoints"
BEST_CKPT_PATH   = os.path.join(CHECKPOINT_DIR, "mrl_v3_best.pt")

# Start from v2 best checkpoint (or fall back to v1)
START_CKPT_PRIORITY = [
    os.path.join(CHECKPOINT_DIR, "mrl_v2_best.pt"),
    os.path.join(CHECKPOINT_DIR, "mrl_clip_epoch_3.pt"),
]
# ==============================


def linear_warmup_lr(optimizer, step: int, warmup_steps: int, base_lr: float):
    """Linearly scale LR from 0 to base_lr over warmup_steps."""
    if step < warmup_steps:
        lr = base_lr * (step + 1) / warmup_steps
        for pg in optimizer.param_groups:
            pg['lr'] = lr


def compute_val_recall_at_1(model, val_loader, device: str) -> float:
    model.eval()
    all_img, all_txt = [], []
    with torch.no_grad():
        for images, input_ids, attention_masks in val_loader:
            images          = images.to(device)
            input_ids       = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            all_img.append(model.extract_image_features(images).cpu())
            all_txt.append(model.extract_text_features(input_ids, attention_masks).cpu())

    img_all = F.normalize(torch.cat(all_img), dim=-1)
    txt_all = F.normalize(torch.cat(all_txt), dim=-1)
    sim     = txt_all @ img_all.T
    N       = sim.shape[0]
    _, topk = sim.topk(1, dim=1)
    targets = torch.arange(N).view(-1, 1)
    return ((topk == targets).sum(dim=1) > 0).float().mean().item() * 100.0


def train():
    print("=== MRL FINE-TUNING v3 (Aggressive Hard Negatives) ===\n")
    print(f"Config: batch={BATCH_SIZE}, lr={LR}, temp={TEMPERATURE}, hard_neg={HARD_NEG_RATIO}\n")

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

    # Load best available checkpoint
    loaded_from = None
    for ckpt in START_CKPT_PRIORITY:
        if os.path.exists(ckpt):
            model.load_state_dict(torch.load(ckpt, map_location=device))
            loaded_from = ckpt
            break

    if loaded_from:
        print(f"Loaded checkpoint: {loaded_from}\n")
    else:
        print("No prior checkpoint found — starting from CLIP pretrained.\n")

    # 3. Loss & Optimizer
    criterion = MRL_InfoNCE_HardNeg_Loss(
        nesting_list=NESTING_LIST,
        temperature=TEMPERATURE,
        hard_neg_ratio=HARD_NEG_RATIO,
    )

    optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    # Cosine annealing with warm restarts (T_0=5: restart every 5 epochs)
    scheduler = CosineAnnealingWarmRestarts(optimizer, T_0=5, T_mult=1, eta_min=1e-8)

    warmup_steps = WARMUP_EPOCHS * len(train_loader)
    global_step  = 0

    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    best_val_r1 = 0.0
    no_improve  = 0
    history     = []

    print(f"{'Epoch':<8} {'Train Loss':<14} {'Val R@1 (%)':<16} {'LR':<12} {'Time'}")
    print("-" * 65)

    for epoch in range(1, NUM_EPOCHS + 1):
        # ── Training ──────────────────────────────────────────────────
        model.train()
        total_loss = 0.0
        t_start    = time.time()

        loop = tqdm(train_loader, desc=f"Epoch {epoch}/{NUM_EPOCHS}", leave=False)
        for images, input_ids, attention_masks in loop:
            images          = images.to(device)
            input_ids       = input_ids.to(device)
            attention_masks = attention_masks.to(device)

            # Warmup LR override
            linear_warmup_lr(optimizer, global_step, warmup_steps, LR)
            global_step += 1

            optimizer.zero_grad()
            img_emb, txt_emb = model(images, input_ids, attention_masks)
            loss = criterion(img_emb, txt_emb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
            optimizer.step()

            total_loss += loss.item()
            loop.set_postfix(loss=f"{loss.item():.4f}")

        # Only step scheduler after warmup
        if epoch > WARMUP_EPOCHS:
            scheduler.step()

        avg_loss   = total_loss / len(train_loader)
        current_lr = optimizer.param_groups[0]['lr']

        # ── Validation ────────────────────────────────────────────────
        val_r1  = compute_val_recall_at_1(model, val_loader, device)
        elapsed = time.time() - t_start
        history.append({"epoch": epoch, "loss": avg_loss, "val_r1": val_r1})
        marker = ""

        if val_r1 > best_val_r1:
            best_val_r1 = val_r1
            no_improve  = 0
            torch.save(model.state_dict(), BEST_CKPT_PATH)
            marker = " << BEST"
        else:
            no_improve += 1

        print(
            f"{epoch:<8} {avg_loss:<14.4f} {val_r1:<16.2f} "
            f"{current_lr:<12.2e} {elapsed:.0f}s{marker}"
        )

        # Per-epoch checkpoint
        torch.save(
            model.state_dict(),
            os.path.join(CHECKPOINT_DIR, f"mrl_v3_epoch_{epoch}.pt")
        )

        if no_improve >= EARLY_STOP_PAT:
            print(f"\nEarly stopping at epoch {epoch}.")
            break

    print("-" * 65)
    print(f"\nTraining complete. Best Val Recall@1: {best_val_r1:.2f}%")
    print(f"Best checkpoint: {BEST_CKPT_PATH}")

    print("\n--- Learning Curve ---")
    for h in history:
        print(f"  Epoch {h['epoch']:>2}: Loss={h['loss']:.4f}  Val R@1={h['val_r1']:.2f}%")


if __name__ == "__main__":
    train()
