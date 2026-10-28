"""
extract_features_zeroshot.py - Alias for extract_features_fashiongen.py
"""
import sys
from extract_features_fashiongen import extract_and_save
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", type=str, default=None,
        help="Path to fine-tuned checkpoint. Omit for zero-shot."
    )
    args = parser.parse_args()
    extract_and_save(checkpoint_path=args.checkpoint)
