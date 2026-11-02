"""Run worker commands with consistent imports and artifact paths.

Usage from the repository root: python ai-worker/manage.py --help
"""
import argparse
from pathlib import Path
import subprocess
import sys


COMMANDS = {
    "serve": ("uvicorn", "Run the FastAPI search service"),
    "start-local": ("scripts.local.start_phase_minus1", "Start native inference and Go gateway"),
    "build-fashiongen-index": ("scripts.indexing.build_fashiongen_index", "Verify cached FashionGen features and publish an index"),
    "generate-meta": ("scripts.indexing.generate_meta", "Generate metadata for an existing index (manual utility)"),
    "extract-dataset": ("scripts.data.extract_fashiongen_h5", "Extract FashionGen HDF5 images and metadata"),
    "update-brands": ("scripts.data.update_metadata_brand", "Update FashionGen metadata with brands"),
    "train-fashiongen": ("ai_worker.training.fashiongen", "Train the current FashionGen MRL model"),
    "train-baseline": ("ai_worker.training.baseline", "Run the original B/32 training experiment"),
    "train-v2": ("ai_worker.training.v2", "Run the B/32 v2 training experiment"),
    "train-v3": ("ai_worker.training.v3", "Run the B/32 v3 training experiment"),
    "train-fixed-features": ("ai_worker.training.fixed_features", "Train a fixed dimension comparison model"),
    "extract-baseline": ("ai_worker.extraction.baseline", "Extract features for the earlier B/32 dataset"),
    "extract-fashiongen": ("ai_worker.extraction.fashiongen", "Extract FashionGen features (zero-shot by default)"),
    "extract-mrl-fashiongen": ("ai_worker.extraction.mrl_fashiongen", "Extract trained FashionGen MRL features"),
    "benchmark": ("ai_worker.benchmarks.retrieval", "Evaluate earlier retrieval, reranking and AQE experiments"),
    "benchmark-fashiongen": ("ai_worker.benchmarks.fashiongen", "Evaluate FashionGen retrieval"),
    "benchmark-fixed-features": ("ai_worker.benchmarks.ff_vs_mrl", "Compare fixed dimensions against MRL"),
    "benchmark-interpolation": ("ai_worker.benchmarks.interpolation", "Evaluate dimension interpolation"),
    "test": ("tests.run_phase_minus1", "Run search regression; add --e2e for live Go/Python tests"),
    "test-readiness": ("tests.test_readiness", "Verify unseeded service readiness"),
    "test-e2e": ("tests.test_search_e2e", "Run isolated live Go/Python integration tests"),
}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Commands:\n" + "\n".join(f"  {name:28} {description}" for name, (_, description) in COMMANDS.items()),
    )
    parser.add_argument("command", choices=COMMANDS)
    # Pass command-specific flags through, including --help.
    args = parser.parse_args(sys.argv[1:2])
    module = COMMANDS[args.command][0]
    extra = sys.argv[2:]
    if args.command == "serve":
        extra = ["ai_worker.api.server:app", "--host", "127.0.0.1", "--port", "8001", *extra]
    result = subprocess.run(
        [sys.executable, "-m", module, *extra],
        cwd=Path(__file__).resolve().parent,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
