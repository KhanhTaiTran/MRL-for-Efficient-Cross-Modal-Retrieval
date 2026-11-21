# Phase 1: authentication, catalog and storefront

## Scope

Implements Phase 1 of the reviewed plan: Auth + Product API + Homepage. Catalog
details and version-aware search enrichment connect the existing retrieval API
to PostgreSQL. Cart, checkout, orders, admin CRUD/index rebuild and writing reviews
remain later phases.

All storefront text is English. Compose still uses its ten demo illustrations
and fictional USD prices; this phase does not import FashionGen into SQL or turn
the demo CLIP model into a trained MRL model. Native FashionGen artifacts retain
their current paths and contents.

## Authentication

Routes under `/api/auth`:

- `POST /register`: normalize email, hash password with bcrypt, send email OTP.
- `POST /verify-email`: consume OTP, verify email and establish a session.
- `POST /resend-verification`: issue another code for an unverified local account.
- `POST /login`: require correct password and verified email.
- `POST /refresh`: rotate the opaque refresh cookie and return a new access JWT.
- `POST /logout`: revoke the session family and clear its cookie.
- `POST /forgot-password`, `POST /reset-password`: email-code recovery and revoke
  all existing sessions after changing the password.
- `GET /me`, `PATCH /me`: authenticated account details/name updates. Role and email
  cannot be changed through the profile payload.

Access JWTs expire after 15 minutes and validate HS256, issuer, audience and
expiry. They live in browser memory. The seven-day refresh token is a random
256-bit opaque value, stored as a SHA-256 hash in PostgreSQL and sent in an
HttpOnly, SameSite=Lax cookie scoped to `/api/auth`. Refresh rotates tokens under
database row locks. Reusing a revoked token revokes its entire family. Protected
requests also check the session family in SQL, so logout/reset invalidate access
immediately.

OTPs use six digits, expire after ten minutes and are stored as HMAC hashes bound
to the user and purpose. Each code permits five guesses. Issuance has a 60-second
cooldown and a maximum of five codes per purpose/user/hour. Auth endpoints also
have an IP limiter for the current single-instance gateway. Browser mutations
validate Origin; untrusted Origins cannot refresh/logout using ambient cookies.
The gateway does not trust forwarded client-IP headers by default.

The frontend deduplicates refresh within a tab and uses Web Locks across tabs.
BroadcastChannel propagates logout. Browsers without Web Locks have only the
within-tab deduplication; simultaneous refreshes may require signing in again
under the strict reuse policy.

Configuration: `JWT_SECRET` must have at least 32 bytes. Compose's fallback is a
development key; use a random secret and `COOKIE_SECURE=true` with HTTPS when
deploying. The cookie setup assumes the frontend and API share a site, as they
do with the local ports. SMTP uses the existing MailHog service locally and also
accepts `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD`.

Existing seed users keep their stored password hashes when re-seeding. Changing
`DEMO_ADMIN_PASSWORD` does not reset an existing account's password. Use the
registration/recovery flows when testing instead of assuming a newly edited
environment default changed an existing volume's credentials.

## Catalog and search

- `GET /api/products`: pagination (`page`, `limit`), `category`, `featured`, `q`,
  `min_price`, `max_price`, and sort (`newest`, `price_asc`, `price_desc`, `name`).
- `GET /api/products/categories`: categories from active products.
- `GET /api/products/:handle`: product, ordered images and variants/stock.
- Public responses include price/currency, image URL and visible-review summary.
  Empty review history returns `rating_average: null`, `review_count: 0`.
- Search enrichment uses the **worker-returned index version + vector ID**.
  It never trusts a filename or inference-supplied catalog ID as SQL identity.
  Ranking is retained, duplicate product images collapse to the first result and
  inactive products disappear. Unknown index versions fail instead of matching
  against the current active version by accident.
- A native gateway without `DATABASE_URL` retains Phase -1 retrieval. Catalog
  and auth routes explicitly report unavailable until SQL is configured.

The homepage replaces the mock product array with featured SQL products. `/search`
adds category/sort/pagination UI, and `/product/[handle]` reads the local catalog
with server rendering, metadata and actual HTTP 404 for absent products. The
sitemap reads the catalog instead of Shopify. `API_INTERNAL_URL` provides the
server-side Docker URL separately from the browser's `NEXT_PUBLIC_API_URL`.
`SITE_URL` supplies the public origin for metadata/sitemap, including the isolated
13000 port. Compose passes it at build time and runtime.

Product cards link to details and show real catalog prices/review summaries.
`View product` replaces the old fake Quick Add counter; this phase does not
pretend a cart exists. Catalog/detail links can launch similar-image search.
Unconverted legacy content/Shopify helpers remain in the repository; the newly
converted home, catalog, product and account flows do not depend on Shopify.

PPR changed from globally enabled to opt-in (`incremental`). This prevents the
old pre-rendered shell from returning HTTP 200 before a missing product is known.

## Verification and repeatable commands

Run from the repository root. Existing Phase 0 data is reused. Once infrastructure
is already healthy, build/restart these two services without re-running the seed:

```powershell
docker compose --env-file infra/test.env.example build core-api frontend
docker compose --env-file infra/test.env.example up -d --no-deps core-api frontend
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify python /app/infra/scripts/verify_phase1.py
docker compose --env-file infra/test.env.example --profile tools run --rm --no-deps verify
```

For a stopped/fresh stack, use the Phase 0 startup procedure first. The Phase 1
verifier creates a uniquely named test account, checks mail only in local MailHog
and removes only that test account on completion. OTP expiry/attempt limits are
simulated by altering its own temporary OTP rows.

```powershell
Set-Location core-api
go test ./...
$env:TEST_DATABASE_URL='postgres://aurafind:aurafind_dev@localhost:15432/aurafind?connect_timeout=5'
go test ./internal/catalog -run TestEnrichmentVersionIsolation -v
```

The catalog integration test creates a uniquely named temporary schema, applies
the initial migration there, verifies version isolation/deduplication/hidden
products/zero-price preservation, and removes only its own schema.

Verified on 29 October 2026:

- Gateway unit tests, JWT expiry/signature/algorithm/audience rejection and OTP
  formatting/purpose binding.
- PostgreSQL catalog integration test in an isolated temporary schema.
- HTTP auth/catalog/search suite: registration, OTP expiry/guess limit/replay,
  verification, profile, refresh rotation/reuse, Origin checks, logout, reset and
  previous-session revocation; SQL enrichment/filtering and frontend routes/404.
- TypeScript and frontend/gateway Docker production builds.
- Existing Phase 0 integration verifier still passes after Phase 1.
- Browser: sign in, reload session restoration, simultaneous refresh in two tabs,
  logout propagation, category/price sorting, product details and similar search.

Manual test: open `http://localhost:13000/register`, create an account, read its
code at `http://localhost:18025`, verify, then check `/account`. Browse `/search`,
open a product and select **Find similar styles**. Cart/checkout are Phase 2.

Implementation references: [JWT library](https://pkg.go.dev/github.com/golang-jwt/jwt/v5),
[OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[Go SMTP](https://pkg.go.dev/net/smtp).
