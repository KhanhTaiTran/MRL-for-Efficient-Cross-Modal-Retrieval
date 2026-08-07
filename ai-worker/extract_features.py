import torch
import time
import os
from tqdm import tqdm
from dataset import create_dataloaders
from model import MRL_CrossModal_Model

CHECKPOINT_PRIORITY = [
    'checkpoints/mrl_v3_best.pt',   # Best: v3 aggressive hard-neg training
    'checkpoints/mrl_v2_best.pt',   # Good: v2 hard-neg training
    'checkpoints/mrl_clip_epoch_3.pt',  # Baseline: v1 fine-tune
]
CHECKPOINT_PATH = next(
    (p for p in CHECKPOINT_PRIORITY if os.path.exists(p)),
    None
)


def extract_and_save_features():
    print("1. Preparing DataLoader (Using Test Set)...")
    # We only need the test_loader to demonstrate Retrieval performance
    _, _, test_loader, df = create_dataloaders(batch_size=64, num_workers=0)
    
    print("\n2. Loading Model...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    
    model = MRL_CrossModal_Model().to(device)

    if CHECKPOINT_PATH is not None and os.path.exists(CHECKPOINT_PATH):
        print(f"Loading fine-tuned model from {CHECKPOINT_PATH}...")
        # Load state dict directly
        model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device)) 
        print("Model loaded successfully.")
    else:
        print("Using root model (Zero-shot, not trained).")
 
    model.eval() # switch to evaluation mode

    all_image_features = []
    all_text_features = []
    
    print(f"\n3. Extracting Features for {len(test_loader.dataset)} items...") # type: ignore
    
    # Don't use gradient to save RAM and speed up
    with torch.no_grad():
        for batch_idx, (images, input_ids, attention_masks) in enumerate(tqdm(test_loader)):
            images = images.to(device)
            input_ids = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            
            # Extract FULL vector (512 dimensions)
            # According to MRL principle, we only need to extract the full bản 1 time, 
            # then in the benchmark file we will cut (slice) this vector out.
            img_embeds = model.extract_image_features(images)
            txt_embeds = model.extract_text_features(input_ids, attention_masks)
            
            # Store
            all_image_features.append(img_embeds.cpu())
            all_text_features.append(txt_embeds.cpu())
            
    # Concatenate all batches into a single tensor
    final_image_features = torch.cat(all_image_features, dim=0)
    final_text_features = torch.cat(all_text_features, dim=0)
    
    print(f"\nExtraction Complete!")
    print(f"Final Image Features Shape: {final_image_features.shape}")
    print(f"Final Text Features Shape: {final_text_features.shape}")
    
    print("\n4. Saving features to disk...")
    os.makedirs('embeddings', exist_ok=True)
    torch.save(final_image_features, 'embeddings/test_image_features.pt')
    torch.save(final_text_features, 'embeddings/test_text_features.pt')
    print("Saved to 'embeddings/' folder.")

if __name__ == "__main__":
    extract_and_save_features()
