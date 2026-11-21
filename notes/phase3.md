# Phase 3: catalog administration and live index rebuilds

Implemented 3 November 2026. Phase 2 checkpoint: `6b5e6fa`.

## Scope

`/admin` supports product creation/editing/archive/reactivation, variant creation,
editing/disabling, inventory, image upload/order/primary/removal, rebuild jobs
and retained versions. Customer accounts cannot use admin APIs. Roles are read
from SQL on every authenticated request. Storefront text stays English.
Review writing/moderation, order fulfillment, payments, arbitrary checkpoint
import and model training are outside this phase.

## API and catalog consistency

All `/api/admin` routes require a verified admin session, validate browser Origin,
disable caching and have a bounded context.

- `GET /products`: includes archived products; supports `page`, `limit`, `q`.
- `POST /products`, `GET /products/:id`, `PUT /products/:id`.
- `DELETE /products/:id`: archive; reactivate with PUT.
- `POST /products/:id/variants`, `PUT /products/:id/variants/:variant_id`.
- `DELETE /products/:id/variants/:variant_id`: disable.
- `POST /products/:id/images`: multipart `image`, optional `alt` and `primary`.
- `PUT /products/:id/images/:image_id`: `alt`, `position`, `is_primary`.
- `DELETE /products/:id/images/:image_id`: retire; promote the next primary.
- `GET /index/jobs`, `POST /index/jobs`, `GET /index/versions`.

Product writes use integer `price_cents` and the last-read `revision`; stale
updates return 409. Variant updates require `expected_stock`, preventing stale
admin forms from overwriting stock consumed by checkout. The existing composite
FK enforces default variant ownership. Edits increment `search_revision` and
mark search pending. Admin prices explicitly use USD cents.

Images must decode as PNG/JPEG, at most 10 MB, 20 million pixels and 8000 pixels
per side. The gateway re-encodes PNG, strips input metadata and generates an
immutable object key. A product supports 20 active images. Retired images retain
SQL identity and S3 bytes for historical mappings and order snapshots. Public
catalog/search filter retired images. Storage and SQL are separate: a failed SQL
write after upload may leave an unreferenced object. Automatic garbage collection
is not included.

## Rebuild and activation

The new default `index-worker` Compose service runs
`python -m ai_worker.indexing.worker` and consumes PostgreSQL `ai_index_jobs`.
RabbitMQ stays optional and outside search. A SQL queue avoids a separate
database-to-broker delivery step. A partial unique index permits one open job;
concurrent submissions return that job. A session advisory lock permits one
consumer. A replacement consumer marks interrupted running jobs failed so the
admin can explicitly retry.

The worker captures active SQL product/image identities and revisions, downloads
MinIO images, and generates real embeddings with the active validated model,
preprocessing and supported dimensions. Demo rebuilds remain pretrained CLIP
512D, not trained MRL. Products without images are excluded. Builds support
1–20,000 active images. Edits during a build remain pending when their revision
no longer matches the captured revision.

Complete artifacts are finalized under `vector_data/versions/<uuid>` before one
SQL transaction publishes the new version, vector mappings, active flag and job
completion. Each version retains its checkpoint, image/text indexes, paths,
captions, product IDs and SHA-256 manifest. Legacy seed artifacts are archived
first. Failures preserve the active version. Historical versions/mappings and
immutable image files are retained; no cleanup or rollback-selection UI exists.
Failed `.building` directories may remain for diagnosis and are never selected.

Inference polls SQL every three seconds. It validates a candidate independently
and publishes one engine dictionary reference. Every search pins its reference
for the complete request and returns that version with its vector IDs; SQL
enrichment uses the exact returned version. In-flight searches keep the old
engine. Corrupt candidates are rejected while the old engine stays ready.
Live reload accepts the same checkpoint; switching models requires a restart.
The admin screen distinguishes published versions from the version serving
search. Job completion means SQL publication; activation follows validation.

Native research mode without `DATABASE_URL` keeps its existing manifest and
checkpoint behavior. Compose rebuilds never touch native FashionGen artifacts.

## Run and verify

For an existing healthy demo:

```powershell
docker compose --env-file infra/test.env.example run --rm --no-deps migrate
docker compose --env-file infra/test.env.example build ai-worker core-api frontend
docker compose --env-file infra/test.env.example up -d --no-deps ai-worker core-api frontend index-worker
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_phase3.py
```

For a fresh stack follow README startup. Once a managed catalog is active, seed
exits without replacing catalog, index or stock. Normal Compose startup therefore
preserves admin rebuilds. Re-seeding does not reset any existing admin password.

The gateway receives `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` and
optional `MINIO_SECURE=true`; Compose supplies internal values. Inference and
indexing receive `DATABASE_URL`. No extra public service port is exposed.

```powershell
Set-Location core-api
$env:TEST_DATABASE_URL='postgres://aurafind:aurafind_dev@localhost:15432/aurafind?connect_timeout=5'
go test ./... -count=1
go vet ./...
```

Tests cover admin 401/403 and immediate role changes, revision/stock conflicts,
variants, image validation/storage/primary promotion, retained mappings and
concurrent enqueue. Snapshot tests cover in-flight version isolation and corrupt
artifacts. The real HTTP verifier injects a missing object, confirms failure
leaves search intact, then rebuilds the demo with continuous searches and checks
activation and retained old mappings. It removes temporary users/products/objects;
successful real catalog versions and job history remain. Successful test rebuilds
exclude test-only products so no historical fixture identity must be removed.

Run Phase 0/1/2 verifiers after Phase 3. Phase 0 expects the original ten demo
products/variants, so use an unextended seeded catalog for its fixture counts.
The worker regression command includes snapshot tests. Migration verification
tests all three migrations up/repeat/down/up only in a fresh temporary database.

Verified on 3 November 2026: Go tests/vet and isolated SQL suites, TypeScript,
Linux production builds, Phase 0/1/2/3 HTTP suites, snapshot tests and all five
native FashionGen regression groups. Browser checks covered product creation,
variant creation/stock edits, image upload, reload persistence, archive and logout.
The approved temporary browser admin, sessions, product and object were removed.
Cold-start loaded the published catalog version; running seed preserved it.
One Phase 0 image check hit the existing 15-second inference timeout while native
model regression ran concurrently; its isolated rerun passed. This CPU demo does
not establish a latency guarantee under competing model workloads.

Reference: [official MinIO Go SDK](https://github.com/minio/minio-go).
