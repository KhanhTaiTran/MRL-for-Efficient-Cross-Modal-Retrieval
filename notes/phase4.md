# Phase 4: verified-purchase reviews, moderation and wishlist

Scope confirmed 3 November 2026. Builds on Phase 3 commit `1b43dde`.
Uses the existing reviews/wishlists tables; no new migration is required.
Review images/videos remain deferred.

## Customer flows

Product detail pages show paginated visible reviews, first-name attribution,
rating and verified-purchase status. Signed-in customers can create/edit one
review per product only if they own a confirmed, paid order containing it.
The API chooses the qualifying order; clients cannot supply an order/user ID or
forge verification. Ratings must be integers 1–5, comments at most 4000 UTF-8
bytes. Refunded, cancelled and another user's orders cannot qualify a write.
Editing a hidden review does not unhide it. Previously submitted reviews are
not automatically deleted if an order is later refunded; admins can hide them.
The existing catalog/search review aggregates exclude hidden reviews.

Customers can save products from product details and visit `/wishlist` via the
Saved navigation link. Saved products persist in SQL by authenticated user.
Saving/removing is idempotent. Archived products are omitted from the list while
saved identity is retained, allowing removal and restoration after reactivation.
Wishlist responses are private, paginated and never accept a client user ID.

## Moderation

`/admin/reviews` lists reviews and lets admins hide/show them. The API checks the
current SQL role through the existing session guard. Hidden content is omitted
from public lists and rating summaries, but remains visible to its author in
the authenticated eligibility response and to admins. Moderation is visibility
control, not a pre-publication approval queue. No hard-delete flow is provided.

## Routes

- Public `GET /api/products/:handle/reviews`: visible reviews and pagination.
- Authenticated `GET /api/products/:handle/review-eligibility`: eligibility and
  the current user's own review, including moderation status.
- Authenticated `PUT /api/products/:handle/review`: `{rating, comment}` upsert.
- Authenticated `GET /api/wishlist`, `PUT/DELETE /api/wishlist/:product_id`.
- Admin `GET /api/admin/reviews`, `PATCH /api/admin/reviews/:id` with
  `{is_hidden: boolean}`.

Lists accept `page` and `limit`. Mutations validate Origin and use the existing
in-memory access token / rotating refresh session. Request contexts are bounded;
responses containing account data disable caching. No new storage permissions,
index jobs, email delivery or external accounts are needed.

## Verification

```powershell
docker compose --env-file infra/test.env.example build core-api frontend
docker compose --env-file infra/test.env.example up -d --no-deps core-api frontend
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_phase4.py
```

The HTTP suite creates disposable local customers/admin/product and a real mock
checkout, tests cross-user/refunded/cancelled eligibility, invalid input and
forged fields, concurrent review upsert, moderation authorization, hidden edits,
visible aggregate updates, wishlist privacy/idempotency/pagination/archive,
Origin protection and storefront routes. Cleanup removes reviews before orders,
then users (including sessions) and products; demo stock is untouched. Running
the suite requires permission to create its temporary local admin account.

Also run Go tests/vet, frontend TypeScript/production build and prior Phase 0–2
HTTP suites for compatibility. Phase 3 indexing code/model artifacts are unchanged.

Verified 3 November 2026: Go tests with isolated SQL suites and vet, TypeScript,
Linux gateway/frontend production builds, the Phase 4 HTTP suite and Phase 0–2
HTTP regressions all pass. Browser checks confirm the public review section and
that saving as a guest returns through sign-in to the selected product.
Temporary Phase 4 accounts, sessions, reviews, order and product were removed.
