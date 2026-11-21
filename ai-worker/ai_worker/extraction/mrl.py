"""
Compatibility alias for ai_worker.extraction.mrl_fashiongen.
"""
import sys
from ai_worker.extraction.mrl_fashiongen import extract_and_save, MRL_IMG_FEATS, MRL_TXT_FEATS, MRL_PRODUCT_IDS
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", type=str, default="checkpoints/mrl_fashiongen_best.pt",
        help="Path to trained MRL checkpoint (default: checkpoints/mrl_fashiongen_best.pt)."
    )
    args = parser.parse_args()
    extract_and_save(checkpoint_path=args.checkpoint)
