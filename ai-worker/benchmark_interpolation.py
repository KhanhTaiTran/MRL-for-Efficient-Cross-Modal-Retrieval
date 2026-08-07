"""
Benchmark Script: MRL Interpolation (Untrained Dims) vs FF vs Standard CLIP
"""
import argparse
import os
import torch
import torch.nn.functional as F
from tqdm import tqdm
import matplotlib.pyplot as plt

from dataset import create_dataloaders
from model import MRL_CrossModal_Model

TRAINED_DIMS = [16, 32, 64, 128, 256, 512]
# dims that not trained
INTERPOLATION_DIMS = [12, 24, 48, 96, 192, 384]
# all dims to evaluate (both trained and untrained)
ALL_DIMS = sorted(TRAINED_DIMS + INTERPOLATION_DIMS)

if os.path.exists('/content'):
    DEFAULT_DATA_CSV = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data.csv"
    DEFAULT_DATA_IMG = "/content/drive/MyDrive/Train_MRL_test_19-6/Thesis Dataset/data_images"
    DEFAULT_CKPT_DIR = "/content/drive/MyDrive/Train_MRL_test_19-6/checkpoints"
else:
    DEFAULT_DATA_CSV = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data.csv"
    DEFAULT_DATA_IMG = r"D:\Pre-thesis\Thesis Dataset-20260617T002927Z-3-002\Thesis Dataset\data_images"
    DEFAULT_CKPT_DIR = "checkpoints"

def evaluate_retrieval_metrics(img_embeds: torch.Tensor, txt_embeds: torch.Tensor, k: int = 5) -> dict:
    img_norm = F.normalize(img_embeds, dim=-1)
    txt_norm = F.normalize(txt_embeds, dim=-1)
    sim = txt_norm @ img_norm.T
    N = sim.shape[0]

    _, topk_indices = sim.topk(max(k, 1), dim=1)
    targets = torch.arange(N, device=sim.device).view(-1, 1)
    results = (topk_indices == targets)

    top1 = (results[:, 0]).float().mean().item() * 100.0
    topk = (results[:, :k].sum(dim=1) > 0).float().mean().item() * 100.0
    return {"recall@1": top1, f"recall@{k}": topk}

def extract_full_features(model, dataloader, device):
    model.eval()
    img_list, txt_list = [], []
    with torch.no_grad():
        for images, input_ids, attention_masks in tqdm(dataloader, desc="Extracting features", leave=False):
            images = images.to(device)
            input_ids = input_ids.to(device)
            attention_masks = attention_masks.to(device)
            img_list.append(model.extract_image_features(images, dim=512).cpu())
            txt_list.append(model.extract_text_features(input_ids, attention_masks, dim=512).cpu())
    return torch.cat(img_list, dim=0), torch.cat(txt_list, dim=0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_csv", type=str, default=DEFAULT_DATA_CSV)
    parser.add_argument("--data_img", type=str, default=DEFAULT_DATA_IMG)
    parser.add_argument("--checkpoint_dir", type=str, default=DEFAULT_CKPT_DIR)
    parser.add_argument("--batch_size", type=int, default=64)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}\n")

    _, val_loader, _, _ = create_dataloaders(
        csv_file=args.data_csv, img_dir=args.data_img, batch_size=args.batch_size, num_workers=2
    )

    print("\n[1] Evaluating Baseline: Zero-shot Pre-trained CLIP (512D)...")
    model_clip = MRL_CrossModal_Model().to(device)
    img_clip, txt_clip = extract_full_features(model_clip, val_loader, device)
    clip_metrics = evaluate_retrieval_metrics(img_clip, txt_clip, k=5)
    print(f"-> Zero-shot CLIP Recall@1: {clip_metrics['recall@1']:.2f}%")
    
    # Dọn dẹp RAM
    del model_clip, img_clip, txt_clip
    torch.cuda.empty_cache()

    print("\n[2] Evaluating MRL Model across ALL dimensions (Interpolation)...")
    mrl_ckpt_path = os.path.join(args.checkpoint_dir, "mrl_v3_best.pt")
    if not os.path.exists(mrl_ckpt_path):
        mrl_ckpt_path = os.path.join(args.checkpoint_dir, "mrl_v2_best.pt")

    mrl_r1 = []
    if os.path.exists(mrl_ckpt_path):
        print(f"Loading MRL checkpoint: {mrl_ckpt_path}")
        model_mrl = MRL_CrossModal_Model().to(device)
        model_mrl.load_state_dict(torch.load(mrl_ckpt_path, map_location=device))
        img_512, txt_512 = extract_full_features(model_mrl, val_loader, device)

        for d in ALL_DIMS:
            m = evaluate_retrieval_metrics(img_512[:, :d], txt_512[:, :d], k=5)
            mrl_r1.append(m['recall@1'])
            tag = "(Untrained!)" if d in INTERPOLATION_DIMS else ""
            print(f"  Dim {d:3d} -> R@1: {m['recall@1']:.2f}% {tag}")
            
        del model_mrl, img_512, txt_512
        torch.cuda.empty_cache()
    else:
        print("WARNING: MRL checkpoint not found!")

    print("\n[3] Evaluating Fixed Feature (FF) Models...")
    ff_r1 = []
    for d in TRAINED_DIMS:
        ff_ckpt_path = os.path.join(args.checkpoint_dir, f"ff_dim_{d}_best.pt")
        if os.path.exists(ff_ckpt_path):
            model_ff = MRL_CrossModal_Model().to(device)
            model_ff.load_state_dict(torch.load(ff_ckpt_path, map_location=device))
            img_d, txt_d = extract_full_features(model_ff, val_loader, device)
            m = evaluate_retrieval_metrics(img_d[:, :d], txt_d[:, :d], k=5)
            ff_r1.append(m['recall@1'])
            print(f"  Dim {d:3d} -> R@1: {m['recall@1']:.2f}%")
            del model_ff, img_d, txt_d
            torch.cuda.empty_cache()
        else:
            ff_r1.append(None)
            print(f"  Dim {d:3d} -> Checkpoint missing!")

    print("\n[4] Generating Interpolation Plot...")
    plt.figure(figsize=(10, 6))
    
    # Plot MRL line (continuous)
    if len(mrl_r1) == len(ALL_DIMS):
        plt.plot(ALL_DIMS, mrl_r1, marker='o', linestyle='-', color='blue', linewidth=2.5, label='MRL (All Dims)')
        
        # Highlight points corresponding to untrained dimensions (interpolation)
        untrained_idx = [i for i, d in enumerate(ALL_DIMS) if d in INTERPOLATION_DIMS]
        plt.scatter([ALL_DIMS[i] for i in untrained_idx], [mrl_r1[i] for i in untrained_idx], 
                    color='red', zorder=5, s=100, label='MRL Untrained (Interpolation)')

    # Plot FF points (only trained dims)
    valid_ff_dims = [d for i, d in enumerate(TRAINED_DIMS) if ff_r1[i] is not None]
    valid_ff_r1 = [r for r in ff_r1 if r is not None]
    if valid_ff_dims:
        plt.plot(valid_ff_dims, valid_ff_r1, marker='s', linestyle='--', color='green', markersize=8, label='Fixed Feature (FF)')

    # Plot CLIP Baseline 512D
    plt.axhline(y=clip_metrics['recall@1'], color='black', linestyle='-.', linewidth=2,
                label=f'Zero-shot CLIP Baseline 512D ({clip_metrics["recall@1"]:.2f}%)')

    plt.xscale('log', base=2)
    plt.xticks(ALL_DIMS, labels=[str(d) for d in ALL_DIMS], rotation=45)
    plt.xlabel('Representation Dimension (Log Scale)', fontsize=12)
    plt.ylabel('Recall@1 (%)', fontsize=12)
    plt.title('MRL Dimensionality Interpolation vs Fixed Feature Baselines', fontsize=14, fontweight='bold')
    plt.legend(fontsize=11)
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.tight_layout()
    
    plot_path = "mrl_interpolation_plot.png"
    plt.savefig(plot_path, dpi=300)
    print(f"Plot saved successfully to {os.path.abspath(plot_path)}")

if __name__ == "__main__":
    main()
