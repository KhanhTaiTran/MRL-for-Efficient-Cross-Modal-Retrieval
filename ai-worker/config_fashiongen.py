import os

FASHIONGEN_ROOT = r"D:\Pre-thesis\FashionGen\extracted"

TRAIN_DIR = os.path.join(FASHIONGEN_ROOT, "train")
TRAIN_CSV = os.path.join(TRAIN_DIR, "metadata.csv")
TRAIN_IMG_DIR = os.path.join(TRAIN_DIR, "images")

VAL_DIR = os.path.join(FASHIONGEN_ROOT, "val")
VAL_CSV = os.path.join(VAL_DIR, "metadata.csv")
VAL_IMG_DIR = os.path.join(VAL_DIR, "images")

CLIP_MODEL_NAME = "openai/clip-vit-base-patch32" # CLIP ViT-B/32 
MAX_LENGTH = 77                           # CLIP token limit
IMAGE_SIZE = 224                          # CLIP input resolution
NESTING_LIST = [16, 32, 64, 128, 256, 512]  # MRL dimensions to train
FULL_DIM = 512                          # max embedding dim

# copy from train_v3.py
BATCH_SIZE = 64
LR = 3e-6
WEIGHT_DECAY = 1e-4
TEMPERATURE = 0.05
HARD_NEG_RATIO = 0.3
NUM_EPOCHS = 10
WARMUP_EPOCHS = 1
EARLY_STOP_PAT = 3           # patience (epochs without val improvement)
GRAD_CLIP = 0.5
NUM_WORKERS = 2           # DataLoader workers

# output paths
CHECKPOINT_DIR = "checkpoints"
BEST_CKPT = os.path.join(CHECKPOINT_DIR, "mrl_fashiongen_best.pt")

EMBEDDING_DIR = "embeddings"
VAL_IMG_FEATS = os.path.join(EMBEDDING_DIR, "fgen_val_image_features.pt")
VAL_TXT_FEATS = os.path.join(EMBEDDING_DIR, "fgen_val_text_features.pt")
VAL_PRODUCT_IDS = os.path.join(EMBEDDING_DIR, "fgen_val_product_ids.json")