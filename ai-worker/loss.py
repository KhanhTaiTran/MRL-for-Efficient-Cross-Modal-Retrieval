import torch
import torch.nn as nn
import torch.nn.functional as F

class Matryoshka_InfoNCE_Loss(nn.Module):
    """
    Matryoshka Representation Learning (MRL) apply for Cross-Modal Retrieval (Contrastive Loss/InfoNCE).
    
    Effect:
    Instead of calculating loss on the full 768-dimensional vector, this function will cut the vector into smaller parts (e.g., 8, 16, 32... dimensions).
    It forces the model to learn to pack the most important information into the initial dimensions of the vector.
    """
    def __init__(self, nesting_list=[8, 16, 32, 64, 128, 256, 512, 768], temperature=0.07):
        super().__init__()
        self.nesting_list = nesting_list # vector dimensions to be cut
        self.temperature = temperature   # temperature to sharpen probability distribution
        
    def forward(self, image_features, text_features):
        """
        Args:
            image_features: Tensor shape [Batch, 768]
            text_features: Tensor shape [Batch, 768]
        Returns:
            total_loss: Total loss of all dimensions
        """
        device = image_features.device
        batch_size = image_features.shape[0]
        
        # ground-truth for Contrastive Loss: 
        # The i-th pair of images must match the i-th pair of text -> The label is the diagonal [0, 1, 2, ..., batch_size-1]
        labels = torch.arange(batch_size, device=device)
        
        total_loss = 0.0
        
        # The most important loop of Matryoshka
        for dim in self.nesting_list:
            # 1. TRUNCATE: Only take the first 'dim' dimensions of the vector
            img_feat_m = image_features[:, :dim]
            txt_feat_m = text_features[:, :dim]
            
            # 2. NORMALIZE: Normalize the vector to a length of 1 to calculate Cosine Similarity accurately
            img_feat_m = F.normalize(img_feat_m, dim=-1)
            txt_feat_m = F.normalize(txt_feat_m, dim=-1)
            
            # 3. CALCULATE SIMILARITY MATRIX
            # Multiply the matrix [Batch, dim] x [dim, Batch] -> [Batch, Batch]
            logits_per_image = (img_feat_m @ txt_feat_m.T) / self.temperature
            logits_per_text = logits_per_image.T
            
            # 4. CALCULATE CROSS-ENTROPY LOSS (InfoNCE)
            # Loss for finding Text from Image
            loss_i2t = F.cross_entropy(logits_per_image, labels)
            # Loss for finding Image from Text
            loss_t2i = F.cross_entropy(logits_per_text, labels)
            
            # Average loss
            step_loss = (loss_i2t + loss_t2i) / 2.0
            
            # 5. ADD UP LOSS OF EACH DIMENSION
            # In the original paper, they can use weights c_m, but the most common is to divide c_m = 1
            total_loss += step_loss
            
        return total_loss

if __name__ == "__main__":
    # Test loss function
    print("Testing Matryoshka InfoNCE Loss...")
    loss_fn = Matryoshka_InfoNCE_Loss()
    
    # Create fake features with batch_size=4, embedding_dim=768
    dummy_img = torch.randn(4, 768)
    dummy_txt = torch.randn(4, 768)
    
    loss = loss_fn(dummy_img, dummy_txt)
    print(f"Total MRL Loss: {loss.item():.4f}")
