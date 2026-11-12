# Product-level hybrid text search

Text search combines CLIP image similarity and field-weighted BM25, using one
immutable model/vector/document snapshot. Image search is unchanged. Existing
clients default to dense retrieval; callers may explicitly request hybrid.

## Retrieval and scores

`search_mode=direct|adaptive` controls MRL retrieval independently from
`retrieval_mode=dense|hybrid`. Adaptive product retrieval selects up to 200 unique
products at 64D, then reranks their images at 512D. Direct uses the requested
dimension. BM25 independently contributes up to 200 products, using Lucene IDF,
`k1=1.2`, `b=0.75`, and field weights brand/name=3,
category/subcategory/tags=2, description=1. Query and document normalization uses
NFKC, casefold, punctuation boundaries, and English Snowball stemming; brands
retain their normalized words.

RRF combines the two product rankings with equal weights and `k=60`. Only actual
branch membership contributes an RRF rank. Lexical-only products get image
cosines to choose a photo, without gaining a fabricated dense rank. Recognized
brand families are prioritized for short shopping queries (up to eight normalized
words), while other brands remain available afterward;
residual query terms rank products within that group. Longer descriptions retain
BM25/RRF relevance without a brand-first tier. Catalog-derived Adidas
and Diesel aliases and the normalizer version are covered by the artifact hash.

`similarity_score` always means cosine in the effective scoring dimension.
`rank_score` means RRF score and must not be rendered as a similarity percentage.
Each internal candidate also retains alternate photos and their cosines. The
gateway validates their versioned SQL mappings and uses the highest-scoring
active photo from the same product.

## HTTP contracts

- `POST /api/search/text`: existing form fields `query`, `mrl_dimension`, and
  `search_mode`, plus optional `retrieval_mode` (default `dense`). Explicit hybrid
  returns up to ten unique eligible products after catalog hydration.
- `GET /api/products?q=...`: uses the same product candidate service. Category,
  min/max price, featured, active product, and active image eligibility are
  applied before either retriever's cutoff. A blank query keeps SQL browsing.
- `POST /infer/search/candidates`: internal JSON request with `query`,
  `mrl_dimension`, `search_mode`, `retrieval_mode`, and optional
  `eligible_product_ids`. An omitted eligibility list means the entire snapshot;
  an explicit empty list means no products. Returns the complete bounded pool,
  `index_version`, `truncated`, and `image_candidates` for each product.
- Search metadata exposes requested/effective retrieval mode,
  `lexical_available`, and `fallback_reason`. A legacy index without lexical
  artifacts reports dense fallback. A declared hybrid artifact that fails
  validation is rejected; a live reload keeps the prior snapshot.

Catalog queries default to relevance sorting; blank queries default to newest.
Explicit price/name/newest sorting orders the complete hydrated pool before
paging. `pagination.total` counts that pool, not all potentially relevant catalog
items. `search.truncated=true` signals a branch limit; the UI calls these
"ranked matches". Each page reflects the current catalog at request time.
Both `/discover?q=...` and `/search?q=...` use the shared hybrid pipeline when
enabled. Submitting a new query from `/search` retains filters and resets paging.

## Build and migrate an index

All builders now write a hashed `search_documents.json` containing one document
per product and complete vector ownership. Managed rebuilds snapshot category,
subcategory, and tags along with the existing name/brand/description. SQL imports
regenerate documents with SQL UUIDs. The native metadata-only upgrader validates
the source CSV provenance and all row mappings, then copies the existing vectors
to a new sibling directory without changing the source or checkpoint.

From the repository root in PowerShell (use actual absolute paths):

```powershell
.\.venv\Scripts\python.exe ai-worker/manage.py upgrade-hybrid-index `
  --source C:\path\ai-worker\vector_db `
  --csv C:\path\FashionGen\extracted\val\metadata.csv `
  --output C:\path\ai-worker\vector_db.hybrid-v1
$env:VECTOR_DB_DIR = 'C:\path\ai-worker\vector_db.hybrid-v1'
.\.venv\Scripts\python.exe ai-worker/manage.py start-local
```

The upgrade does not activate a running process. Native startup and E2E honor
`VECTOR_DB_DIR`. Managed catalog rebuilds publish documents and vectors together
through the existing version activation mechanism. Keep the old directory or
catalog version to roll back.

Docker uses its own named volume and SQL active version. Repository changes and
native index upgrades do not update running containers or that volume. Run
`infra/scripts/start_fashiongen.ps1 -Build` after pulling new source: it rebuilds
the images, stops the index publisher, then runs the SQL metadata-only upgrade
before recreating application services. Existing products, stock, orders,
reviews, checkpoints, and FAISS vectors are preserved.

The underlying command is `python -m ai_worker.indexing.upgrade_hybrid`, run in
the new AI image with `DATABASE_URL` and `VECTOR_DB_DIR`. `--dry-run` validates
without publishing. It creates a new immutable version and atomically copies
SQL vector mappings/activates it. A valid hybrid active version is an idempotent
no-op. It refuses running jobs, concurrent publishers, corrupt artifacts, or
ownership mismatches. `--source-version UUID` explicitly upgrades a retained
version when recovering an incorrect active pointer; it also guards the actual
previous active version against concurrent changes. Retain both version IDs
when recording rollback instructions.

## Evaluation and promotion

`benchmark-hybrid` includes 60 short queries (20 development, 40 held out), ten
deterministic full-caption controls, and five unsupported queries. It compares
legacy dense, product-level dense, BM25, and hybrid using the same query embedding.

```powershell
.\.venv\Scripts\python.exe ai-worker/manage.py benchmark-hybrid `
  --output C:\path\tmp\hybrid-report.json `
  --export-pool C:\path\tmp\hybrid-pool.jsonl --repeats 3
```

Use the exported pooled candidates for independent graded relevance review
(0=irrelevant, 1=partial, 2=relevant, 3=fully satisfies the query). Review catalog
fields without viewing method/rank information. Qrels are a JSON object with
`source: "independent_review"` or `"human"`, `independently_judged: true`,
`judgment_modality: "catalog_text"` or `"image_and_catalog"`, and
`judgments: {query_id: {product_id: grade}}`. Metadata-proxy diagnostics are
explicitly labeled and cannot pass the promotion gate.
Copy `index_version`, `queries_sha256`, and `search_documents_sha256` from the
report into the qrels envelope so promotion cannot reuse stale judgments.

Run again with `--qrels C:\path\qrels.json --gate`. The gate requires complete
held-out/control judgments, at least 10% held-out nDCG@10 improvement over
product-dense, no query-group regression above 5%, no material caption-control
regression, and lexical+fusion p95 at most 50ms. Reports include Precision@10,
brand accuracy, unique-product counts, latency, provenance, and judgment modality.

The storefront promotion flag now defaults on after the passing benchmark below.
`HYBRID_SEARCH_ENABLED=1` enables hybrid for inference (in `.env` for Compose).
`/api/search/config` advertises
`text_retrieval_mode_default=hybrid` only when the flag is enabled and a valid
lexical artifact is loaded. Both frontend text flows send that mode explicitly.
Set the flag back to `0` to restore the dense storefront default.

The release benchmark used 75 queries and 2,048 independent, blind agent judgments
of catalog text covering all held-out/control pooled candidates. It was not a
human or image relevance study. On 40 held-out short queries, nDCG@10 improved
from 0.6572 (product-dense) to 0.8985 (hybrid), a 36.72% relative gain. Full-caption
control nDCG@10 improved from 0.7017 to 0.8483. No short-query group regressed;
lexical+fusion p95 was 10.25ms and hybrid retrieval p95 was 17.39ms, excluding the
shared text encoder. Gate passed with no unjudged pooled candidates. Local
evidence is retained in `tmp/hybrid-benchmark-final.json` and
`tmp/hybrid-qrels-independent-v2.json`.

## Verification

Run `python ai-worker/manage.py test --e2e` with the repository virtualenv.
`test_hybrid_catalog_e2e.py` additionally uses an explicitly configured
`HYBRID_TEST_ADMIN_DATABASE_URL` PostgreSQL instance, creates its own database, and
cleans up its own services/database. Run it with
`python -m tests.test_hybrid_catalog_e2e` from `ai-worker/`.
It checks real checkpoint vectors, SQL filters, paging, cross-route rank parity,
and alternate-image hydration. Go tests use `TEST_DATABASE_URL` for SQL suites.
