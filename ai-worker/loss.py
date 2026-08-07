import torch
import torch.nn as nn
import torch.nn.functional as F

class Matryoshka_InfoNCE_Loss(nn.Module):
    def __init__(self, nesting_list=[8, 16, 32, 64, 128, 256, 512, 768], temperature=0.07):
        super().__init__()
        self.nesting_list = nesting_list 
        self.temperature = temperature   
        
    def forward(self, image_features, text_features):
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

# Hard Negative Mining variant
class MRL_InfoNCE_HardNeg_Loss(nn.Module):
    def __init__(
        self,
        nesting_list: list |None = None,
        temperature: float = 0.07,
        hard_neg_ratio: float = 0.5,
    ):
        super().__init__()
        if nesting_list is None:
            nesting_list = [16, 32, 64, 128, 256, 512]
        self.nesting_list = nesting_list
        self.temperature = temperature
        self.hard_neg_ratio = hard_neg_ratio

    def _hard_neg_infonce(self, img_feat: torch.Tensor, txt_feat: torch.Tensor) -> torch.Tensor:
        device = img_feat.device
        batch_size = img_feat.shape[0]
        labels = torch.arange(batch_size, device=device)

        # similarity logits
        logits_i2t = (img_feat @ txt_feat.T) / self.temperature
        logits_t2i = logits_i2t.T

        # hard negative 
        def apply_hard_neg_mask(logits: torch.Tensor) -> torch.Tensor:
            B = logits.shape[0]
            pos_mask = torch.eye(B, dtype=torch.bool, device=device)  

            # Collect negative logits per row
            neg_logits = logits.masked_fill(pos_mask, float('-inf'))  

            # Threshold: keep only top hard_neg_ratio of negatives
            k = max(1, int((B - 1) * self.hard_neg_ratio))
            threshold_vals, _ = neg_logits.topk(k, dim=1)             
            threshold = threshold_vals[:, -1].unsqueeze(1)            

            # Build mask: True = keep (positive OR hard negative)
            keep_mask = pos_mask | (neg_logits >= threshold)           
            # Replace dropped entries with a very large negative so softmax ignores them
            masked_logits = logits.masked_fill(~keep_mask, -1e9)
            return masked_logits

        masked_i2t = apply_hard_neg_mask(logits_i2t) #TODO: Explain the purpose of this line
        masked_t2i = apply_hard_neg_mask(logits_t2i)

        loss_i2t = F.cross_entropy(masked_i2t, labels)
        loss_t2i = F.cross_entropy(masked_t2i, labels)
        return (loss_i2t + loss_t2i) / 2.0

    def forward(self, image_features: torch.Tensor, text_features: torch.Tensor) -> torch.Tensor:
        total_loss = image_features.new_tensor(0.0)  # Initialize on same device and dtype
        for dim in self.nesting_list:
            img_d = F.normalize(image_features[:, :dim], dim=-1)
            txt_d = F.normalize(text_features[:, :dim], dim=-1)
            total_loss += self._hard_neg_infonce(img_d, txt_d)
        return total_loss


if __name__ == "__main__":
    print("\nTesting MRL_InfoNCE_HardNeg_Loss...")
    loss_fn_hn = MRL_InfoNCE_HardNeg_Loss(hard_neg_ratio=0.5)
    dummy_img2 = torch.randn(8, 512)
    dummy_txt2 = torch.randn(8, 512)
    loss_hn = loss_fn_hn(dummy_img2, dummy_txt2)
    print(f"Hard-Neg MRL Loss (B=8): {loss_hn.item():.4f}")
