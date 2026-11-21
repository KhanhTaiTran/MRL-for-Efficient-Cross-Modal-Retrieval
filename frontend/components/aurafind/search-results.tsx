"use client";
import { useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useSearch } from "./search-provider";
import { ProductCard } from "./product-card";
import { ProductSkeleton } from "./product-skeleton";
import { PRODUCT_GRID_CLASS } from "./constants";
export function SearchResults() {
  const params = useSearchParams();
  const router = useRouter();
  const { execute, results, loading, error, title } = useSearch();
  const q = params.get("q") || undefined,
    similar = params.get("similar") || undefined,
    upload = params.get("upload") || undefined;
  useEffect(() => {
    void execute({
      ...(q ? { q } : {}),
      ...(similar ? { similar } : {}),
      ...(upload ? { upload } : {}),
    });
  }, [q, similar, upload, execute]);
  return (
    <section className="site-container py-8 sm:py-12" aria-busy={loading}>
      <Link
        href="/search"
        className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-white"
      >
        Shop all products
      </Link>
      <div className="mb-8 mt-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Discover with AI</p>
          <h1 className="mt-2 max-w-3xl break-words text-2xl font-semibold tracking-tight sm:text-3xl">
            {title}
          </h1>
        </div>
        <p className="text-sm text-neutral-500" role="status">
          {loading ? "Finding your style…" : `${results.length} products`}
        </p>
      </div>
      {error ? (
        <div
          role="alert"
          className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200"
        >
          <p>{error}</p>
          <button
            className="ui-button mt-4"
            onClick={() =>
              void execute(
                {
                  ...(q ? { q } : {}),
                  ...(similar ? { similar } : {}),
                  ...(upload ? { upload } : {}),
                },
                true,
              )
            }
          >
            Try again
          </button>
        </div>
      ) : (
        <div className={PRODUCT_GRID_CLASS}>
          {loading
            ? Array.from({ length: 8 }, (_, i) => <ProductSkeleton key={i} />)
            : results.map((product, index) => (
                <ProductCard
                  key={product.catalog_product_id || product.product_id}
                  product={product}
                  index={index}
                  onFindSimilar={() =>
                    router.push(
                      `/discover?similar=${encodeURIComponent(product.handle || "")}`,
                    )
                  }
                />
              ))}
        </div>
      )}
      {!loading && !error && results.length === 0 && (
        <div className="py-16 text-center">
          <h2 className="text-lg font-medium">A new look starts here</h2>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-neutral-500">
            Describe a style in the search bar or use the camera to upload a
            reference image.
          </p>
          <Link className="ui-button mt-6 inline-flex" href="/search">
            Browse the collection
          </Link>
        </div>
      )}
    </section>
  );
}
