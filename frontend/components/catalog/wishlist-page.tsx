"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
import { StoreHeader } from "components/layout/store-header";
import { authenticatedRequest } from "lib/api/client";
import { money } from "lib/api/commerce";
interface Saved {
  id: string;
  handle: string;
  name: string;
  price_cents: number;
  currency: string;
  image_url: string;
}
export function WishlistPage() {
  const { user, loading } = useAuth();
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{
    owner: string;
    data: Saved[];
    pages: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setResult(null);
    setError("");
    if (!user || loading) return;
    let alive = true;
    authenticatedRequest<{ data: Saved[]; pagination: { pages: number } }>(
      `/wishlist?page=${page}`,
    )
      .then((value) => {
        if (alive)
          setResult({
            owner: user.id,
            data: value.data,
            pages: value.pagination.pages,
          });
      })
      .catch((error) => {
        if (alive) setError(error.message);
      });
    return () => {
      alive = false;
    };
  }, [user?.id, loading, page, revision]);
  const data = result?.owner === user?.id ? result : null;
  return (
    <>
      <StoreHeader />
      <main className="mx-auto max-w-5xl px-6 py-12">
        <h1 className="text-3xl font-semibold">Your wishlist</h1>
        {loading ? (
          <p className="mt-8">Loading account…</p>
        ) : !user ? (
          <p className="mt-8">
            <Link className="underline" href="/login?next=/wishlist">
              Sign in
            </Link>{" "}
            to save products.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-6 text-red-600">
                {error}
              </p>
            )}
            {!data ? (
              <p className="mt-8">
                {error ? "Wishlist unavailable." : "Loading saved products…"}
              </p>
            ) : (
              <>
                <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                  {data.data.map((item) => (
                    <article key={item.id}>
                      {item.image_url && (
                        <img
                          src={item.image_url}
                          alt={item.name}
                          className="aspect-[3/4] w-full rounded-lg bg-white object-contain"
                        />
                      )}
                      <Link
                        href={`/product/${item.handle}`}
                        className="mt-4 block font-medium"
                      >
                        {item.name}
                      </Link>
                      <p className="mt-2 text-sm">
                        {money(item.price_cents, item.currency)}
                      </p>
                      <button
                        disabled={busy}
                        className="mt-3 text-sm underline"
                        onClick={async () => {
                          setBusy(true);
                          setError("");
                          try {
                            await authenticatedRequest(`/wishlist/${item.id}`, {
                              method: "DELETE",
                            });
                            setRevision((v) => v + 1);
                          } catch (error) {
                            setError(
                              error instanceof Error
                                ? error.message
                                : "Please try again.",
                            );
                          } finally {
                            setBusy(false);
                          }
                        }}
                      >
                        Remove from wishlist
                      </button>
                    </article>
                  ))}
                </div>
                {!data.data.length && (
                  <p className="mt-8">
                    No saved products on this page.{" "}
                    <Link className="underline" href="/search">
                      Explore products
                    </Link>
                  </p>
                )}
                <nav
                  aria-label="Wishlist pages"
                  className="mt-8 flex gap-5 text-sm"
                >
                  <button
                    disabled={page === 1 || busy}
                    className="underline disabled:opacity-40"
                    onClick={() => setPage((v) => v - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page} / {Math.max(1, data.pages)}
                  </span>
                  <button
                    disabled={page >= data.pages || busy}
                    className="underline disabled:opacity-40"
                    onClick={() => setPage((v) => v + 1)}
                  >
                    Next
                  </button>
                </nav>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}
