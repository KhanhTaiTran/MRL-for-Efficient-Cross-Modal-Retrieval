import torch
import torch.nn as nn
from transformers import CLIPModel 

class MRL_CrossModal_Model(nn.Module):
    def __init__(self, model_name='openai/clip-vit-base-patch32'):
        super().__init__()
        self.clip = CLIPModel.from_pretrained(model_name)
        
    def forward(self, images, input_ids, attention_mask):
        outputs = self.clip(pixel_values=images, input_ids=input_ids, attention_mask=attention_mask)
        return outputs.image_embeds, outputs.text_embeds
        
    def extract_image_features(self, images, dim=None):
        vision_outputs = self.clip.vision_model(pixel_values=images)
        image_embeds = self.clip.visual_projection(vision_outputs[1]) # vision_outputs[1] is pooler_output
                
        if dim is not None:
            # Truncate vector (Example: [Batch, 768] -> [Batch, 64])
            image_embeds = image_embeds[:, :dim]
        return image_embeds
        
    def extract_text_features(self, input_ids, attention_mask, dim=None):
        text_outputs = self.clip.text_model(input_ids=input_ids, attention_mask=attention_mask)
        text_embeds = self.clip.text_projection(text_outputs[1])
                
        if dim is not None:
            # Truncate vector (Example: [Batch, 768] -> [Batch, 64])
            text_embeds = text_embeds[:, :dim]
        return text_embeds

if __name__ == "__main__":
    print("Testing MRL Model Architecture...")
    model = MRL_CrossModal_Model()
    
    # Tạo dummy data
    dummy_img = torch.randn(2, 3, 224, 224)
    dummy_input_ids = torch.randint(0, 1000, (2, 77))
    dummy_mask = torch.ones((2, 77))
    
    img_feat, txt_feat = model(dummy_img, dummy_input_ids, dummy_mask)
    print(f"Full Image features shape: {img_feat.shape}")
    
    # Test truncate MRL
    img_feat_mrl = model.extract_image_features(dummy_img, dim=64)
    print(f"Truncated Image features (MRL 64D): {img_feat_mrl.shape}")
