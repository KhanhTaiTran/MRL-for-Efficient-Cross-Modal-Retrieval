# Matryoshka Representation Learning (MRL) for Cross-Modal Retrieval

This project is a proof of concept for Matryoshka Representation Learning (MRL) for Cross-Modal Retrieval.

## Technology Summary
MRL allows cutting off the embeddings from large models (such as CLIP) at the Inference stage without significantly reducing the accuracy. Thanks to that, it helps:
- **Save up to 90% storage space** in the Vector Database.
- **Increase calculation speed many times** (due to smaller matrix multiplication).

---

## How to Prove MRL is More Effective than Traditional Methods

To demonstrate the superior effectiveness of MRL, researchers typically compare it against two traditional baselines: Fixed Feature (FF) training (training independent models) and naive vector truncation (like PCA, SVD, or direct slicing). You can construct a solid proof based on the following three arguments:

### 1. The Ineffectiveness of Naive Truncation vs. MRL Preservation
If you take a standard 3072D embedding from a conventionally trained model and naively slice it to retain only the first 256 dimensions, the remaining vector essentially turns into "noise," resulting in a catastrophic drop in accuracy. 
In contrast, doing the same with an MRL-trained vector ensures the core semantic information is exceptionally well-preserved in the leading dimensions. Research shows that a **128D MRL vector** can match or even defeat a traditional 512D vector trained independently, yielding a **4x optimization in storage** with zero performance degradation.

### 2. Training Cost Efficiency (Train Once, Slice Anytime)
To deploy a system that flexibly operates at multiple sizes like 64D, 128D, 256D, etc., traditional Fixed Feature (FF) methods force you to independently train $N$ different models. This is extremely expensive in terms of both financial cost and compute time.
With MRL, you only need to train a **single model** at the maximum dimension. During real-world deployment, you can dynamically slice the embeddings to any desired representation size on-the-fly without ever needing to retrain.

### 3. Adaptive Retrieval Performance (Shortlisting & Re-ranking)
The most significant practical application of MRL is the two-step search pipeline (Adaptive Retrieval). You can empirically prove this by:
- **Shortlisting**: Using an ultra-small vector (e.g., 16D) to quickly scan through millions of documents and filter out a shortlist of 200 candidates. This saves massive amounts of memory, RAM, and disk I/O.
- **Re-ranking**: Using the full-capacity vector (e.g., 2048D) to re-rank only these 200 candidates to get the final Top-10.
This combination has been proven to maintain the exact same accuracy as using 2048D vectors for the entire database search from the start, but it increases the actual wall-clock speed by **14x** and reduces theoretical compute costs (FLOPs) by up to **128x**.

---

## Repository Structure

1. **`dataset.py`**: Data processing, filtering out corrupted files, applying preprocessing steps (Resize, Tokenize) and initializing `PyTorch DataLoader` for the 22,000 image dataset.
2. **`loss.py`**: The core of the project. Contains `Matryoshka_InfoNCE_Loss` function simulating the hierarchical Loss calculation of MRL.
3. **`model.py`**: Wrapper containing CLIP architecture (`openai/clip-vit-base-patch32`) and additional function to truncate dimension at Inference step.
4. **`extract_features.py`**: Script to run the model through the entire image dataset and save Vectors to disk (embeddings/ folder).
5. **`benchmark.py`**: Script to measure performance. Measure time (Latency), storage space (Storage) and accuracy (Recall@K) of MRL compared to traditional.
6. **`retrieval/`**: Contains Jupyter Notebooks (`diagram-trade-off.ipynb`, `clip_gradcam.ipynb`) to visualize the MRL performance and attention maps.

---

## How to Run

### Step 1: Install Libraries
Please make sure you have installed the necessary libraries (refer to `requirements.txt`):
```bash
pip install -r requirements.txt
```

### Step 2: Check Data
The data path is configured inside `dataset.py`. Run this script to check if the DataLoader works:
```bash
python dataset.py
```

### Step 3: Extract Features
We will use the model to extract features of the Test set and save them:
```bash
python extract_features.py
```
*Running time depends on your machine (CPU/GPU). The result will create an `embeddings/` folder containing 2 `.pt` files.*

### Step 4: Benchmark
Run the final script to output the detailed comparison table:
```bash
python benchmark.py
```

---

## Interpreting the Proof Results

After running `benchmark.py`, you will receive a table similar to the following:

| Dimension | Storage (MB) | Latency (ms) | Recall@1 (%) | Recall@5 (%) |
| :--- | :--- | :--- | :--- | :--- |
| **512 (Base)** | 4.26 | 23.67 | 28.22 | 59.48 |
| **256 (MRL)**  | 2.13 | 8.41 | 19.27 | 47.64 |
| **128 (MRL)**  | 1.06 | 4.91 | 11.29 | 30.56 |
| **64 (MRL)**   | 0.53 | 2.87 | 3.35 | 13.08 |

**How to complete the proof:** 
The table above runs on weights **not trained through MRL** (original Zero-shot), so Recall drops sharply at lower dimensions. You need to use the `loss.py` file to Fine-tune the CLIP model on the training set. Once trained, the Recall curve of the 64D and 128D markers will curve up and stick close to the 512D Baseline, successfully proving the 3 arguments listed in the beginning of this document!
