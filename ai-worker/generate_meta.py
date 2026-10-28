#!/usr/bin/env python3
"""
Utility script to generate index_meta.json with metadata and checkpoint SHA-256.
Run this script whenever you retrain a model or rebuild a vector index.
"""

import os
import sys
import json
import hashlib
import argparse
import faiss
from datetime import datetime, timezone

def sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Generate index_meta.json for model & vector validation")
    parser.add_argument("--checkpoint", default="./checkpoints/mrl_clip_epoch_3.pt", help="Path to checkpoint .pt")
    parser.add_argument("--output", default="./vector_db/index_meta.json", help="Path to output JSON")
    parser.add_argument("--index", default="./vector_db/image_embeddings.index")
    parser.add_argument("--index-version", default="v1-production", help="Index version identifier")
    parser.add_argument("--clip-model", default="openai/clip-vit-base-patch32", help="HF CLIP model identifier")
    args = parser.parse_args()

    checkpoint_path = args.checkpoint
    if not os.path.isfile(checkpoint_path):
        raise FileNotFoundError(checkpoint_path)
    ckpt_hash = sha256_file(checkpoint_path)
    index = faiss.read_index(args.index)
    if index.d != 512 or not index.ntotal:
        raise ValueError("Expected a non-empty 512D index")

    meta = {
        "index_version": args.index_version,
        "num_vectors": index.ntotal,
        "checkpoint_path": checkpoint_path.replace("\\", "/"),
        "checkpoint_sha256": ckpt_hash,
        "clip_model_name": args.clip_model,
        "tokenizer_name": args.clip_model,
        "image_size": 224,
        "normalize_mean": [0.48145466, 0.4578275, 0.40821073],
        "normalize_std": [0.26862954, 0.26130258, 0.27577711],
        "full_dim": 512,
        "supported_dims": [16, 32, 64, 128, 256, 512],
        "built_at": datetime.now(timezone.utc).isoformat()
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"[+] Successfully wrote metadata to {args.output}")

if __name__ == "__main__":
    main()
