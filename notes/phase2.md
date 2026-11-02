# Phase 2 preparation: cart, checkout and customer orders

Prepared 2 November 2026. Scope follows `phase1.md`: cart/checkout are Phase 2.
This document is an implementation contract; these endpoints are not implemented yet.

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

- `core-api/cmd/server/main.go` uses Gin `Run`, without explicit HTTP read-header,
  write or idle timeouts. Configure an `http.Server` before public deployment;
  checkout also needs bounded database transaction contexts.
- OTP email currently sends while a SQL transaction is open. Slow SMTP holds the
  user lock, and a successful send followed by a failed commit can deliver an
  unusable code. Consider a transactional outbox when making delivery durable.
- No `.github` CI workflow is present. Add automated Go, TypeScript and lightweight
  worker checks so future Phase 2 changes cannot silently break Phase 1.
