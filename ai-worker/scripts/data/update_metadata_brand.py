import os
import shutil
import h5py
import numpy as np
import pandas as pd

H5_ROOT = r"D:\Pre-thesis\FashionGen"
EXTRACTED_ROOT = os.path.join(H5_ROOT, "extracted")

TRAIN_H5 = os.path.join(H5_ROOT, "fashiongen_256_256_train.h5")
VAL_H5 = os.path.join(H5_ROOT, "fashiongen_256_256_validation.h5")

TRAIN_CSV = os.path.join(EXTRACTED_ROOT, "train", "metadata.csv")
VAL_CSV = os.path.join(EXTRACTED_ROOT, "val", "metadata.csv")


def decode(val) -> str:
    """Decode byte-string fields from H5 into plain Python str."""
    if isinstance(val, (bytes, np.bytes_)):
        return val.decode("utf-8", errors="ignore").strip()
    if hasattr(val, "__iter__") and not isinstance(val, str):
        inner = val[0] if len(val) == 1 else val
        if isinstance(inner, (bytes, np.bytes_)):
            return inner.decode("utf-8", errors="ignore").strip()
    return str(val).strip()


def build_text(brand: str, description: str) -> str:
    brand = brand.strip()
    desc = description.strip()
    if brand and desc:
        return f"{brand}. {desc}"
    return desc or brand


def update_split(csv_path: str, h5_path: str, split_name: str):
    if not os.path.exists(csv_path):
        print(f"[-] {csv_path} does not exist, skipping.")
        return
    if not os.path.exists(h5_path):
        print(f"[-] {h5_path} does not exist, skipping.")
        return

    print(f"\n[+] Processing {split_name.upper()} split...")
    # Backup original CSV if not already backed up
    bak_path = csv_path + ".bak"
    if not os.path.exists(bak_path):
        shutil.copyfile(csv_path, bak_path)
        print(f"    Created backup: {bak_path}")

    df = pd.read_csv(csv_path, dtype=str)
    print(f"    Loaded {len(df):,} rows from {csv_path}")

    # Extract H5 row indices from image filename (e.g., 'images/0000002.jpg' -> 2)
    def get_row_idx(path_str):
        base = os.path.basename(path_str)
        name, _ = os.path.splitext(base)
        return int(name)

    row_indices = df["image_path"].apply(get_row_idx).tolist()

    with h5py.File(h5_path, "r") as h5:
        brand_ds = h5["input_brand"]
        desc_ds = h5["input_description"]

        new_texts = []
        new_brands = []

        total = len(row_indices)
        for i, idx in enumerate(row_indices):
            if i % 5000 == 0 and i > 0:
                print(f"    Processed {i:,} / {total:,} rows...", flush=True)

            raw_brand = brand_ds[idx]
            raw_desc = desc_ds[idx]

            brand_str = decode(raw_brand)
            desc_str = decode(raw_desc)

            combined_text = build_text(brand_str, desc_str)

            new_texts.append(combined_text)
            new_brands.append(brand_str)

    df["text"] = new_texts
    df["brand"] = new_brands

    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"[OK] {split_name.upper()} updated successfully -> {csv_path}")
    print(f"    Sample row 0:")
    print(f"      brand: {df.iloc[0]['brand']}")
    print(f"      text : {df.iloc[0]['text'][:100]}...")


def main():
    print("=" * 60)
    print("FashionGen Metadata Brand + Description Updater")
    print("=" * 60)

    update_split(TRAIN_CSV, TRAIN_H5, "train")
    update_split(VAL_CSV, VAL_H5, "validation")

    print("\n[Done] All metadata CSVs updated with Brand + Description.")


if __name__ == "__main__":
    main()
