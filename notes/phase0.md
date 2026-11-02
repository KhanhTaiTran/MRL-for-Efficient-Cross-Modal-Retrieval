# Phase 0: portable infrastructure and search-ready demo

## Deliverables

- PostgreSQL 16 with fifteen application tables and reversible versioned migrations.
- One-shot migrate service; SQL files are NOT placed in PostgreSQL initdb.
- MinIO S3 storage built from the official pinned release source (Hub image unavailable, Quay returned 401 during implementation).
- Private reviews bucket and publicly readable product objects; initialization in idempotent seed.
- MailHog local SMTP/inbox; optional RabbitMQ jobs profile.
- One-shot seed creates demo admin, products, variants, object keys, index version and version-specific vector mappings.
- Real CLIP-generated demo index, saved checkpoint and metadata on persistent volumes.
- Separate liveness/readiness; missing index reports 503 readiness, invalid existing model/index fails closed.
- Containerized frontend, correct build-time public API URL and build contexts excluding private datasets/checkpoints.

## Startup contract

Run `docker compose up -d --build` after copying .env.example to .env. Seed completes before inference starts. Gateway verifies database and inference readiness. No dependency cycle requires an unseeded inference server to become ready first.

Initial schema is 000001; future changes use a new numbered migration. Migration rollback is for explicit recovery/testing, not startup. A single initial migration can contain all fifteen tables.

## Demo versus research

Default Compose demo: ten synthetic garment illustrations, fictional prices, zero reviews, public pretrained CLIP 512D. This tests infrastructure without requiring the private dataset or trained checkpoint. It is not evidence for MRL quality. Current FashionGen artifacts and native services remain separate.

The first run requires public package/model downloads but no third-party account. This is not an offline distribution of model weights. Native FashionGen and Compose can coexist when host ports differ.

## Implementation details

Core API connects PostgreSQL only when DATABASE_URL is configured, preserving existing native development. Inference with no index stays live/not-ready; seed/restart is needed to load it. Existing invalid manifests are rejected instead of silently falling back to base CLIP.

Indexes and mappings are versioned together; one active SQL version enforced by a unique partial index. Default variant FK ensures a product cannot point to another product's variant. Stock, quantity, totals and ratings have database constraints. Refresh-token family fields and order request_hash prepare later auth/checkout work, without claiming those endpoints already exist.

## Verification

Verified on 29/10/2026 with Docker Engine 29.1.3 and `infra/test.env.example`:

- All six long-running services healthy: PostgreSQL, MinIO, MailHog, inference, gateway, frontend.
- Migration and seed one-shot services exit 0.
- Fifteen application tables plus schema_migrations; version 1, not dirty.
- Migration up / repeated up / down / up passed in fresh temporary databases; only those temporary test databases were dropped.
- Repeated final seed produced the same version UUID f4aae988-c2cf-51c0-b0fb-f1462772f7e9, with 10 products, 10 variants and 10 active mappings (no duplicate rows).
- Negative stock and cross-product default-variant assignments rejected by database constraints.
- Product object GET works, exactly ten managed demo objects exist, reviews bucket is private.
- Real text search and image self-match through Go -> Python pass; self-match score > 0.999.
- SQL active UUID matches inference's active index version and ten-vector config.
- Frontend, console and MailHog UI return HTTP success inside the Compose network; local SMTP accepts verification email.
- Gateway Go tests pass; no-index liveness/readiness regression passes.
- Existing 32,528-vector FashionGen Phase -1 regression rerun passes all five groups. Its artifacts were not modified.
- Frontend production image builds with standalone output; AI runtime is CPU-only PyTorch 2.6.0 / torchvision 0.21.0.

Commands:

```sh
docker compose --env-file infra/test.env.example up -d --build
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify
```

```powershell
.\.venv\Scripts\python.exe infra/scripts/test_migrations.py --env-file infra/test.env.example
.\.venv\Scripts\python.exe ai-worker/manage.py test-readiness
.\.venv\Scripts\python.exe ai-worker/manage.py test
```

Running isolated endpoints: storefront http://localhost:13000, gateway http://localhost:18080, S3 http://localhost:19000, storage console http://localhost:19001, email http://localhost:18025. Native FashionGen remains on 3000/8080. Windows refused the initial 5432 bind; the test environment therefore publishes PostgreSQL on 15432. No Docker volumes containing research data were removed.

Phase 1 auth/product/cart APIs and SQL enrichment are outside this phase. Demo prices are fixtures and are not yet surfaced by the storefront's search response. Live index rebuild and historical index artifact retention remain Phase 3 work.

Primary implementation references:
- Docker startup conditions: https://docs.docker.com/compose/how-tos/startup-order/
- PostgreSQL migration driver: https://github.com/golang-migrate/migrate/tree/master/database/postgres
- Official MinIO source release: https://github.com/minio/minio/tree/RELEASE.2025-04-22T22-12-26Z
