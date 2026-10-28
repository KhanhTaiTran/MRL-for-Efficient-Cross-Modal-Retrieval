import os
import torch
import torch.optim as optim
from torch.cuda.amp import autocast, GradScaler
from transformers import get_cosine_schedule_with_warmup
from tqdm import tqdm

import config_fashiongen as cfg
from dataset_fashiongen import create_fashiongen_dataloaders
from model import MRL_CrossModal_Model
from loss import MRL_InfoNCE_HardNeg_Loss

class EarlyStopping:
    def __init__(self, patience=cfg.EARLY_STOP_PAT, min_delta=1e-4):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = float('inf')
        self.early_stop = False

    def __call__(self, val_loss):
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True


def train_one_epoch(model, dataloader, optimizer, scheduler, criterion, scaler, device, epoch):
    model.train()
    total_loss = 0.0
    grad_accum = getattr(cfg, "GRAD_ACCUM", 1)  # default to 1 if not set
    optimizer.zero_grad()
    pbar = tqdm(dataloader, desc=f"Epoch {epoch} [Train]")
    
    for batch_idx, (images, input_ids, attn_masks, _) in enumerate(pbar):
        images     = images.to(device)
        input_ids  = input_ids.to(device)
        attn_masks = attn_masks.to(device)

        with autocast():
            img_embeds, txt_embeds = model(images, input_ids, attn_masks)
            loss = criterion(img_embeds, txt_embeds)
            loss = loss / grad_accum  # scale loss for accumulation

        scaler.scale(loss).backward()
        
        # Only update weights every grad_accum steps
        if (batch_idx + 1) % grad_accum == 0 or (batch_idx + 1) == len(dataloader):
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.GRAD_CLIP)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad()

        total_loss += loss.item() * grad_accum  # unscale for logging
        pbar.set_postfix({"Loss": f"{loss.item() * grad_accum:.4f}", "LR": f"{scheduler.get_last_lr()[0]:.2e}"})

    return total_loss / len(dataloader)


@torch.no_grad()
def validate(model, dataloader, criterion, device, epoch):
    model.eval()
    total_loss = 0.0
    pbar = tqdm(dataloader, desc=f"Epoch {epoch} [Val]")
    
    for images, input_ids, attn_masks, _ in pbar:
        images     = images.to(device)
        input_ids  = input_ids.to(device)
        attn_masks = attn_masks.to(device)

        with autocast():
            img_embeds, txt_embeds = model(images, input_ids, attn_masks)
            loss = criterion(img_embeds, txt_embeds)

        total_loss += loss.item()
        pbar.set_postfix({"Loss": f"{loss.item():.4f}"})

    if len(dataloader) == 0:
        return 0.0
    return total_loss / len(dataloader)


def main():
    os.makedirs(cfg.CHECKPOINT_DIR, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.backends.cudnn.benchmark = True
    print(f"[Setup] Device: {device}")
    print(f"[Setup] Data root: {cfg.FASHIONGEN_ROOT}")
    print(f"[Setup] Train CSV: {cfg.TRAIN_CSV} (exists: {os.path.exists(cfg.TRAIN_CSV)})")
    print(f"[Setup] Train images: {cfg.TRAIN_IMG_DIR} (exists: {os.path.exists(cfg.TRAIN_IMG_DIR)})")
    print(f"[Setup] Val CSV:   {cfg.VAL_CSV} (exists: {os.path.exists(cfg.VAL_CSV)})")
    print(f"[Setup] Val images: {cfg.VAL_IMG_DIR} (exists: {os.path.exists(cfg.VAL_IMG_DIR)})")
    
    # load data
    print(f"[Setup] Creating DataLoaders...")
    train_loader, val_loader = create_fashiongen_dataloaders(
        val_subset_size=2000,   # Fast early stopping: only 2000 val samples per epoch (~2min on T4)
    )
    print(f"        Train batches: {len(train_loader)} | Val batches: {len(val_loader)}")

    # load model and loss func
    print(f"[Setup] Initializing model ({cfg.CLIP_MODEL_NAME})...")
    model = MRL_CrossModal_Model(model_name=cfg.CLIP_MODEL_NAME).to(device)
    criterion = MRL_InfoNCE_HardNeg_Loss(
        nesting_list=cfg.NESTING_LIST, 
        temperature=cfg.TEMPERATURE, 
        hard_neg_ratio=cfg.HARD_NEG_RATIO
    ).to(device)

    # optimizer and scheduler
    optimizer = optim.AdamW(model.parameters(), lr=cfg.LR, weight_decay=cfg.WEIGHT_DECAY)
    
    grad_accum      = getattr(cfg, "GRAD_ACCUM", 1)
    eff_batch       = cfg.BATCH_SIZE * grad_accum
    steps_per_epoch = (len(train_loader) + grad_accum - 1) // grad_accum
    total_steps     = steps_per_epoch * cfg.NUM_EPOCHS
    warmup_steps    = steps_per_epoch * cfg.WARMUP_EPOCHS
    print(f"[Setup] Effective batch: {eff_batch} (batch={cfg.BATCH_SIZE} × accum={grad_accum})")
    print(f"        Steps/epoch: {steps_per_epoch} | Total: {total_steps} | Warmup: {warmup_steps}")

    scheduler = get_cosine_schedule_with_warmup(
        optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
    )
    
    scaler = GradScaler()
    early_stopper = EarlyStopping(patience=cfg.EARLY_STOP_PAT)

    # Resume Checkpoint Logic
    latest_ckpt_path = os.path.join(cfg.CHECKPOINT_DIR, "mrl_fashiongen_latest.pt")
    start_epoch = 1

    if os.path.exists(latest_ckpt_path):
        print(f"[Resume] Found latest checkpoint: {latest_ckpt_path}")
        checkpoint = torch.load(latest_ckpt_path, map_location=device)
        
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
        scaler.load_state_dict(checkpoint['scaler_state_dict'])
        
        start_epoch = checkpoint['epoch'] + 1
        early_stopper.best_loss = checkpoint['best_val_loss']
        early_stopper.counter = checkpoint['early_stop_counter']
        
        print(f"         -> Resuming from epoch {start_epoch}")
        print(f"         -> Current best val loss: {early_stopper.best_loss:.4f} (Early stop counter: {early_stopper.counter}/{early_stopper.patience})")
    else:
        print("[Start] No existing checkpoint found. Starting from scratch.")

    # training loop
    print("\n[Start] Beginning Training Loop")

    for epoch in range(start_epoch, cfg.NUM_EPOCHS + 1):
        train_loss = train_one_epoch(model, train_loader, optimizer, scheduler, criterion, scaler, device, epoch)
        val_loss = validate(model, val_loader, criterion, device, epoch)
        
        print(f"=== Epoch {epoch}/{cfg.NUM_EPOCHS} Summary ===")
        print(f"    Train Loss : {train_loss:.4f}")
        print(f"    Val Loss   : {val_loss:.4f}")

        # save latest checkpoint (for resuming)
        torch.save({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'scheduler_state_dict': scheduler.state_dict(),
            'scaler_state_dict': scaler.state_dict(),
            'best_val_loss': early_stopper.best_loss if val_loss >= early_stopper.best_loss else val_loss,
            'early_stop_counter': 0 if val_loss < early_stopper.best_loss - early_stopper.min_delta else early_stopper.counter + 1
        }, latest_ckpt_path)
        print(f"    -> [Saved] Latest state saved to {latest_ckpt_path}")

        # checkpoint and early stop (for best model)
        if val_loss < early_stopper.best_loss - early_stopper.min_delta:
            print(f"    -> [New Best] Saving BEST model to {cfg.BEST_CKPT}")
            torch.save(model.state_dict(), cfg.BEST_CKPT)
        
        early_stopper(val_loss)
        if early_stopper.early_stop:
            print(f"\n[Early Stop] Triggered at epoch {epoch}! No improvement for {cfg.EARLY_STOP_PAT} epochs.")
            break

    print("\n[Done] Training complete.")


if __name__ == "__main__":
    main()
