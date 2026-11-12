"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
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
      <section className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
        <Link
          href="/search"
          className="mb-5 inline-flex min-h-8 items-center text-sm text-neutral-600 underline underline-offset-4 dark:text-neutral-400"
        >
          Continue shopping
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Saved items
        </h1>
        <p className="mt-3 text-sm leading-6 text-neutral-600 dark:text-neutral-400">
          Keep your favourites together and return to them whenever you like.
        </p>
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
              <p role="alert" className="mt-6 text-red-700 dark:text-red-400">
                {error}
              </p>
            )}
            {!data ? (
              <p className="mt-8">
                {error ? "Wishlist unavailable." : "Loading saved products…"}
              </p>
            ) : (
              <>
                <div className="mt-8 grid grid-cols-2 gap-x-4 gap-y-8 sm:gap-x-6 md:grid-cols-3 xl:grid-cols-4">
                  {data.data.map((item) => (
                    <article key={item.id} className="min-w-0">
                      {item.image_url && (
                        <img
                          src={item.image_url}
                          alt={item.name}
                          className="aspect-[3/4] w-full rounded-lg bg-white object-contain"
                        />
                      )}
                      <Link
                        href={`/product/${item.handle}`}
                        className="mt-4 block break-words text-sm font-medium leading-6 hover:underline sm:text-base"
                      >
                        {item.name}
                      </Link>
                      <p className="mt-2 text-sm font-semibold tabular-nums">
                        {money(item.price_cents, item.currency)}
                      </p>
                      <button
                        disabled={busy}
                        className="mt-2 min-h-11 text-left text-xs text-neutral-600 underline underline-offset-4 disabled:opacity-50 sm:text-sm dark:text-neutral-400"
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
                  className="mt-10 flex flex-wrap items-center justify-between gap-4 text-sm sm:justify-start sm:gap-5"
                >
                  <button
                    disabled={page === 1 || busy}
                    className="min-h-11 rounded-lg border border-neutral-300 px-4 disabled:opacity-40 dark:border-neutral-700"
                    onClick={() => setPage((v) => v - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page} / {Math.max(1, data.pages)}
                  </span>
                  <button
                    disabled={page >= data.pages || busy}
                    className="min-h-11 rounded-lg border border-neutral-300 px-4 disabled:opacity-40 dark:border-neutral-700"
                    onClick={() => setPage((v) => v + 1)}
                  >
                    Next
                  </button>
                </nav>
              </>
            )}
          </>
        )}
      </section>
    </>
  );
}
