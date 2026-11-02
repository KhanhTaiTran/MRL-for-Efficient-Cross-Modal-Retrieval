# AI worker

Python code is grouped by responsibility. `manage.py` is the command entry point;
the `ai_worker` package contains implementation code. Run the commands below from
the repository root using its virtual environment.

```text
ai-worker/
├── manage.py                    Command launcher; normalizes the working directory
├── ai_worker/
│   ├── api/server.py            FastAPI startup, health, configuration and search
│   ├── models/mrl.py           Shared CLIP/MRL model and feature extraction methods
│   ├── retrieval/               Two-stage reranking and alpha query expansion
│   ├── config/fashiongen.py     Dataset paths and FashionGen experiment settings
│   ├── datasets/               FashionGen and earlier fashion dataset loaders
│   ├── training/               Training loops and losses
│   ├── extraction/             Export image/text embeddings from trained/base models
│   ├── benchmarks/             Retrieval metrics, latency and experiment comparisons
│   ├── legacy/                 Retired RabbitMQ RPC and original index builder
│   └── paths.py                Stable worker/repository artifact roots
├── scripts/
│   ├── data/                   HDF5 extraction and CSV metadata preparation
│   ├── indexing/               Verified FashionGen index builder and metadata utility
│   └── local/                  Native inference + Go gateway launcher
├── tests/                      Readiness, real-model regression and HTTP integration
├── checkpoints/                Local model weights (ignored by Git)
├── embeddings/                 Local extracted feature caches (ignored by Git)
├── vector_db/                  Active FAISS indexes and manifest (ignored by Git)
├── data/                       Local datasets (ignored by Git)
├── mrl-model/                  Earlier standalone research weights (local artifact)
├── Dockerfile
└── requirements.txt
```

## Run and test

```powershell
.\.venv\Scripts\python.exe ai-worker/manage.py --help
.\.venv\Scripts\python.exe ai-worker/manage.py serve
.\.venv\Scripts\python.exe ai-worker/manage.py start-local
.\.venv\Scripts\python.exe ai-worker/manage.py test-readiness
.\.venv\Scripts\python.exe ai-worker/manage.py test
.\.venv\Scripts\python.exe ai-worker/manage.py test --e2e
```

`serve` starts inference alone on port 8001; `start-local` starts inference and the
Go gateway. Choose one when using those ports. The local launcher refuses occupied
ports and records its own process IDs/logs under the repository's `tmp/` directory.

The real-model regression suite needs the local matching checkpoint, index and
cached Hugging Face model. The E2E suite also needs Go and dataset images. Its
default ports are 18001/18080; set `TEST_INFER_PORT` and `TEST_API_PORT` if occupied.

Docker uses `ai_worker.api.server:app` directly. Compose build/run commands are
unchanged; rebuild the AI image after this source reorganization.

## Research commands

```powershell
.\.venv\Scripts\python.exe ai-worker/manage.py train-fashiongen
.\.venv\Scripts\python.exe ai-worker/manage.py extract-fashiongen --help
.\.venv\Scripts\python.exe ai-worker/manage.py extract-mrl-fashiongen --help
.\.venv\Scripts\python.exe ai-worker/manage.py benchmark-fashiongen --help
.\.venv\Scripts\python.exe ai-worker/manage.py build-fashiongen-index --help
```

Set `FASHIONGEN_ROOT` for your dataset. Under `training/`, `fashiongen.py` is the
current ViT-B/16 FashionGen experiment; `baseline.py`, `v2.py`, `v3.py` and
`fixed_features.py` preserve earlier ViT-B/32 experiments. `losses.py` contains
shared objectives, not a runnable training script.

Under `extraction/`, `fashiongen.py` exports zero-shot features by default;
`mrl_fashiongen.py` uses the trained checkpoint. `mrl.py` and `zeroshot.py` preserve
the earlier alias modules. `baseline.py` exports the older dataset's features.
Under `benchmarks/`, `fashiongen.py` evaluates the current dataset;
`retrieval.py`, `ff_vs_mrl.py` and `interpolation.py` preserve earlier experiments.

The normal commands set the working directory to `ai-worker/` so existing research
output locations remain stable. Advanced callers can also use `python -m
ai_worker.training.fashiongen` **from `ai-worker/`**. Import shared code through
its full package name, e.g. `from ai_worker.models.mrl import MRL_CrossModal_Model`.
Do not run nested implementation files directly.

## Indexes and retired code

Use `scripts/indexing/build_fashiongen_index.py` through the launcher for current
FashionGen indexes: it verifies checkpoint/cache provenance and publishes a full
manifest. `generate_meta.py` only creates metadata for an existing index; it does
not verify embedding provenance. Both are offline operations: stop inference
before replacing its index.

`legacy/rabbitmq_rpc.py` is the old synchronous RabbitMQ search worker. It is not
started by Docker or the native launcher. `legacy/extract_db_vectors.py` is the
original dataset-specific index builder; it does not produce the current verified
FashionGen manifest. These files remain for reference; current search uses HTTP.

This reorganization moves source files only. Checkpoints, embeddings, image data,
index manifests and Compose volumes retain their existing locations and contents.
