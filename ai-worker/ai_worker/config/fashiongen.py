import os

# Auto-detect root directory (Colab local SSD > Colab Drive > Windows local)
if os.path.exists("/content/data/train"):
    FASHIONGEN_ROOT = "/content/data"
elif os.path.exists("/content/drive/MyDrive/FashionGen/train"):
    FASHIONGEN_ROOT = "/content/drive/MyDrive/FashionGen" 
else:
    FASHIONGEN_ROOT = os.environ.get("FASHIONGEN_ROOT", r"D:\Pre-thesis\FashionGen\extracted")

# Train paths (prefer local SSD if available)
TRAIN_DIR = "/content/data/train" if os.path.exists("/content/data/train/images") else os.path.join(FASHIONGEN_ROOT, "train")
TRAIN_CSV = os.path.join(TRAIN_DIR, "metadata.csv")
TRAIN_IMG_DIR = os.path.join(TRAIN_DIR, "images")

# Val paths (prefer local SSD if has images, otherwise fallback to Google Drive directly)
if os.path.exists("/content/data/val/images") and len(os.listdir("/content/data/val/images")) > 0:
    VAL_DIR = "/content/data/val"
elif os.path.exists("/content/drive/MyDrive/FashionGen/val/images"):
    VAL_DIR = "/content/drive/MyDrive/FashionGen/val"
else:
    VAL_DIR = os.path.join(FASHIONGEN_ROOT, "val")

VAL_CSV = os.path.join(VAL_DIR, "metadata.csv")
VAL_IMG_DIR = os.path.join(VAL_DIR, "images")

CLIP_MODEL_NAME = "openai/clip-vit-base-patch16"    # CLIP ViT-B/16
MAX_LENGTH = 77                                     # CLIP token limit
IMAGE_SIZE = 224                                    
NESTING_LIST = [16, 32, 64, 128, 256, 512]          
FULL_DIM = 512                                     

# params
BATCH_SIZE = 64      
GRAD_ACCUM = 2          # effective batch size = 64 * 2 = 128
LR = 5e-5               # EI-CLIP paper baseline LR for fine-tuning
WEIGHT_DECAY = 1e-4
TEMPERATURE = 0.05
HARD_NEG_RATIO = 0.5     
NUM_EPOCHS = 20        
WARMUP_EPOCHS = 2       
EARLY_STOP_PAT = 5      # stop training if val loss doesn't improve for 5 epochs
GRAD_CLIP = 1.0         # gradient clipping
NUM_WORKERS    = 2       

# output paths
CHECKPOINT_DIR = "checkpoints"
BEST_CKPT = os.path.join(CHECKPOINT_DIR, "mrl_fashiongen_best.pt")

EMBEDDING_DIR = "embeddings"
VAL_IMG_FEATS = os.path.join(EMBEDDING_DIR, "fgen_val_image_features.pt")
VAL_TXT_FEATS = os.path.join(EMBEDDING_DIR, "fgen_val_text_features.pt")
VAL_PRODUCT_IDS = os.path.join(EMBEDDING_DIR, "fgen_val_product_ids.json")