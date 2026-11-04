"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
import { StoreHeader } from "components/layout/store-header";
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
      <StoreHeader />
      <main className="mx-auto max-w-4xl px-6 py-12">
        <h1 className="text-3xl font-semibold">Review moderation</h1>
        <Link href="/admin" className="mt-4 inline-block text-sm underline">
          Back to catalog administration
        </Link>
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
                <div className="mt-8 divide-y divide-neutral-200 dark:divide-neutral-800">
                  {data.data.map((review) => (
                    <article key={review.id} className="py-6">
                      <h2 className="font-medium">
                        {review.product_name} · {review.rating} out of 5
                      </h2>
                      <p className="mt-2 text-xs text-neutral-500">
                        {review.author} ·{" "}
                        {new Date(review.created_at).toLocaleDateString()} ·{" "}
                        {review.is_hidden ? "Hidden" : "Visible"}
                      </p>
                      <p className="mt-4 whitespace-pre-wrap break-words text-sm">
                        {review.comment}
                      </p>
                      <button
                        disabled={busy}
                        className="mt-4 text-sm underline"
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
                  <p className="mt-8">No reviews on this page.</p>
                )}
                <nav
                  aria-label="Moderation pages"
                  className="mt-8 flex gap-5 text-sm"
                >
                  <button
                    className="underline disabled:opacity-40"
                    disabled={page === 1 || busy}
                    onClick={() => setPage((v) => v - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page} / {Math.max(1, data.pages)}
                  </span>
                  <button
                    className="underline disabled:opacity-40"
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
      </main>
    </>
  );
}
