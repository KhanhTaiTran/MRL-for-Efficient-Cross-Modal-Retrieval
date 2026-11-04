"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "components/auth/auth-provider";
import { authenticatedRequest, request } from "lib/api/client";
export interface CustomerReview {
  id: string;
  product_name: string;
  author: string;
  rating: number;
  comment: string;
  is_hidden: boolean;
  is_verified_purchase: boolean;
  created_at: string;
}
interface ReviewsResponse {
  data: CustomerReview[];
  pagination: { pages: number; total: number };
}
const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Please try again.";
export function ProductEngagement({
  id,
  handle,
}: {
  id: string;
  handle: string;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [reviews, setReviews] = useState<ReviewsResponse | null>(null);
  const [eligibility, setEligibility] = useState<{
    owner: string;
    eligible: boolean;
    review: CustomerReview | null;
  } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setError("");
    setReviews(null);
    request<ReviewsResponse>(
      `/products/${encodeURIComponent(handle)}/reviews?page=${page}`,
    )
      .then((value) => {
        if (alive) setReviews(value);
      })
      .catch((error) => {
        if (alive) setError(errorMessage(error));
      });
    return () => {
      alive = false;
    };
  }, [handle, page, revision]);
  useEffect(() => {
    setEligibility(null);
    if (!user || loading) return;
    let alive = true;
    authenticatedRequest<{ eligible: boolean; review: CustomerReview | null }>(
      `/products/${encodeURIComponent(handle)}/review-eligibility`,
    )
      .then((value) => {
        if (alive) setEligibility({ owner: user.id, ...value });
      })
      .catch((error) => {
        if (alive) setError(errorMessage(error));
      });
    return () => {
      alive = false;
    };
  }, [handle, user?.id, loading, revision]);
  const own = eligibility?.owner === user?.id ? eligibility : null;
  async function saveReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await authenticatedRequest(
        `/products/${encodeURIComponent(handle)}/review`,
        {
          method: "PUT",
          body: JSON.stringify({
            rating: Number(form.get("rating")),
            comment: String(form.get("comment") || ""),
          }),
        },
      );
      setRevision((v) => v + 1);
      setNotice("Your review has been saved.");
      router.refresh();
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="mt-14 border-t border-neutral-200 py-8 dark:border-neutral-800">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-semibold">Customer reviews</h2>
        <button
          disabled={busy || loading}
          className="text-sm underline disabled:opacity-50"
          onClick={async () => {
            if (!user) {
              router.push(
                `/login?next=${encodeURIComponent(`/product/${handle}`)}`,
              );
              return;
            }
            setBusy(true);
            setError("");
            try {
              await authenticatedRequest(`/wishlist/${id}`, { method: "PUT" });
              setNotice("Saved to your wishlist.");
            } catch (error) {
              setError(errorMessage(error));
            } finally {
              setBusy(false);
            }
          }}
        >
          Save to wishlist
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-5 text-sm text-red-600">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-5 text-sm">
          {notice}
        </p>
      )}
      {!reviews ? (
        <p className="mt-6 text-sm">
          {error ? "Reviews could not be loaded." : "Loading reviews…"}
        </p>
      ) : (
        <>
          <p className="mt-4 text-sm text-neutral-500">
            {reviews.pagination.total
              ? `${reviews.pagination.total} customer reviews`
              : "No reviews yet."}
          </p>
          <div className="mt-5 divide-y divide-neutral-200 dark:divide-neutral-800">
            {reviews.data.map((review) => (
              <article key={review.id} className="py-5">
                <p className="font-medium">
                  {review.rating} out of 5 · {review.author || "Customer"}
                </p>
                <p className="mt-1 text-xs text-neutral-500">
                  {review.is_verified_purchase ? "Verified purchase · " : ""}
                  {new Date(review.created_at).toLocaleDateString()}
                </p>
                <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">
                  {review.comment}
                </p>
              </article>
            ))}
          </div>
          {reviews.pagination.pages > 1 && (
            <nav aria-label="Review pages" className="mt-5 flex gap-5 text-sm">
              <button
                disabled={page <= 1}
                className="underline disabled:opacity-40"
                onClick={() => setPage((v) => v - 1)}
              >
                Previous
              </button>
              <span>
                Page {page} of {reviews.pagination.pages}
              </span>
              <button
                disabled={page >= reviews.pagination.pages}
                className="underline disabled:opacity-40"
                onClick={() => setPage((v) => v + 1)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
      {!loading &&
        (!user ? (
          <p className="mt-8 text-sm">
            <Link
              href={`/login?next=${encodeURIComponent(`/product/${handle}`)}`}
              className="underline"
            >
              Sign in
            </Link>{" "}
            to review a verified purchase.
          </p>
        ) : own?.eligible ? (
          <form
            key={`${user.id}:${revision}`}
            onSubmit={saveReview}
            className="mt-8 max-w-xl space-y-4"
          >
            <h3 className="text-lg font-medium">
              {own.review ? "Edit your review" : "Review your purchase"}
            </h3>
            {own.review?.is_hidden && (
              <p className="text-sm text-neutral-500">
                This review is hidden by a moderator. Editing it does not change
                its visibility.
              </p>
            )}
            <label className="block text-sm">
              Rating
              <select
                name="rating"
                defaultValue={own.review?.rating ?? 5}
                className="mt-2 block w-full rounded-lg border bg-transparent p-3"
              >
                {[5, 4, 3, 2, 1].map((n) => (
                  <option key={n} value={n}>
                    {n} out of 5
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Your review
              <textarea
                name="comment"
                defaultValue={own.review?.comment || ""}
                maxLength={4000}
                rows={4}
                className="mt-2 block w-full rounded-lg border bg-transparent p-3"
              />
            </label>
            <p className="text-xs text-neutral-500">
              Comments support up to 4000 UTF-8 bytes. Reviews show your first
              name.
            </p>
            <button
              disabled={busy}
              className="rounded-lg bg-neutral-900 px-5 py-3 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
            >
              Save review
            </button>
          </form>
        ) : (
          own && (
            <p className="mt-8 text-sm text-neutral-500">
              A confirmed, paid purchase is required to review this product.
            </p>
          )
        ))}
    </section>
  );
}
