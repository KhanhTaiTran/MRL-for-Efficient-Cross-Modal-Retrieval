import os

import torchvision
from PIL import Image

MOCK_DIR = "mock_data"

def download_cifar_mock():
    # create mock_data directory if it doesn't exist
    os.makedirs(MOCK_DIR, exist_ok=True)
    
    # delete any existing files in mock_data to ensure a clean slate
    for f in os.listdir(MOCK_DIR):
        os.remove(os.path.join(MOCK_DIR, f))
    print(f"Deleted existing files in {MOCK_DIR}.")

    print("Downloading/loading CIFAR-100 dataset (Approximately 160MB if not already downloaded)...")
    # Load CIFAR-100 test set (10,000 images) and save a subset to mock_data
    dataset = torchvision.datasets.CIFAR100(root='./data', train=False, download=True)
    
    # take a subset of classes to keep it manageable (e.g., 6 classes with 4 images each = 24 images total)
    target_classes = ['apple', 'bicycle', 'motorcycle', 'cat', 'dog', 'sunflower']
    
    # Map class names to indices in the dataset
    class_to_idx = dataset.class_to_idx
    target_indices = {class_to_idx[cls]: cls for cls in target_classes if cls in class_to_idx}
    
    print(f"Extracting images for classes: {', '.join(target_indices.values())}...")
    
    # Count the number of images saved, taking 4 images per class
    saved_counts = {cls: 0 for cls in target_classes}
    images_per_class = 4 
    total_saved = 0
    
    for img, label in dataset:
        if label in target_indices:
            cls_name = target_indices[label]
            
            if saved_counts[cls_name] < images_per_class:
                # Save file in the format: apple_01.jpg, cat_02.jpg,...
                file_name = f"{cls_name}_{saved_counts[cls_name] + 1:02d}.jpg"
                file_path = os.path.join(MOCK_DIR, file_name)
                
                # CIFAR-100 returns a PIL Image so it can be saved directly
                img.save(file_path)
                
                saved_counts[cls_name] += 1
                total_saved += 1
                print(f"Saved: {file_name}")
                
        # Stop once we've saved enough images for each class
        if all(count >= images_per_class for count in saved_counts.values()):
            break
            
    print(f"\n Completed! Saved {total_saved} CIFAR-100 images to '{MOCK_DIR}'.")

if __name__ == "__main__":
    download_cifar_mock()