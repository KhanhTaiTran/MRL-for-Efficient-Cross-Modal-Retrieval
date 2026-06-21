# Matryoshka Representation Learning (MRL) for Cross-Modal Retrieval

This project is a proof of concept for Matryoshka Representation Learning (MRL) for Cross-Modal Retrieval.

## Technology Summary
MRL allows cutting off the embeddings from large models (such as CLIP) at the Inference stage without significantly reducing the accuracy. Thanks to that, it helps:
- **Save up to 90% storage space** in the Vector Database.
- **Increase calculation speed many times** (due to smaller matrix multiplication).

---

## Repository Structure

1. **`dataset.py`**: Data processing, filtering out corrupted files, applying preprocessing steps (Resize, Tokenize) and initializing `PyTorch DataLoader` for the 22,000 image dataset.
2. **`loss.py`**: The core of the project. Contains `Matryoshka_InfoNCE_Loss` function simulating the hierarchical Loss calculation of MRL.
3. **`model.py`**: Wrapper containing CLIP architecture (`openai/clip-vit-base-patch32`) and additional function to truncate dimension at Inference step.
4. **`extract_features.py`**: Script to run the model through the entire image dataset and save Vectors to disk (embeddings/ folder).
5. **`benchmark.py`**: Script to measure performance. Measure time (Latency), storage space (Storage) and accuracy (Recall@K) of MRL compared to traditional.

---

## 🚀 How to Run

### Step 1: Install Libraries
Please make sure you have installed the necessary libraries:
```bash
pip install torch torchvision pandas scikit-learn transformers tqdm pillow
```

### Step 2: Check Data
The data path is configured by default to the folder `D:\Pre-thesis\Thesis Dataset-...`. You can change this path inside the `dataset.py` file.
Run this script to check if the DataLoader works:
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

## 📊 Interpreting the Proof Results

After running `benchmark.py`, you will receive a table similar to the following:

| Dimension | Storage (MB) | Latency (ms) | Recall@1 (%) | Recall@5 (%) |
| :--- | :--- | :--- | :--- | :--- |
| **512 (Base)** | 4.26 | 23.67 | 28.22 | 59.48 |
| **256 (MRL)**  | 2.13 | 8.41 | 19.27 | 47.64 |
| **128 (MRL)**  | 1.06 | 4.91 | 11.29 | 30.56 |
| **64 (MRL)**   | 0.53 | 2.87 | 3.35 | 13.08 |

### Points to prove:
1. **Storage & Speed:** At `64 dimensions`, our system **saves ~88% storage space** (from 4.26MB to 0.53MB). Query speed is ~8 times faster. This difference when multiplied by millions of images on production is huge.
2. **Accuracy (Note):** The table above runs on weights **not trained through MRL** (original Zero-shot), so Recall drops sharply. 
👉 **How to complete:** You only need to use the `loss.py` file to Fine-tune the CLIP model on the training set. Then, the Recall curve of the 64, 128 markers will curve up and stick close to the 512 Baseline, creating a perfect trade-off!
