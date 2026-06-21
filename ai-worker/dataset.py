import os
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
from sklearn.model_selection import train_test_split

class FashionCrossModalDataset(Dataset):
    def __init__(self, df, img_dir, transform=None, tokenizer=None, max_length=77):
        """
        Args:
            df (pandas.DataFrame): DataFrame containing the filtered data.
            img_dir (str): Path to the directory containing images.
            transform (callable, optional): Optional transform to be applied on a sample.
            tokenizer (callable, optional): Tokenizer to encode text.
            max_length (int): Maximum token length.
        """
        self.df = df.reset_index(drop=True)
        self.img_dir = img_dir
        self.transform = transform
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_name = row['image']
        img_path = os.path.join(self.img_dir, img_name)
        
        # Load image
        try:
            image = Image.open(img_path).convert('RGB')
        except Exception as e:
            # Fallback if image is somehow corrupted
            image = Image.new('RGB', (224, 224), color='white')
            
        if self.transform:
            image = self.transform(image)
            
        # Combine 'display name' and 'description'
        title = str(row['display name']) if pd.notna(row['display name']) else ""
        desc = str(row['description']) if pd.notna(row['description']) else ""
        
        # We can use title + description as the text query
        text = f"{title}. {desc}"
        
        if self.tokenizer:
            # Tokenize text using HuggingFace tokenizer
            tokens = self.tokenizer(
                text, 
                padding='max_length', 
                truncation=True, 
                max_length=self.max_length, 
                return_tensors='pt'
            )
            # Squeeze to remove the batch dimension added by tokenizer
            input_ids = tokens['input_ids'].squeeze(0)
            attention_mask = tokens['attention_mask'].squeeze(0)
            return image, input_ids, attention_mask
        else:
            return image, text

def create_dataloaders(
    csv_file=r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.csv",
    img_dir=r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images",
    batch_size=64,
    num_workers=4,
    tokenizer_name='openai/clip-vit-base-patch32'
):
    print("1. Loading metadata CSV...")
    # Load CSV, ignoring bad lines
    df = pd.read_csv(csv_file, on_bad_lines='skip')
    print(f"-> Total rows in raw CSV: {len(df)}")
    
    print("2. Filtering out rows where images don't exist...")
    # List all available images once to speed up filtering
    existing_images = set(os.listdir(img_dir))
    df = df[df['image'].isin(existing_images)]
    print(f"-> Valid pairs (Image + Text) after filtering: {len(df)}")
    
    print(f"3. Loading tokenizer ({tokenizer_name})...")
    from transformers import AutoTokenizer
    try:
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    except Exception as e:
        print(f"Warning: Could not load tokenizer: {e}. Dataset will return raw text.")
        tokenizer = None
        
    print("4. Defining Image Transforms (Resize, CenterCrop, Normalize)...")
    # Standard CLIP image preprocessing transforms
    img_transform = transforms.Compose([
        transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), 
                             std=(0.26862954, 0.26130258, 0.27577711))
    ])
    
    print("5. Splitting Dataset (Train 80% / Val 10% / Test 10%)...")
    train_df, temp_df = train_test_split(df, test_size=0.2, random_state=42)
    val_df, test_df = train_test_split(temp_df, test_size=0.5, random_state=42)
    
    print(f"-> Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")
    
    # Create PyTorch Datasets
    train_dataset = FashionCrossModalDataset(train_df, img_dir, img_transform, tokenizer)
    val_dataset = FashionCrossModalDataset(val_df, img_dir, img_transform, tokenizer)
    test_dataset = FashionCrossModalDataset(test_df, img_dir, img_transform, tokenizer)
    
    # Create DataLoaders
    # Note: num_workers>0 on Windows sometimes causes issues, set to 0 for fallback
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)
    
    return train_loader, val_loader, test_loader, df

if __name__ == "__main__":
    # Test script to verify things work
    print("=== TESTING DATASET AND DATALOADER ===")
    try:
        # Using num_workers=0 to avoid multiprocessing issues on Windows during simple test
        train_loader, val_loader, test_loader, _ = create_dataloaders(batch_size=16, num_workers=0)
        
        # Fetch one batch
        print("\nFetching a single batch from Train Loader...")
        for images, input_ids, attention_masks in train_loader:
            print(f"-> Images batch shape: {images.shape} (Batch, Channels, Height, Width)")
            print(f"-> Input IDs batch shape: {input_ids.shape} (Batch, MaxTokens)")
            print(f"-> Attention Mask batch shape: {attention_masks.shape}")
            break
        print("\nSUCCESS: Dataloader is working perfectly!")
    except ImportError as e:
        print(f"Missing dependency. Please run: pip install pandas scikit-learn transformers torch torchvision")
        print(f"Error: {e}")
