"""
Usage:
    python extract_fashiongen_h5.py              # uses default paths
    python extract_fashiongen_h5.py --train_n 20000   # smaller train subset
"""

import argparse
import csv
import os
import random
import sys
import time

import h5py
import numpy as np
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
H5_ROOT   = r"D:\Pre-thesis\FashionGen"
OUT_ROOT  = os.path.join(H5_ROOT, "extracted")
TRAIN_H5  = os.path.join(H5_ROOT, "fashiongen_256_256_train.h5")
VAL_H5    = os.path.join(H5_ROOT, "fashiongen_256_256_validation.h5")

TRAIN_SUBSET = 30_000   # How many train images to sample
JPEG_QUALITY = 95       # High quality — CLIP is sensitive to compression
RANDOM_SEED  = 42
# ──────────────────────────────────────────────────────────────────────────────


def decode(val):
    """Decode byte-string fields from H5 into plain Python str."""
    if isinstance(val, (bytes, np.bytes_)):
        return val.decode("utf-8", errors="ignore").strip()
    if hasattr(val, "__iter__") and not isinstance(val, str):
        # Shape (1,) arrays
        inner = val[0] if len(val) == 1 else val
        if isinstance(inner, (bytes, np.bytes_)):
            return inner.decode("utf-8", errors="ignore").strip()
    return str(val).strip()


def build_text(name, description):
    """
    Combine product name + description into a single rich text query.
    This mirrors how FashionKLIP (ACL 2023) benchmarks text-to-image retrieval.
    """
    name = name.strip()
    desc = description.strip()
    if name and desc:
        return f"{name}. {desc}"
    return name or desc


def extract_split(h5_path, out_dir, indices=None, split_name="split"):
    """
    Read from h5_path, write JPEGs + metadata.csv.
    If indices is None → extract ALL rows.
    If indices is a list → extract only those row indices (train subset).
    """
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "metadata.csv")

    # Check if already extracted (resume support)
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            existing = sum(1 for _ in f) - 1  # minus header
        print(f"  [RESUME] Found existing {csv_path} with {existing} rows.")
        print(f"  Skipping — delete the folder to re-extract.")
        return existing

    print(f"\n{'='*60}")
    print(f"  Extracting: {split_name.upper()}")
    print(f"  H5 source : {h5_path}")
    print(f"  Output    : {out_dir}")
    print(f"  Images    : {len(indices) if indices is not None else 'ALL'}")
    print(f"{'='*60}")

    count = 0
    skipped = 0
    t0 = time.time()

    with h5py.File(h5_path, "r") as f:
        total_rows = f["input_image"].shape[0]
        if indices is None:
            indices = list(range(total_rows))

        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=["image_path", "text", "product_id", "category", "subcategory"]
            )
            writer.writeheader()

            for i, row_idx in enumerate(indices):
                # ── Progress ───────────────────────────────────────────────
                if i % 500 == 0 and i > 0:
                    elapsed = time.time() - t0
                    rate    = i / elapsed
                    eta     = (len(indices) - i) / rate
                    print(
                        f"  [{i:>6}/{len(indices)}] "
                        f"rate={rate:.0f} imgs/s  "
                        f"ETA={eta/60:.1f}min",
                        end="\r"
                    )

                # ── Read image ─────────────────────────────────────────────
                img_np = f["input_image"][row_idx]          # uint8 (256,256,3)
                img    = Image.fromarray(img_np, mode="RGB")

                # ── Read metadata ──────────────────────────────────────────
                product_id  = decode(f["input_productID"][row_idx])
                name        = decode(f["input_name"][row_idx])
                description = decode(f["input_description"][row_idx])
                category    = decode(f["input_category"][row_idx])
                subcategory = decode(f["input_subcategory"][row_idx])
                text        = build_text(name, description)

                if not text:
                    skipped += 1
                    continue

                # ── Save JPEG ──────────────────────────────────────────────
                filename   = f"{row_idx:07d}.jpg"
                jpg_path   = os.path.join(img_dir, filename)
                rel_path   = os.path.join("images", filename)   # relative to out_dir
                img.save(jpg_path, format="JPEG", quality=JPEG_QUALITY)

                writer.writerow({
                    "image_path" : rel_path,
                    "text"       : text,
                    "product_id" : product_id,
                    "category"   : category,
                    "subcategory": subcategory,
                })
                count += 1

    elapsed = time.time() - t0
    print(f"\n  [OK] Done! {count:,} images saved in {elapsed/60:.1f} min  ({skipped} skipped / no text)")
    return count


def main():
    parser = argparse.ArgumentParser(description="Extract FashionGen H5 → JPEG + CSV")
    parser.add_argument("--h5_root",    default=H5_ROOT,        help="Folder containing .h5 files")
    parser.add_argument("--out_root",   default=OUT_ROOT,        help="Output root folder")
    parser.add_argument("--train_n",    type=int, default=TRAIN_SUBSET, help="# train images to sample")
    parser.add_argument("--seed",       type=int, default=RANDOM_SEED)
    parser.add_argument("--skip_train", action="store_true",    help="Skip train extraction (only do val)")
    parser.add_argument("--skip_val",   action="store_true",    help="Skip val extraction (only do train)")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    train_h5 = os.path.join(args.h5_root, "fashiongen_256_256_train.h5")
    val_h5   = os.path.join(args.h5_root, "fashiongen_256_256_validation.h5")
    train_dir = os.path.join(args.out_root, "train")
    val_dir   = os.path.join(args.out_root, "val")

    # ── Validation split — extract ALL (32,528 images = official benchmark) ──
    if not args.skip_val:
        extract_split(val_h5, val_dir, indices=None, split_name="validation")

    # ── Train split — random subset ──────────────────────────────────────────
    if not args.skip_train:
        with h5py.File(train_h5, "r") as f:
            total_train = f["input_image"].shape[0]
        n = min(args.train_n, total_train)
        train_indices = sorted(random.sample(range(total_train), n))
        print(f"\n  Sampled {n:,} / {total_train:,} train indices (seed={args.seed})")
        extract_split(train_h5, train_dir, indices=train_indices, split_name="train")

    print("\n" + "="*60)
    print("  Phase 0 complete!")
    print(f"  Output at: {args.out_root}")
    print("  Next step: run dataset_fashiongen.py to verify dataloaders")
    print("="*60)


if __name__ == "__main__":
    main()
