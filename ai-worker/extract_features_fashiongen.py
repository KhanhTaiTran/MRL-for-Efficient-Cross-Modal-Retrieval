"""
extract_features_fashiongen.py — Phase 3: Feature Extraction for FashionGen.

Runs the MRL CLIP model over the full FashionGen validation set (32,528 items),
saves 512-dim image + text embeddings to disk.

The benchmark script (Phase 4) then slices these 512-dim vectors down to any
MRL sub-dimension [16, 32, 64, 128, 256, 512] without re-running the model.

Supports two modes:
  - Zero-shot : no checkpoint argument, uses raw pretrained CLIP weights.
  - Fine-tuned: pass --checkpoint path/to/mrl_fashiongen_best.pt

Usage:
  python extract_features_fashiongen.py                           # zero-shot
  python extract_features_fashiongen.py --checkpoint checkpoints/mrl_fashiongen_best.pt
"""

import argparse
import json
import os
import time

import torch

import config_fashiongen as cfg
from dataset_fashiongen import create_fashiongen_dataloaders
from model import MRL_CrossModal_Model

# helper function to load model 
def load_model(checkpoint_path: str | None, device: str) -> MRL_CrossModal_Model: #the output expected is a MRL_CrossModal_Model
    model = MRL_CrossModal_Model().to(device)

    if checkpoint_path and os.path.exists(checkpoint_path):
        model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        print(f"    -> Loaded fine-tuned weights: {checkpoint_path}")
    else:
        if checkpoint_path:
            print(f"    -> WARNING: checkpoint not found at '{checkpoint_path}'.")
        print(f"    -> Using zero-shot CLIP weights (openai/clip-vit-base-patch32).")

    model.eval()
    return model

# main extraction function
def extract_and_save(checkpoint_path: str | None = None):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nDevice: {device}")

    # load model (zero-shot or fine-tuned)
    print("Loading model...")
    model = load_model(checkpoint_path, device)

    print("Building val DataLoader...")
    _, val_loader = create_fashiongen_dataloaders(
        batch_size = 128,   # larger = faster on GPU; safe for 4GB VRAM #TODO: check if this too large
        num_workers = 2,
    )
    n_items = len(val_loader.dataset)  # type: ignore
    print(f" -> Val items: {n_items:,} | Batches: {len(val_loader)}")

    print(f"\nExtracting 512-dim features for {n_items:,} val items...")
    all_img_feats = []
    all_txt_feats = []
    all_product_ids = []

    t0 = time.perf_counter() # start timer

    with torch.no_grad():
        for batch_idx, (images, input_ids, attn_masks, product_ids) in enumerate(val_loader): #loop through all the img in the batch
            images     = images.to(device)
            input_ids  = input_ids.to(device)
            attn_masks = attn_masks.to(device)

            img_feats = model.extract_image_features(images)        # [B, 512] full dims
            txt_feats = model.extract_text_features(input_ids, attn_masks)  # [B, 512]

            all_img_feats.append(img_feats.cpu())
            all_txt_feats.append(txt_feats.cpu())
            all_product_ids.extend(product_ids)

            #batch_size = val_loader.batch_size or 1
            #n_batches = len(val_loader)

            # Progress
            if (batch_idx + 1) % 20 == 0 or (batch_idx + 1) == len(val_loader):
                done = min((batch_idx + 1) * val_loader.batch_size, len(val_loader.dataset))  # type: ignore
                pct = done / n_items * 100
                elapsed = time.perf_counter() - t0
                eta = elapsed / (batch_idx + 1) * (len(val_loader) - batch_idx - 1)
                print(f" [{done:>6}/{n_items}] {pct:5.1f}%  "
                      f"elapsed={elapsed/60:.1f}min  ETA={eta/60:.1f}min", end="\r")

    print()  # newline after progress

    # concanate all batches into single tensors
    final_img = torch.cat(all_img_feats, dim=0)   # [N, 512]
    final_txt = torch.cat(all_txt_feats, dim=0)   # [N, 512]

    elapsed = time.perf_counter() - t0
    print(f"\nExtraction complete in {elapsed/60:.1f} min")
    print(f"    Image features : {tuple(final_img.shape)}")
    print(f"    Text  features : {tuple(final_txt.shape)}")
    print(f"    Product IDs    : {len(all_product_ids):,}")

    os.makedirs(cfg.EMBEDDING_DIR, exist_ok=True)

    torch.save(final_img, cfg.VAL_IMG_FEATS)
    torch.save(final_txt, cfg.VAL_TXT_FEATS)
    with open(cfg.VAL_PRODUCT_IDS, "w", encoding="utf-8") as f:
        json.dump(all_product_ids, f)

    print(f"\nSaved to '{cfg.EMBEDDING_DIR}/':")
    print(f"{os.path.basename(cfg.VAL_IMG_FEATS)}")
    print(f"{os.path.basename(cfg.VAL_TXT_FEATS)}")
    print(f"{os.path.basename(cfg.VAL_PRODUCT_IDS)}")
    print("\nNext step: run benchmark_fashiongen.py to compute Recall@K")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", type=str, default=None,
        help="Path to fine-tuned checkpoint. Omit for zero-shot."
    )
    args = parser.parse_args()
    extract_and_save(checkpoint_path=args.checkpoint)
