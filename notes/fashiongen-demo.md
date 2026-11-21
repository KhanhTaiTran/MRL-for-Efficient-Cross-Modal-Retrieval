# FashionGen storefront demonstration

This deployment uses the actual local FashionGen validation corpus: 32,528
photos, 7,519 products, original descriptions, categories and brands available
in the extracted CSV. Retrieval uses the trained MRL ViT-B/16 checkpoint and
the existing verified image/text embeddings at 16/32/64/128/256/512 dimensions.
It does not generate replacement product photographs or train a new model.

The extracted CSV contains no price, stock, size or color inventory. Each
product therefore receives one default variant (unspecified size/color), an
explicitly synthetic USD price and initial stock of 20. Product metadata and
the storefront disclose this. Checkout remains a mock payment. Admin can
replace these values with genuine merchant data via `/admin`.

## Start on this machine

Docker Desktop must be running. From the repository root:

```powershell
# First deployment, or after changing application code:
.\infra\scripts\start_fashiongen.ps1 -Build

# On demo day, reuse the built images and installed corpus:
.\infra\scripts\start_fashiongen.ps1
```

Open http://localhost:13000. API is http://localhost:18080; PostgreSQL is
localhost:15432; local verification email is http://localhost:18025.

The Compose overlay reads these inputs as read-only mounts:

- `../FashionGen/extracted/val`: `metadata.csv` and `images/`.
- `ai-worker/vector_db`: validated native FAISS indexes and row mappings.
- `ai-worker/checkpoints`: original trained checkpoint.
- `$env:USERPROFILE/.cache/huggingface/hub/models--openai--clip-vit-base-patch16`:
  cached backbone/tokenizer for offline inference.

Override `FASHIONGEN_DATA_DIR` / `HF_B16_CACHE_DIR` in the shell if the files
are elsewhere. Ports and project name are in `infra/fashiongen.env.example`.
All further Compose commands must use that env file and both Compose files.

## Publication and data preservation

Startup backs up PostgreSQL into ignored `tmp/before-fashiongen-*.dump` and
stops the background publisher during the one-shot import. The importer checks
the source checkpoint/CSV/artifact hashes, every row/image/product/caption
mapping and FAISS shapes. It stages all photos in MinIO and the serving image
volume, copies the offline B/16 cache and writes an immutable version directory.
The serving checkpoint contains the unchanged model weights only; optimizer
and training state remain exclusively in the original checkpoint. Metadata
records both source and serving checkpoint hashes.

One SQL transaction creates catalog products/variants/images, publishes all
vector mappings, archives the ten illustration products and switches the active
version. Source files, existing users/orders and prior versions are retained.
The original demo objects are retained for history. Inference is recreated
because switching from B/32 to B/16 requires a restart. Once installed, repeated
startup preserves prices, stock consumed by checkout and subsequent catalog
rebuilds. The standard fixture seed also preserves this managed catalog.

The overlay raises the background rebuild image limit to 50,000. Rebuilding
the entire corpus on CPU re-encodes every image and can take a long time; it is
not needed for this initial deployment, which imports verified cached vectors.
Price/stock changes are read from SQL immediately. Catalog edits that change
retrieval content need a later rebuild to update embeddings.

Do not run fixture-only `verify_phase0.py` on this catalog: its assertions
explicitly require ten illustration products. Do not delete Docker volumes.

## Verification

```powershell
docker compose --env-file infra/fashiongen.env.example -f docker-compose.yml -f docker-compose.fashiongen.yml --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_fashiongen.py
```

This checks SQL/loaded version consistency, all six text retrieval dimensions,
self-image retrieval with the original photograph, SQL enrichment, product
gallery, wishlist and exact-price checkout/review on an actual FashionGen
product. A disposable customer is removed together with its session, review
and order; the purchased inventory unit is restored. No admin is created.

Phase 2 and Phase 4 HTTP suites can also run with this Compose configuration;
their fixtures are independent of the original ten products.

Verified on 5 November 2026 on the running local stack:

- Full import: 7,519 active FashionGen products, 32,528 images/vector mappings.
- Cold start and repeat startup script: installed catalog/version preserved;
  inference, gateway, frontend and infrastructure healthy.
- Importer provenance/multiline-caption tests (4), snapshot tests (2), Go tests
  with isolated SQL suites, `go vet`, TypeScript and Linux production builds pass.
- `verify_fashiongen.py`, Phase 2 and Phase 4 HTTP suites pass; disposable data
  removed, real-product test purchase stock restored.
- Browser: real photos and source note, Find Similar, product detail/gallery,
  original-photo upload and Compare all dims. All six direct searches retrieved
  the uploaded product with top similarity 1.0000. This is a self-retrieval
  consistency check, not an independent recall/accuracy benchmark.
- Screenshot: `tmp/fashiongen-search.png` (ignored local artifact).

## Suggested demonstration sequence

1. Show the FashionGen source note and browse actual product photos/categories.
2. Search `blue denim jacket`, `black leather boots`, or `red dress` in English.
3. Upload a photograph from the FashionGen source folder, or use Find similar.
4. Open `/image-search` to compare direct retrieval across supported dimensions;
   the home page uses adaptive 64D candidate search plus 512D reranking.
5. Open a result, inspect its gallery and save it to the wishlist.
6. Sign in, purchase one unit, inspect order history and write a verified review.
7. As an existing admin, edit stock/price or moderate the review.

Explain that retrieval uses the actual FashionGen/MRL system while payment and
merchant price/inventory values are demonstration data. Do not describe prices
or stock as measured FashionGen attributes, or claim a performance guarantee
from one local demonstration.
