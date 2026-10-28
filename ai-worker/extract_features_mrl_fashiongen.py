import argparse
import json
import os
import time

import torch

import config_fashiongen as cfg
from dataset_fashiongen import create_fashiongen_dataloaders
from model import MRL_CrossModal_Model

MRL_IMG_FEATS   = os.path.join(cfg.EMBEDDING_DIR, "fgen_val_mrl_image_features.pt") 
MRL_TXT_FEATS   = os.path.join(cfg.EMBEDDING_DIR, "fgen_val_mrl_text_features.pt")
MRL_PRODUCT_IDS = os.path.join(cfg.EMBEDDING_DIR, "fgen_val_product_ids.json")  # shared

def load_model(checkpoint_path: str, device: str) -> MRL_CrossModal_Model:
    model = MRL_CrossModal_Model(model_name=cfg.CLIP_MODEL_NAME).to(device)

    if checkpoint_path and os.path.exists(checkpoint_path):
        state = torch.load(checkpoint_path, map_location=device)
        model.load_state_dict(state)
        print(f"-> Loaded fine-tuned weights: {checkpoint_path}")
    else:
        raise FileNotFoundError(
            f"Checkpoint not found: '{checkpoint_path}'\n"
            f"Please copy mrl_fashiongen_best.pt from Drive/Colab to "
            f"ai-worker/checkpoints/ on your laptop."
        )

    model.eval()
    return model

def extract_and_save(checkpoint_path: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nDevice: {device}")
    
    batch_size = 128 if device == "cuda" else 32
    num_workers = 2 if device == "cuda" else 0   # 0 on Windows laptop to avoid PicklingError
    
    print("Loading trained MRL model...")
    model = load_model(checkpoint_path, device)

    print("Building val DataLoader...")
    _, val_loader = create_fashiongen_dataloaders(
        batch_size  = batch_size,
        num_workers = num_workers,
    )
    n_items = len(val_loader.dataset)  # type: ignore
    print(f"    -> Val items: {n_items:,} | Batches: {len(val_loader)}")

    print(f"\nExtracting 512-dim MRL features for {n_items:,} val items...")
    all_img_feats  = []
    all_txt_feats  = []
    all_product_ids = []

    t0 = time.perf_counter()

    with torch.no_grad():
        for batch_idx, (images, input_ids, attn_masks, product_ids) in enumerate(val_loader):
            images     = images.to(device)
            input_ids  = input_ids.to(device)
            attn_masks = attn_masks.to(device)

            img_feats = model.extract_image_features(images)
            txt_feats = model.extract_text_features(input_ids, attn_masks)

            all_img_feats.append(img_feats.cpu())
            all_txt_feats.append(txt_feats.cpu())
            all_product_ids.extend(product_ids)

            # Progress
            if (batch_idx + 1) % 10 == 0 or (batch_idx + 1) == len(val_loader):
                done    = min((batch_idx + 1) * batch_size, n_items)
                pct     = done / n_items * 100
                elapsed = time.perf_counter() - t0
                eta     = elapsed / (batch_idx + 1) * (len(val_loader) - batch_idx - 1)
                print(f"    [{done:>6}/{n_items}] {pct:5.1f}%  "
                      f"elapsed={elapsed/60:.1f}min  ETA={eta/60:.1f}min", end="\r")

    print()
    
    final_img = torch.cat(all_img_feats, dim=0)   # [N, 512]
    final_txt = torch.cat(all_txt_feats, dim=0)   # [N, 512]

    elapsed = time.perf_counter() - t0
    print(f"\nExtraction complete in {elapsed/60:.1f} min")
    print(f"Image features : {tuple(final_img.shape)}")
    print(f"Text  features : {tuple(final_txt.shape)}")
    print(f"Product IDs    : {len(all_product_ids):,}")

    os.makedirs(cfg.EMBEDDING_DIR, exist_ok=True)
    torch.save(final_img, MRL_IMG_FEATS)
    torch.save(final_txt, MRL_TXT_FEATS)

    # Save product_ids only if not already present (same as zero-shot)
    if not os.path.exists(MRL_PRODUCT_IDS):
        with open(MRL_PRODUCT_IDS, "w", encoding="utf-8") as f:
            json.dump(all_product_ids, f)
        print(f"-> Saved product IDs to {MRL_PRODUCT_IDS}")
    else:
        print(f"-> Product IDs already exist, skipping.")

    print(f"\n[6] Saved MRL embeddings to '{cfg.EMBEDDING_DIR}/':")
    print(f"{os.path.basename(MRL_IMG_FEATS)}")
    print(f"{os.path.basename(MRL_TXT_FEATS)}")
    print(f"\nNext step: run benchmark_fashiongen.py --emb_prefix mrl to compare vs zero-shot.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", type=str, required=True,
        help="Path to trained MRL checkpoint (mrl_fashiongen_best.pt)."
    )
    args = parser.parse_args()
    extract_and_save(args.checkpoint)
