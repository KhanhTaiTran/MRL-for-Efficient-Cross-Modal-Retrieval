"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { request } from "lib/api/client";
import { productForCard, type CatalogResponse } from "lib/api/catalog";
import { ProductCard } from "components/aurafind/product-card";
import { ProductSkeleton } from "components/aurafind/product-skeleton";
import { PRODUCT_GRID_CLASS } from "components/aurafind/constants";
import type { EnrichedProduct } from "components/aurafind/types";

export function CatalogBrowser({
  preview = false,
  onFindSimilar,
  initialCategory = "",
  initialQuery = "",
}: {
  preview?: boolean;
  onFindSimilar?: (product: EnrichedProduct) => void;
  initialCategory?: string;
  initialQuery?: string;
}) {
  const router = useRouter();
  const [category, setCategory] = useState(initialCategory);
  const [categories, setCategories] = useState<string[]>([]);
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<CatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    request<{ data: string[] }>("/products/categories", {
      signal: controller.signal,
    })
      .then((value) => setCategories(value.data))
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      page: String(page),
      limit: preview ? "8" : "12",
      sort,
      category,
      q: initialQuery,
    });
    if (preview) params.set("featured", "true");
    request<CatalogResponse>(`/products?${params}`, {
      signal: controller.signal,
    })
      .then(setData)
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error ? error.message : "Could not load products.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [category, sort, page, preview, retry, initialQuery]);

  return (
    <section className="mx-auto max-w-[1600px] px-4 py-12 sm:px-6 lg:px-8">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500">
            {preview ? "Curated for you" : "Find your next favourite"}
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">
            {preview ? "Featured products" : "Shop all products"}
          </h2>
        </div>
        {preview && (
          <Link href="/search" className="text-sm underline underline-offset-4">
            View all products
          </Link>
        )}
      </div>
      {!preview && (
        <div className="mb-8 flex flex-wrap items-end gap-5">
          <label className="text-sm">
            Category
            <select
              aria-label="Category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
              className="ml-3 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
            >
              <option value="">All categories</option>
              {categories.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Sort
            <select
              aria-label="Sort"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              className="ml-3 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
            >
              <option value="newest">Newest</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
              <option value="name">Name</option>
            </select>
          </label>
          {data && (
            <p className="text-sm text-neutral-500" aria-live="polite">
              {data.pagination.total} products
            </p>
          )}
        </div>
      )}
      {error ? (
        <div
          role="alert"
          className="space-y-4 rounded-xl border border-neutral-300 p-6 dark:border-neutral-700"
        >
          <p>{error}</p>
          <button
            onClick={() => setRetry((value) => value + 1)}
            className="text-sm underline"
          >
            Try again
          </button>
        </div>
      ) : (
        <div className={PRODUCT_GRID_CLASS}>
          {loading
            ? Array.from({ length: preview ? 4 : 8 }, (_, index) => (
                <ProductSkeleton key={index} />
              ))
            : data?.data.map((product, index) => (
                <ProductCard
                  key={product.id}
                  product={productForCard(product)}
                  index={index}
                  onFindSimilar={
                    onFindSimilar ??
                    (() =>
                      router.push(
                        `/?similar=${encodeURIComponent(product.handle)}`,
                      ))
                  }
                />
              ))}
        </div>
      )}
      {!loading && !error && !data?.data.length && (
        <p className="py-10 text-neutral-500">
          No products match these filters.
        </p>
      )}
      {!preview && !loading && !error && data && data.pagination.pages > 1 && (
        <nav
          aria-label="Product pagination"
          className="mt-10 flex items-center justify-center gap-6 text-sm"
        >
          <button
            disabled={page === 1}
            onClick={() => setPage((value) => value - 1)}
            className="rounded-lg border px-4 py-2 disabled:opacity-40"
          >
            Previous
          </button>
          <span>
            Page {page} of {data.pagination.pages}
          </span>
          <button
            disabled={page >= data.pagination.pages}
            onClick={() => setPage((value) => value + 1)}
            className="rounded-lg border px-4 py-2 disabled:opacity-40"
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
