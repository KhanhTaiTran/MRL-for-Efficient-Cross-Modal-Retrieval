"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
import { AdminNav } from "./admin-nav";
import { Star, MessageSquare } from "lucide-react";
import { displayText } from "lib/display-text";
import { authenticatedRequest } from "lib/api/client";
import type { CustomerReview } from "components/catalog/product-engagement";
export function ReviewModeration() {
  const { user, loading } = useAuth();
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{
    owner: string;
    data: CustomerReview[];
    pages: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setResult(null);
    setError("");
    if (user?.role !== "admin" || loading) return;
    let alive = true;
    authenticatedRequest<{
      data: CustomerReview[];
      pagination: { pages: number };
    }>(`/admin/reviews?page=${page}`)
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
  }, [user?.id, user?.role, loading, page, revision]);
  const data = result?.owner === user?.id ? result : null;
  return (
    <>
      <div className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-10 lg:px-8">
        <div className="mb-6">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500 dark:text-neutral-400">
            Workspace
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Administration
          </h1>
          <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            Manage your catalog, customer reviews and product search.
          </p>
        </div>
        <AdminNav active="reviews" />
        {loading ? (
          <p className="mt-8">Loading account…</p>
        ) : !user ? (
          <p className="mt-8">
            <Link className="underline" href="/login?next=/admin/reviews">
              Sign in as administrator
            </Link>
          </p>
        ) : user.role !== "admin" ? (
          <p role="alert" className="mt-8">
            Administrator access is required.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-5 text-red-600">
                {error}
              </p>
            )}
            {!data ? (
              <p className="mt-8">
                {error ? "Reviews unavailable." : "Loading reviews…"}
              </p>
            ) : (
              <>
                <div className="mb-6">
                  <h2 className="text-xl font-semibold">Customer reviews</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                    Control what appears on product pages. Hidden reviews are
                    kept in the account history and excluded from public
                    ratings.
                  </p>
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  {data.data.map((review) => (
                    <article
                      key={review.id}
                      className="flex min-w-0 flex-col rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6 dark:border-neutral-800 dark:bg-neutral-900/50"
                    >
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <span
                          className={`rounded-md px-2 py-1 text-xs font-medium ${review.is_hidden ? "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300" : "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"}`}
                        >
                          {review.is_hidden ? "Hidden" : "Visible"}
                        </span>
                        <span className="flex items-center gap-1 text-sm font-medium">
                          <Star className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                          {review.rating} / 5
                        </span>
                      </div>
                      <h2 className="break-words font-medium">
                        {displayText(review.product_name)}
                      </h2>
                      <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                        {review.author} ·{" "}
                        {new Date(review.created_at).toLocaleDateString()} ·{" "}
                        {review.is_verified_purchase
                          ? "Verified purchase"
                          : "Customer review"}
                      </p>
                      <p className="mt-4 whitespace-pre-wrap break-words text-sm">
                        {review.comment}
                      </p>
                      <button
                        disabled={busy}
                        className="mt-5 min-h-11 self-start rounded-xl border border-neutral-300 px-4 py-2.5 text-sm font-medium hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800"
                        onClick={async () => {
                          setBusy(true);
                          setError("");
                          try {
                            await authenticatedRequest(
                              `/admin/reviews/${review.id}`,
                              {
                                method: "PATCH",
                                body: JSON.stringify({
                                  is_hidden: !review.is_hidden,
                                }),
                              },
                            );
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
                        {review.is_hidden ? "Show review" : "Hide review"}
                      </button>
                    </article>
                  ))}
                </div>
                {!data.data.length && (
                  <div className="rounded-2xl border border-dashed border-neutral-300 px-6 py-12 text-center dark:border-neutral-700">
                    <MessageSquare className="mx-auto mb-3 h-8 w-8 text-neutral-400" />
                    <p className="font-medium">No customer reviews yet</p>
                    <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
                      Reviews submitted after purchases will appear here.
                    </p>
                  </div>
                )}
                <nav
                  aria-label="Moderation pages"
                  className="mt-8 flex gap-5 text-sm"
                >
                  <button
                    className="min-h-11 rounded-xl border border-neutral-300 px-4 py-2 disabled:opacity-40 dark:border-neutral-700"
                    disabled={page === 1 || busy}
                    onClick={() => setPage((v) => v - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page} / {Math.max(1, data.pages)}
                  </span>
                  <button
                    className="min-h-11 rounded-xl border border-neutral-300 px-4 py-2 disabled:opacity-40 dark:border-neutral-700"
                    disabled={page >= data.pages || busy}
                    onClick={() => setPage((v) => v + 1)}
                  >
                    Next
                  </button>
                </nav>
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
