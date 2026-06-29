# [Matryoshka Representation Learning for Efficient Cross-Modal Retrieval](https://arxiv.org/abs/2205.13147)
_Adapted from the original work by: Aditya Kusupati*, Gantavya Bhatt*, Aniket Rege*, Matthew Wallingford, Aditya Sinha, Vivek Ramanujan, William Howard-Snyder, Kaifeng Chen, Sham Kakade, Prateek Jain, Ali Farhadi_

Learned representations are used in multiple downstream tasks like web-scale search & retrieval. However, they are flat & rigid -- Information is diffused across dimensions and cannot be adaptively deployed without large post-hoc overhead. We fix both of these issues with **Matryoshka Representation Learning** (MRL)🪆. 

This repository extends the original MRL concept to **Vision-Language Models (CLIP)** for highly efficient **Cross-Modal Retrieval** (Text-to-Image / Image-to-Text). The repository is organized as follows:

1. Set up
2. Matryoshka Cross-Modal Model
3. Training Models
4. Inference & Benchmarking
5. Model Analysis
6. Advanced Retrieval & Re-ranking


## 1. Set Up
Pip install the requirements file in the `ai-worker` directory. Note that a python3 distribution and PyTorch are required:
```bash
# Set up a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r ai-worker/requirements.txt
```

## 2. Matryoshka Cross-Modal Model
Unlike the original MRL which modifies the final linear layer of a ResNet, we modify the projection heads of a **CLIP (ViT-B/32)** model. The model is defined in `ai-worker/model.py` and can be instantiated as:
```python
from ai_worker.model import MRL_CrossModal_Model

# Initialize the CLIP-based MRL model
mrl_model = MRL_CrossModal_Model()
```
The model leverages a custom Matryoshka Loss (`ai-worker/loss.py`) which forces the embeddings to be learned in a nested, hierarchical manner across predefined representation sizes (e.g., `[16, 64, 256, 512, 768]`).

## 3. Training Models
`cd ai-worker/`

We provide training scripts (`train.py`, `train_v2.py`, `train_v3.py`) to fine-tune the CLIP model using the Matryoshka contrastive loss on image-text pairs. 

### Training MRL Cross-Modal Model
To start a training run (example using `train_v3.py` which contains our most optimized loop):
```bash
python train_v3.py
```
*Note: Make sure to configure your dataset paths inside the training scripts before running. Checkpoints are automatically saved to `ai-worker/checkpoints/`.*

## 4. Inference & Benchmarking
### Feature Extraction
To evaluate the model, you first need to extract the image and text features into `.pt` or `.pth` files.
```bash
python extract_features.py 
```
Or for large-scale database vectors:
```bash
python extract_db_vectors.py
```

### Evaluation (Top-K, mAP, P@K)
Once features are extracted into the `embeddings/` folder, run the benchmark script to compute cross-modal retrieval metrics:
```bash
python benchmark.py
```
This script evaluates the model across all MRL dimensions simultaneously and reports `Top-1`, `Top-5`, `P@5`, and `mAP@5` to demonstrate the compute-accuracy tradeoff.

## 5. Model Analysis
`cd retrieval/`

We provide Jupyter notebooks which contain performance visualization and metric analysis tailored for Cross-Modal MRL models:

- `clip_gradcam.ipynb`: Generates **GradCAM heatmaps** for our ViT-based CLIP model. It visually demonstrates how the model's focus on the image shifts across different MRL dimensions (e.g., from 16D to 768D) given a specific Text Query.
- `compute_metric.ipynb`: A clean, minimal notebook for interactive metric computation and validation set analysis.

## 6. Advanced Retrieval
`cd ai-worker/`

In an attempt to achieve optimal compute-accuracy tradeoff, we carry out **Adaptive Retrieval**:
1. **Shortlisting**: Retrieve a length $k$ neighbors shortlist using an extremely low dimension $D_s$ (e.g., 16D or 64D).
2. **Re-ranking**: Re-rank the shortlist using the full dimension $D_r$ (e.g., 768D).

We provide scripts for these advanced techniques:
- `reranker.py`: Implements the multi-stage Adaptive Retrieval (Funnel Retrieval) logic.
- `query_expansion.py`: Explores techniques to expand the text query for more robust retrieval.

With these techniques, we are able to match the Top-1 accuracy (%) of full-dimension retrieval while drastically reducing the MFLOPs/Query and storage footprint.

---
## Citation
If you find the base MRL concept useful, please consider citing the original paper:
```bibtex
@inproceedings{kusupati2022matryoshka,
  title     = {Matryoshka Representation Learning},
  author    = {Kusupati, Aditya and Bhatt, Gantavya and Rege, Aniket and Wallingford, Matthew and Sinha, Aditya and Ramanujan, Vivek and Howard-Snyder, William and Chen, Kaifeng and Kakade, Sham and Jain, Prateek and others},
  booktitle = {Advances in Neural Information Processing Systems},
  month     = {December},
  year      = {2022},
}
```
