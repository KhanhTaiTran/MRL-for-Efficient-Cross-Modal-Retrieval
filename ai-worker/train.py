import torch
import torch.optim as optim
from tqdm import tqdm
import os

from dataset import create_dataloaders
from model import MRL_CrossModal_Model
from loss import Matryoshka_InfoNCE_Loss

# =========== CONFIG DATASET PATH AUTOMATICALLY ===========
if os.path.exists('/content'):
    # Running on Google Colab
    print("[System] Running on Google Colab...")
    DATA_CSV = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data.csv"
    DATA_IMG = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data_images"
else:
    # Running on Local machine
    print("[System] Running on Local machine...")
    DATA_CSV = r"D:\Pre-thesis\Thesis Dataset-202620617T002927Z-3-002\Thesis Dataset\data.csv"
    DATA_IMG = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"
# ===================================================

def train():
    print("=== MRL FINE-TUNING PIPELINE ===")
    
    # 1. Initialize DataLoaders
    train_loader, val_loader, _, _ = create_dataloaders(
        csv_file=DATA_CSV,
        img_dir=DATA_IMG,
        batch_size=32, 
        num_workers=2 # Colab usually has 2 CPU cores
    )
    
    # 2. Initialize Model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nUsing Device: {device}")
    model = MRL_CrossModal_Model().to(device)
    
    # 3. Initialize MRL Loss and Optimizer
    # We force the model to learn to compress information into these milestones [16, 32, 64, 128, 256, 512]
    # (Because CLIP ViT-Base has a maximum of 512 dimensions)
    criterion = Matryoshka_InfoNCE_Loss(nesting_list=[16, 32, 64, 128, 256, 512])
    
    # Fine-tuning CLIP requires a very small Learning Rate (lr) to avoid destroying previously learned knowledge
    optimizer = optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)
    
    # 4. Training Loop
    num_epochs = 3 # Example demo train 3 epochs
    os.makedirs("checkpoints", exist_ok=True)
    
    for epoch in range(num_epochs):
        model.train()
        total_loss = 0.0
        
        # tqdm shows processing bar
        loop = tqdm(train_loader, desc=f"Epoch [{epoch+1}/{num_epochs}]")
        
        for batch_idx, (images, input_ids, attention_masks) in enumerate(loop):
            # Moving data to GPU
            images = images.to(device)
            input_ids = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            
            # Clear old gradient
            optimizer.zero_grad()
            
            # Forward: Let image and text run through the model (Will return 2 vectors of 512 dimensions)
            img_embeds, txt_embeds = model(images, input_ids, attention_masks)
            
            # Calculate Loss: PUT INTO MRL LOSS FUNCTION TO AUTOMATICALLY CUT AND CALCULATE SCORES AT MULTIPLE RESOLUTIONS
            loss = criterion(img_embeds, txt_embeds)
            
            # Backward: Backpropagate to update weights
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            
            # Update processing bar
            loop.set_postfix(loss=loss.item())
            
        avg_train_loss = total_loss / len(train_loader)
        print(f"-> Epoch {epoch+1} Finished | Average Loss: {avg_train_loss:.4f}")
        
        # 5. Save Model checkpoint
        checkpoint_path = f"checkpoints/mrl_clip_epoch_{epoch+1}.pt"
        torch.save(model.state_dict(), checkpoint_path)
        print(f"Saved Checkpoint: {checkpoint_path}\n")

if __name__ == "__main__":
    # Note: Running this file requires a machine with a GPU (Nvidia RTX...) to train quickly.
    # Running on CPU will be very slow (may take several hours/epoch).
    train()
