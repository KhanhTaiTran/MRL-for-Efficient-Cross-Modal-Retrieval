import ast
import os
from typing import List, Optional, Tuple

import pandas as pd
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from transformers import AutoTokenizer

import config_fashiongen as cfg

# helpers function for cleaning product_id and loading CSV
def _clean_product_id(raw: str) -> str:
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip() #s[start : end]; mean that start from index 1 to end-1, and remove the first and last character
    return s

# load CSV and filter out rows with missing text or missing image files
def _load_csv(csv_path: str, img_root: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"[ERROR] Metadata CSV not found at: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str)
    df["product_id"] = df["product_id"].apply(_clean_product_id)
    df["abs_path"]   = df["image_path"].apply(
        lambda p: os.path.join(img_root, str(p).replace("\\", "/").split("/")[-1])
    )
    # filter rows without text
    df = df[df["text"].notna() & (df["text"].str.strip() != "")].copy()
    
    # filter rows whose image file doesn't exist
    exists_mask = df["abs_path"].apply(os.path.exists)
    n_found = exists_mask.sum()
    if n_found == 0:
        sample_path = df["abs_path"].iloc[0] if len(df) > 0 else "N/A"
        raise FileNotFoundError(
            f"\n[ERROR] 0/{len(df)} images found in '{img_root}'!\n"
            f"Checking path: {sample_path}\n"
            f"Please verify that images were extracted to the correct folder."
        )
    df = df[exists_mask].copy().reset_index(drop=True)
    return df

# preprocess image for CLIP ViT-B/32
def clip_transform(image_size: int = cfg.IMAGE_SIZE) -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(image_size, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(), # convert PIL image to tensor, value range [0, 1]
        transforms.Normalize(
            mean=(0.48145466, 0.4578275,  0.40821073), # meann and std are from CLIP paper
            std =(0.26862954, 0.26130258, 0.27577711),
        ), 
    ])

class FashionGenDataset(Dataset):
    """
    Returns per-item tuples:
        image_tensor  : FloatTensor [3, 224, 224]
        input_ids     : LongTensor  [max_length]
        attention_mask: LongTensor  [max_length]
        product_id    : str  (needed for grouped recall on val set)
    """

    def __init__(
        self,
        csv_path   : str,
        img_root   : str,
        tokenizer,
        transform  = None,
        max_length : int = cfg.MAX_LENGTH,
    ):
        self.df = _load_csv(csv_path, img_root)
        self.tokenizer = tokenizer
        self.transform = transform or clip_transform()
        self.max_length = max_length

    def __len__(self) -> int: # return the number of rows in the dataframe
        return len(self.df)

    def __getitem__(self, idx: int): # return a tuple data for the given index
        row = self.df.iloc[idx]

        # img
        img = Image.open(row["abs_path"]).convert("RGB")
        img_tensor = self.transform(img)

        # convert text to tokenID that model can understand
        tokens = self.tokenizer( 
            row["text"],
            padding = "max_length",
            truncation = True, # truncate the text if it > max_length
            max_length = self.max_length,
            return_tensors="pt",
        )
        input_ids = tokens["input_ids"].squeeze(0)       # squeeze(0): [1,max_length] -> remove the batch dimension -> [max_length]
        attention_mask = tokens["attention_mask"].squeeze(0)  # [max_length]

        return img_tensor, input_ids, attention_mask, row["product_id"]

def _collate_fn(batch):
    imgs, ids, masks, pids = zip(*batch)
    return (
        torch.stack(imgs),
        torch.stack(ids),
        torch.stack(masks),
        list(pids),
    )

# dataloaders for training and validation
def create_fashiongen_dataloaders(
    batch_size      : int = cfg.BATCH_SIZE,
    num_workers     : int = cfg.NUM_WORKERS,
    val_batch       : int = 128,
    val_subset_size : int = 0,    # 0 = use full val set; >0 = random subset for fast early stopping
) -> Tuple[DataLoader, DataLoader]:
    tokenizer = AutoTokenizer.from_pretrained(cfg.CLIP_MODEL_NAME)
    transform = clip_transform()

    train_ds = FashionGenDataset(
        csv_path  =cfg.TRAIN_CSV,
        img_root  =cfg.TRAIN_IMG_DIR,
        tokenizer =tokenizer,
        transform =transform,
    )
    
    val_ds = FashionGenDataset(
        csv_path  =cfg.VAL_CSV,
        img_root  =cfg.VAL_IMG_DIR,
        tokenizer =tokenizer,
        transform =transform,
    )

    # Optionally limit val set to a fast subset for early stopping
    if val_subset_size > 0 and val_subset_size < len(val_ds):
        import random
        indices = random.sample(range(len(val_ds)), val_subset_size)
        val_ds = torch.utils.data.Subset(val_ds, indices)
        print(f"    [Val] Using fast subset: {val_subset_size:,} / {len(val_ds.dataset):,} samples")  # type: ignore

    train_loader = DataLoader(
        train_ds,
        batch_size  =batch_size,
        shuffle     =True,
        num_workers =num_workers,
        drop_last   =True,
        pin_memory  =True,
        collate_fn  =_collate_fn,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size  =val_batch,
        shuffle     =False,
        num_workers =num_workers,
        drop_last   =False,
        pin_memory  =True,
        collate_fn  =_collate_fn,
    )

    return train_loader, val_loader

# smoke test
if __name__ == "__main__":
    print("Loading tokenizer …")
    tokenizer = AutoTokenizer.from_pretrained(cfg.CLIP_MODEL_NAME)
    print("Loading datasets …")
    print("\n[TRAIN]")
    train_ds = FashionGenDataset(cfg.TRAIN_CSV, cfg.TRAIN_IMG_DIR, tokenizer)
    print(f"  Rows: {len(train_ds):,}")
    img, ids, mask, pid = train_ds[0]
    img = torch.as_tensor(img)   # convert PIL image to tensor
    print(f"  img shape : {img.shape}")
    print(f"  ids shape : {ids.shape}")
    print(f"  product_id: {pid}")

    print("\n[VAL]")
    val_ds = FashionGenDataset(cfg.VAL_CSV, cfg.VAL_IMG_DIR, tokenizer)
    print(f"  Rows: {len(val_ds):,}")
    n_products = val_ds.df["product_id"].nunique()
    print(f"  Unique products: {n_products:,}")

    print("\n[DATALOADER] Fetching first batch …")
    train_loader, val_loader = create_fashiongen_dataloaders(batch_size=8, num_workers=0)
    imgs, ids, masks, pids = next(iter(train_loader))
    print(f"  imgs  : {imgs.shape}")
    print(f"  ids   : {ids.shape}")
    print(f"  pids  : {pids[:4]}")
    print("\nAll OK — dataset_fashiongen.py is ready.")
