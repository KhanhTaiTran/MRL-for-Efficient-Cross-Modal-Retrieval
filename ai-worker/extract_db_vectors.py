import os
import json
import torch
import pandas as pd
import numpy as np
import faiss
from tqdm import tqdm
from PIL import Image
from torchvision import transforms
from transformers import AutoTokenizer

from model import MRL_CrossModal_Model

# =========== Config path ===========
DATA_EXCEL_PATH = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.xlsx"
IMG_DIR = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"
# Set CHECKPOINT_PATH to None if you want to use the original model
CHECKPOINT_PATH = "checkpoints/mrl_clip_epoch_3.pt" 
OUTPUT_DIR = "vector_db"
BATCH_SIZE = 64
MAX_LENGTH = 77
TOKENIZER_NAME = 'openai/clip-vit-base-patch32'
# ============================================

class FullFashionDataset(torch.utils.data.Dataset):
    def __init__(self, df, img_dir, transform, tokenizer):
        self.df = df.reset_index(drop=True)
        self.img_dir = img_dir
        self.transform = transform
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_name = str(row['image'])
        img_path = os.path.join(self.img_dir, img_name)
        
        try:
            image = Image.open(img_path).convert('RGB')
        except Exception:
            # Image error -> return white image
            image = Image.new('RGB', (224, 224), color='white')
            
        image = self.transform(image)
        
        # concatenate title and description to make a full caption
        title = str(row['display name']) if 'display name' in row and pd.notna(row['display name']) else ""
        desc = str(row['description']) if 'description' in row and pd.notna(row['description']) else ""
        text = f"{title}. {desc}".strip()
        if text == ".": text = ""
        
        tokens = self.tokenizer(
            text, 
            padding='max_length', 
            truncation=True, 
            max_length=MAX_LENGTH, 
            return_tensors='pt'
        )
        return image, tokens['input_ids'].squeeze(0), tokens['attention_mask'].squeeze(0), img_name, text

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"1. Loading data from {DATA_EXCEL_PATH}...")
    try:
        # If the file is xlsx
        df = pd.read_excel(DATA_EXCEL_PATH)
    except Exception as e:
        print(f"Could not read Excel file, trying to read CSV: {e}")
        df = pd.read_csv(DATA_EXCEL_PATH.replace('.xlsx', '.csv'), on_bad_lines='skip')
        
    # Filter out images that don't exist on disk
    existing_images = set(os.listdir(IMG_DIR))
    df = df[df['image'].isin(existing_images)]
    print(f"-> Total valid Image+Text: {len(df)}")
    
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
    img_transform = transforms.Compose([
        transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), std=(0.26862954, 0.26130258, 0.27577711))
    ])
    
    dataset = FullFashionDataset(df, IMG_DIR, img_transform, tokenizer)
    # Use num_workers=0 to avoid multiprocessing errors on Windows
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"-> Using device: {device}")
    model = MRL_CrossModal_Model().to(device)
    
    if os.path.exists(CHECKPOINT_PATH):
        print(f"\n2. Loading model from Checkpoint: {CHECKPOINT_PATH}")
        model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device))
    else:
        print(f"\n2. WARNING: {CHECKPOINT_PATH} not found, using original model (Zero-shot)!")
        
    model.eval()
    
    all_img_features = []
    all_txt_features = []
    image_paths_list = []
    captions_list = []
    
    print(f"\n3. Starting to extract vectors for {len(df)} items (this will take a while)...")
    with torch.no_grad():
        for images, input_ids, attention_masks, img_names, texts in tqdm(dataloader):
            images = images.to(device)
            input_ids = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            
            # Extract full 512-dim vectors
            img_embeds = model.extract_image_features(images)
            txt_embeds = model.extract_text_features(input_ids, attention_masks)
            
            all_img_features.append(img_embeds.cpu().numpy())
            all_txt_features.append(txt_embeds.cpu().numpy())
            
            image_paths_list.extend(img_names)
            captions_list.extend(texts)
            
    # Combine all vectors
    final_img_features = np.vstack(all_img_features).astype('float32')
    final_txt_features = np.vstack(all_txt_features).astype('float32')
    
    print(f"\n-> Image Vector Matrix Shape: {final_img_features.shape}")
    print(f"-> Text Vector Matrix Shape: {final_txt_features.shape}")
    
    print("\n4. Initializing FAISS Indices and storing...")
    # Normalize L2 before putting into FAISS IndexFlatIP (Cosine Similarity = Inner Product of L2 Normalized vectors)
    faiss.normalize_L2(final_img_features)
    faiss.normalize_L2(final_txt_features)
    
    dim = final_img_features.shape[1]
    
    # Create and save index for images
    img_index = faiss.IndexFlatIP(dim)
    img_index.add(final_img_features)
    faiss.write_index(img_index, os.path.join(OUTPUT_DIR, "image_embeddings.index"))
    
    # Create and save index for text (for Image-to-Text problem)
    txt_index = faiss.IndexFlatIP(dim)
    txt_index.add(final_txt_features)
    faiss.write_index(txt_index, os.path.join(OUTPUT_DIR, "text_embeddings.index"))
    
    print("5. Storing Metadata JSON...")
    # Save image metadata
    with open(os.path.join(OUTPUT_DIR, "image_paths.json"), "w", encoding="utf-8") as f:
        json.dump(image_paths_list, f, ensure_ascii=False, indent=4)
        
    # Save text metadata
    with open(os.path.join(OUTPUT_DIR, "captions.json"), "w", encoding="utf-8") as f:
        json.dump(captions_list, f, ensure_ascii=False, indent=4)
        
    print(f"\n PERFECT! Entire Database (Vector & Metadata) has been successfully saved in folder '{OUTPUT_DIR}'")

if __name__ == "__main__":
    main()
