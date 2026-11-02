# AuraFind: MRL cross-modal retrieval

The project combines a Next.js storefront, a Go gateway and a Python CLIP/FAISS service. Search is HTTP request/response. RabbitMQ is reserved for background indexing jobs; it is not in the search path.

## Phase notes

- [Phase -1 implementation and verification](notes/phase-minus1.md)
- [Phase 0 infrastructure](notes/phase0.md)
- [Phase 1 authentication and catalog](notes/phase1.md)
- [Phase 2 cart, checkout and orders preparation](notes/phase2.md)

The storefront uses English. MRL controls and timing are developer tools, not shopping UI.

## Portable demo (Phase 0)

Requirements: Docker Desktop with Linux containers, Docker Compose v2, Internet access on the first build/seed, and available host ports. No Shopify, SMTP provider or cloud account is required.

```sh
cp .env.example .env
docker compose up -d --build
docker compose ps -a
```

PowerShell: use `Copy-Item .env.example .env` for the first command. Do not overwrite an existing .env.

Startup order is PostgreSQL -> versioned migration -> demo seed -> inference -> gateway -> frontend. Storage and local email run alongside this chain. Migration and seed containers should exit successfully; long-running services should remain running/healthy. The first build compiles MinIO from its official release source and installs CPU-only PyTorch. First seed downloads public CLIP weights and saves them in persistent volumes; it can take several minutes.

- Storefront: http://localhost:3000
- Gateway/config: http://localhost:8080/api/search/config
- S3 endpoint: http://localhost:9000
- Storage console: http://localhost:9001
- Local email inbox: http://localhost:8025

If the existing native FashionGen app uses 3000/8080, stop those project processes first or set API_PORT, FRONTEND_PORT and NEXT_PUBLIC_API_URL together in .env. NEXT_PUBLIC_API_URL is baked into the frontend image, so rebuild frontend after changing it.

The demo has ten locally generated clothing illustrations and fictional USD prices, clearly marked as demo records in PostgreSQL. It uses real public pretrained CLIP embeddings at 512D only. It is NOT the fine-tuned MRL benchmark or a copy of FashionGen. Phase 1 provides email-verified accounts, catalog browsing/product details and SQL prices in search results. Cart/checkout and orders are later phases.

```sh
docker compose logs seed migrate
docker compose logs --tail 30 ai-worker core-api
docker compose run --rm seed
```

Re-seeding is intended for a stopped inference service; it replaces the demo index and keeps catalog IDs stable. Restart inference after a reseed. Live rebuild/hot-swap is a later phase.

```sh
docker compose stop ai-worker core-api frontend
docker compose run --rm seed
docker compose up -d ai-worker core-api frontend
```

Persistent volumes hold PostgreSQL, objects, model cache, demo images and indexes. `docker compose down` preserves data. Removing volumes explicitly destroys local state and is not part of routine startup.

Run infrastructure verification after the stack is ready:

```sh
docker compose --profile tools run --rm --no-deps verify
```

To test on separate ports while native FashionGen is running, use `--env-file infra/test.env.example` on every Compose command. This uses storefront 13000, gateway 18080, PostgreSQL 15432, storage 19000/19001 and mail 11025/18025.

Enable the optional broker with `docker compose --profile jobs up -d rabbitmq`. A background consumer is not implemented in Phase 0.

## Current FashionGen research/local app

The full validation database (32,528 vectors, 7,519 product IDs) and trained checkpoints remain local; they are not committed or copied into demo images. Existing FashionGen artifacts are not modified by Compose's named volumes.

```powershell
.\.venv\Scripts\python.exe ai-worker/manage.py start-local
.\.venv\Scripts\python.exe ai-worker/manage.py test --e2e
```

This path uses `ai-worker/vector_db/index_meta.json` to select the matching dataset/checkpoint. See the Phase -1 note for limitations and reproducibility checks. The latest checkpoint matches the currently cached FashionGen embeddings; best/latest cannot be swapped by merely changing metadata.

See [AI worker structure and commands](ai-worker/README.md) for API, training, extraction, benchmarks, scripts and tests. Configure FASHIONGEN_ROOT for your dataset. Earlier ViT-B/32 experiments and notebooks remain as research history, not production entry points.

## Attribution

Based on Matryoshka Representation Learning, Kusupati et al., NeurIPS 2022: https://arxiv.org/abs/2205.13147. Frontend started from Vercel Commerce; preserve frontend/license.md. MinIO is built from the official pinned source release under AGPL-3.0; its license is included in the image at /usr/share/doc/minio/LICENSE.
