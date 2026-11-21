# Phase 2: cart, checkout and customer orders

Prepared 2 November 2026. Scope follows `phase1.md`: cart/checkout are Phase 2.
Implemented and verified 3 November 2026. The design contract below describes
the shipped local demo behavior.

## Delivered behavior

Verified accounts have a persistent PostgreSQL cart, mock checkout and private
order history. Product details add the selected variant to the cart with an
absolute quantity of one; the cart page supports quantities 1–99 and removal.
The homepage cart buttons now navigate to the real cart and load its quantity.
Account pages link to order history. Sign-in, registration and email verification
preserve the return path.

`/cart`, `/checkout`, `/account/orders` and `/account/orders/:id` use the existing
in-memory access-token/refresh flow. Checkout clearly states that payment is
simulated and no money is charged. Shipping is zero; USD is the only supported
checkout currency. No real payment credentials or provider are used.

Commerce responses use integer `price_cents`, `subtotal_cents`, `shipping_cents`
and `total_cents`; SQL stores exact NUMERIC values. The order total limit is
999,999,999,999 cents, matching NUMERIC(12,2). Carts support at most 100 variants.
Cart reads expose `can_checkout` and per-item stock/availability.

Checkout receives `{shipping_address, currency, items}`. Each item contains
`variant_id`, `quantity` and `price_cents`. Address fields are `name`, `line1`,
`line2`, `city`, `region`, `postal_code`, `country`; country is a two-letter code.
Quote lines are normalized/sorted before hashing. The `Idempotency-Key` header
is required (8–128 printable non-space ASCII characters). First success returns
201; exact replay returns 200 with `replayed: true`; changed payload returns 409.
Order ownership failures return 404. Responses are private (`Cache-Control:
no-store`). Browser mutation Origins and CORS idempotency headers are checked.

The checkout screen stores the original request/key in per-account tab session
storage before sending. Network/503 failures retain it for retry, including
after reload; definitive validation/conflict responses require a fresh review.
Successful retries resolve to the original order even after cart clear. Closing
the tab clears this browser recovery state. No confirmation email or durable
email outbox is included in this phase.

Migration 000002 adds the maximum cart quantity constraint. Checkout and cart
mutations lock the owning user first; checkout locks products/variants/cart rows
in deterministic order, validates the quote, guards stock updates, snapshots
order items/address and clears the cart in one transaction. Commerce requests
have a ten-second context deadline. Gateway HTTP read/header/write/idle timeouts
are now explicit.

## Verification and commands

On an existing healthy Phase 1 demo stack (isolated test ports):

```powershell
docker compose --env-file infra/test.env.example run --rm --no-deps migrate
docker compose --env-file infra/test.env.example build core-api frontend
docker compose --env-file infra/test.env.example up -d --no-deps core-api frontend
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_phase2.py
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_phase1.py
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify
```

For a fresh/stopped stack, follow the README startup procedure first. Do not
reseed a running inference index to apply this phase; only migration/application
services change. Migration 000001 remains unchanged.

```powershell
Set-Location core-api
$env:TEST_DATABASE_URL='postgres://aurafind:aurafind_dev@localhost:15432/aurafind?connect_timeout=5'
go test ./... -count=1
go vet ./...
```

Verified: Go tests/vet, isolated-schema database integration tests, frontend
TypeScript and Linux production images, and Phase 0/1/2 HTTP suites. Tests cover
wrong quantities, stock/availability, ownership, stale/tampered quotes, concurrent
same-key replay, different-payload conflicts, last-unit competition, injected
mid-transaction rollback, immutable order snapshots, free/fractional prices,
maximum supported total and the cart-update/checkout race. Database tests also
verify competing multi-product purchases acquire locks consistently.
Migration up/repeat/down/up passes in a fresh temporary database.
The Phase 2 HTTP verifier creates/removes only its own temporary users/products/orders; seeded
demo stock is untouched.

Browser verification: sign-in returns to product, selected variant adds to cart,
quantity update survives reload, address form submits a mock order, confirmation
and order history show the exact $24.68 total, and logout succeeds. Browser-test
fixtures are disposable and separate from seeded products.

## Preparation review

The source reorganization contained a startup blocker: model imports did not
match the model module filename. The canonical module is now
`ai_worker.models.mrl` in `models/mrl.py`, reflecting `MRL_CrossModal_Model`.
All consumers and documentation use that name; model code is unchanged.
Previously built Docker images did not expose the current-source import failure.

Rechecked on 2 November 2026: Go tests and vet, the isolated PostgreSQL catalog
integration test, frontend TypeScript, and both Phase 0/1 Compose verifiers pass.
Current-source worker readiness and all five FashionGen regression groups also
pass with the local matching checkpoint and 32,528-vector index.
The Compose verifiers use existing service images, not a full rebuild of every
service. Native Windows production compilation/type checking/static page generation
passes, but standalone packaging fails with Windows EPERM on symlink creation;
the current-source Linux Docker frontend production image builds successfully.

## Entry gate

- Keep Phase 1 auth, catalog and search working; run Go tests/vet, frontend
  TypeScript/build, worker readiness/regression and both Compose verifiers.
- Run the catalog integration test with `TEST_DATABASE_URL` explicitly set;
  ordinary `go test ./...` skips it when that variable is absent.
- Checkpoint the existing broad source reorganization and Phase 0/1 changes
  before adding commerce work. Include the new package files as well as deletions;
  do not commit local checkpoints, embeddings, images or secrets.
- Use new numbered migrations for schema changes. Do not edit migration 000001
  on databases that already applied it.

## Decisions for the first implementation

- Verified, signed-in customers only; persistent cart belongs to the authenticated
  SQL user. Guest carts and merging are deferred.
- USD demo checkout, zero shipping fee, mock payment only. Clearly label simulated
  payment. Real payment providers, tax and shipping integrations are deferred.
- Cart quantities are absolute values, not increment operations. Set an explicit
  maximum of 99 per variant and reject unavailable/inactive products and variants.
- Cart does not reserve stock. Read and revalidate current price/availability at
  checkout. An outdated checkout quote returns a conflict for customer review.
- Use exact integer cents or decimal arithmetic in Go for all order calculations;
  the catalog's existing float64 display fields are not a checkout money model.
- Keep product retrieval independent of checkout: no inference request or broker
  job is needed to place an order.

## API contract

All routes below require `AuthHandler.RequireUser()`. Derive ownership from the
authenticated user, never a client-supplied user ID. Return 404 for another user's
cart item or order. Apply trusted-Origin checks to browser mutations; the current
auth Origin guard is mounted only under `/api/auth`.

- `GET /api/cart`: items, current variant prices, availability and exact totals.
- `PUT /api/cart/items/:variant_id`: JSON `{ "quantity": 2 }`; upsert absolute
  quantity (1–99). Repeating a request leaves the same quantity.
- `DELETE /api/cart/items/:variant_id`: remove owned item; repeat is successful.
- `POST /api/checkout`: shipping address, expected cart quote and a required
  `Idempotency-Key` header. Success returns the created order. Repeating the same
  key and canonical payload returns that same order; changed payload returns 409.
- `GET /api/orders`: paginated orders for the current user, newest first.
- `GET /api/orders/:id`: owned order with immutable item/address/price snapshots.

Use 400 for malformed input, 401 for missing/expired auth, 404 for absent/foreign
resources, 409 for stock/price/cart/idempotency conflicts and 503 for temporary
dependency failure. Include stable machine-readable error codes for UI recovery.
Add `Idempotency-Key` to the gateway CORS allowed headers or browser checkout
preflight will fail.

## Checkout transaction

1. Validate and canonicalize the address, quote, currency and bounded idempotency
   key. Hash the canonical request, not raw JSON. The quote includes variant IDs,
   quantities and expected prices so a changed cart is a different request.
2. Begin one PostgreSQL transaction. Lock the owning user first, following auth's
   user-first lock order. Serialize cart mutations and checkout with the same
   user lock so adding an item cannot race with checkout's cart deletion.
3. Look up `(user_id, idempotency_key)` before validating the current cart. An
   existing matching order must replay even after the original cart was cleared.
4. Lock cart rows and affected product/variant rows in deterministic ID order.
   Validate nonempty cart, active products, available variants, one supported
   currency, quantities and expected prices. Return 409 on a changed quote.
5. Decrement inventory with stock guards, checking affected rows. Calculate
   exact totals server-side; never accept client totals as authoritative.
6. Insert the order and item snapshots, clear only the purchased cart rows and
   commit. Failure must roll back stock, order and cart changes together.
7. Send any confirmation email after commit. Mail failure must not undo the order
   or cause a retry to purchase again. A durable outbox is later work.

The schema already provides `cart_items`, `orders`, `order_items`, positive
quantity/nonnegative stock checks and per-user idempotency uniqueness. Verify any
additional constraints/indexes in migration 000002, including a bounded cart
quantity if enforced in SQL. Define a supported checkout total limit so arithmetic
and NUMERIC(12,2) overflow are rejected before writing.

## Delivery sequence

1. Backend cart repository/handlers and database integration tests.
2. Transactional checkout and retry/concurrency tests before wiring the UI.
3. Customer order list/detail API with ownership tests.
4. Product Add to cart using the selected variant, cart page, checkout form,
   mock-payment confirmation and account order history. Preserve `next` through
   registration and verification for checkout return navigation.
5. Add `infra/scripts/verify_phase2.py`, update README and rerun Phase 0/1 checks.

Use `frontend/lib/api/client.ts` for authenticated requests; never reuse legacy
Shopify cart actions for the local SQL cart. Retrying checkout must reuse the
original idempotency key and payload after a timeout. Generate a new key only
for a new purchase attempt, not every network retry.

## Acceptance tests

- Unauthenticated requests fail; one user cannot read/change another user's data.
- Add/update/remove persist after reload; zero, negative, fractional and excessive
  quantities fail; disabled variants and inactive products cannot be purchased.
- Two users competing for the last unit produce exactly one order and no negative
  stock. Multi-item competing checkouts acquire locks consistently.
- Concurrent identical checkout retries produce one order/stock decrement. Same
  key with a different canonical payload returns 409, including after cart clear.
- Client price tampering and stale quotes fail; exact totals cover fractional
  prices, free products and maximum supported quantities/totals.
- Injected mid-transaction failure leaves inventory, cart and orders unchanged.
- Concurrent cart changes do not disappear into an order the customer did not quote.
- Later catalog edits do not alter historical order item or address snapshots.
- Session expiration, refresh, logout and recovery continue to work during cart
  and checkout flows. Cross-origin preflight permits the idempotency header.
- Browser flow: select variant, add, edit quantity, reload, sign in if needed,
  checkout, retry after simulated response loss, then inspect order history.

## Follow-ups identified during review

- Resolved in Phase 2: gateway HTTP timeouts and bounded commerce contexts.
- OTP email currently sends while a SQL transaction is open. Slow SMTP holds the
  user lock, and a successful send followed by a failed commit can deliver an
  unusable code. Consider a transactional outbox when making delivery durable.
- No `.github` CI workflow is present. Add automated Go, TypeScript and lightweight
  worker checks so future Phase 2 changes cannot silently break Phase 1.
