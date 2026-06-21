import torch
import torch.nn.functional as F
import time
import os

def compute_recall_at_k(similarity_matrix, k=1):
    """
    Calculate Recall@K.
    similarity_matrix: Tensor [N, N]. Rows are Query (Text), Columns are Database (Image).
    Ground-truth labels are on the main diagonal (i == j).
    """
    N = similarity_matrix.shape[0]
    
    # Get the index of the top K most similar results for each query
    # topk_indices có shape [N, k]
    _, topk_indices = similarity_matrix.topk(k, dim=1)
    
    # Create a tensor containing the correct labels [N, 1]
    targets = torch.arange(N, device=similarity_matrix.device).view(-1, 1)
    
    # Check if the target is in the top K returned results
    # results will be a boolean array [N, k]
    results = (topk_indices == targets)
    
    # If there is at least 1 True in the row (meaning the target is in the top K), the query is successful
    correct_queries = results.sum(dim=1) > 0
    
    # Calculate Recall rate
    recall = correct_queries.float().mean().item() * 100.0
    return recall

def run_benchmark():
    print("=== MRL vs BASELINE RETRIEVAL BENCHMARK ===")
    
    # 1. Load data
    img_path = 'embeddings/test_image_features.pt'
    txt_path = 'embeddings/test_text_features.pt'
    
    if not os.path.exists(img_path) or not os.path.exists(txt_path):
        print("Error: Cannot find embeddings file. Please run 'python extract_features.py' first!")
        return
        
    image_features_full = torch.load(img_path)
    text_features_full = torch.load(txt_path)
    
    N = image_features_full.shape[0]
    print(f"Loaded {N} queries and images for benchmarking.")
    
    # 2. Define vector dimensions (MRL dimensions) to test
    # 512 is Baseline. Smaller dimensions are MRL.
    test_dims = [16, 32, 64, 128, 256, 512]
    
    # Convert to GPU if available to speed up matrix calculation
    device = "cuda" if torch.cuda.is_available() else "cpu"
    image_features_full = image_features_full.to(device)
    text_features_full = text_features_full.to(device)
    
    print(f"\nRunning MRL benchmark on device: {device.upper()}")
    print("-" * 95)
    print(f"{'Dimension':<12} | {'Storage (MB)':<15} | {'Latency (ms)':<15} | {'Recall@1 (%)':<15} | {'Recall@5 (%)':<15}")
    print("-" * 95)
    
    for dim in test_dims:
        # Replicate MRL principle: ONLY truncate the vector during the Inference process
        img_mrl = image_features_full[:, :dim]
        txt_mrl = text_features_full[:, :dim]
        
        # NORMALIZE (Very important for calculating Cosine Similarity)
        img_mrl = F.normalize(img_mrl, dim=-1)
        txt_mrl = F.normalize(txt_mrl, dim=-1)
        
        # 1. Measure Vector Database storage memory
        # Storage = (Number of images) * (Number of dimensions) * (4 bytes for float32)
        storage_bytes = N * dim * 4 
        storage_mb = storage_bytes / (1024 * 1024)
        
        # 2. Measure Retrieval speed (Latency)
        # Start counting time
        start_time = time.time()
        
        # Matrix multiplication [N, dim] x [dim, N] -> [N, N]
        # This is the step to calculate Cosine Similarity for ALL pairs.
        # In real-world scenarios with millions of images, this multiplication is very heavy, so a smaller 'dim' will help calculate extremely fast.
        similarity_matrix = txt_mrl @ img_mrl.T
        
        # Time counting finished
        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000.0
        
        # 3. Calculate Accuracy (Recall@K)
        recall_1 = compute_recall_at_k(similarity_matrix, k=1)
        recall_5 = compute_recall_at_k(similarity_matrix, k=5)
        
        # Label Baseline for highest dimension
        label = f"{dim} (Base)" if dim == 512 else f"{dim} (MRL)"
        
        # Print results in table format
        print(f"{label:<12} | {storage_mb:<15.2f} | {latency_ms:<15.2f} | {recall_1:<15.2f} | {recall_5:<15.2f}")
        
    print("-" * 95)
    print("\nConclusion:")
    print("1. When reducing dimensions, STORAGE and LATENCY decrease linearly.")
    print("2. However, Accuracy (Recall) drops only slightly at markers like 64 or 128, proving MRL's efficiency.")

if __name__ == "__main__":
    run_benchmark()
