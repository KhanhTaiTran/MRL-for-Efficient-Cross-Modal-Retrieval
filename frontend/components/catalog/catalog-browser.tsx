"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, SlidersHorizontal, X } from "lucide-react";
import { request } from "lib/api/client";
import { productForCard, type CatalogResponse } from "lib/api/catalog";
import { categoryLabel } from "lib/display-text";
import { ProductCard } from "components/aurafind/product-card";
import { ProductSkeleton } from "components/aurafind/product-skeleton";
import { PRODUCT_GRID_CLASS } from "components/aurafind/constants";
import type { EnrichedProduct } from "components/aurafind/types";
import { CatalogSelect } from "components/ui/catalog-select";
import { fetchSearchConfig } from "components/aurafind/search-api";

const sorting = [
  { value: "relevance", label: "Relevance" },
  { value: "newest", label: "Newest" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "name", label: "Name" },
];
type Filters = {
  category: string;
  query: string;
  sort: string;
  page: number;
  minPrice: string;
  maxPrice: string;
  featured: boolean;
};

// A null-rendering subscriber keeps soft navigations and native history changes
// in sync without making the homepage preview depend on searchParams.
function CatalogLocation({
  onChange,
}: {
  onChange: (filters: Filters) => void;
}) {
  const params = useSearchParams();
  const queryString = params.toString();
  useEffect(() => {
    const current = new URLSearchParams(queryString);
    const rawPage = Number(current.get("page") || 1);
    onChange({
      category: current.get("category") ?? "",
      query: current.get("q") ?? "",
      sort: sorting.some((item) => item.value === current.get("sort"))
        ? current.get("sort")!
        : current.get("q")?.trim()
          ? "relevance"
          : "newest",
      page: Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1,
      minPrice: current.get("min_price") ?? "",
      maxPrice: current.get("max_price") ?? "",
      featured: current.get("featured") === "true",
    });
    try {
      sessionStorage.setItem(
        "aurafind-catalog-url",
        window.location.pathname + (queryString ? `?${queryString}` : ""),
      );
    } catch {
      /* Optional browser storage. */
    }
  }, [queryString, onChange]);
  return null;
}

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
  const [filters, setFilters] = useState<Filters>({
    category: initialCategory,
    query: initialQuery,
    sort: initialQuery.trim() ? "relevance" : "newest",
    page: 1,
    minPrice: "",
    maxPrice: "",
    featured: false,
  });
  const [ready, setReady] = useState(preview);
  const [categories, setCategories] = useState<string[]>([]);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<CatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const syncLocation = useCallback((next: Filters) => {
    setFilters((current) =>
      current.category === next.category &&
      current.query === next.query &&
      current.sort === next.sort &&
      current.page === next.page &&
      current.minPrice === next.minPrice &&
      current.maxPrice === next.maxPrice &&
      current.featured === next.featured
        ? current
        : next,
    );
    setReady(true);
  }, []);

  function updateFilters(patch: Partial<Filters>) {
    const next = { ...filters, ...patch };
    setFilters(next);
    if (preview) return;
    const params = new URLSearchParams(window.location.search);
    const pairs: [string, string][] = [
      ["category", next.category],
      ["q", next.query],
      [
        "sort",
        next.sort === (next.query.trim() ? "relevance" : "newest")
          ? ""
          : next.sort,
      ],
      ["page", next.page === 1 ? "" : String(next.page)],
      ["min_price", next.minPrice],
      ["max_price", next.maxPrice],
      ["featured", next.featured ? "true" : ""],
    ];
    for (const [key, value] of pairs) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    const url = window.location.pathname + (params.size ? `?${params}` : "");
    window.history.pushState(null, "", url);
    try {
      sessionStorage.setItem("aurafind-catalog-url", url);
    } catch {
      /* Optional navigation convenience. */
    }
  }

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
    if (!ready) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      page: String(filters.page),
      limit: preview ? "8" : "12",
      sort: filters.sort,
      category: filters.category,
      q: filters.query,
      min_price: filters.minPrice,
      max_price: filters.maxPrice,
      featured: String(filters.featured),
    });
    if (preview) params.set("featured", "true");
    const load = async () => {
      if (filters.query.trim()) {
        try {
          const config = await fetchSearchConfig(controller.signal);
          params.set(
            "retrieval_mode",
            config.text_retrieval_mode_default ?? "dense",
          );
        } catch (failure) {
          if (controller.signal.aborted) throw failure;
          params.set("retrieval_mode", "dense");
        }
      }
      return request<CatalogResponse>(`/products?${params}`, {
        signal: controller.signal,
      });
    };
    load()
      .then(setData)
      .catch((failure) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Could not load products.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [filters, preview, retry, ready]);

  const filtered = Boolean(
    filters.category ||
      filters.query ||
      filters.sort !== "newest" ||
      filters.minPrice ||
      filters.maxPrice ||
      filters.featured,
  );
  return (
    <section
      className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-12 lg:px-8"
      aria-labelledby={preview ? "featured-heading" : "catalog-heading"}
    >
      {!preview && (
        <Suspense fallback={null}>
          <CatalogLocation onChange={syncLocation} />
        </Suspense>
      )}
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-[0.14em] text-neutral-500 uppercase dark:text-neutral-400">
            {preview ? "Curated for you" : "The collection"}
          </p>
          <h2
            id={preview ? "featured-heading" : "catalog-heading"}
            className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl"
          >
            {preview ? "Featured products" : "Shop all products"}
          </h2>
          {!preview && (
            <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
              Explore the catalog by category, or use the search above to
              describe a look.
            </p>
          )}
        </div>
        {preview && (
          <Link
            href="/search"
            className="inline-flex items-center gap-2 text-sm font-medium underline-offset-4 hover:underline"
          >
            View all products <ArrowRight className="h-4 w-4" />
          </Link>
        )}
      </div>
      {!preview && (
        <div className="mb-7 rounded-2xl border border-neutral-200 bg-white p-4 sm:p-5 dark:border-neutral-800 dark:bg-neutral-900/40">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-cols-[minmax(200px,280px)_minmax(200px,240px)_1fr]">
            <CatalogSelect
              label="Category"
              searchable
              value={filters.category}
              onChange={(category) => updateFilters({ category, page: 1 })}
              options={[
                { value: "", label: "All categories" },
                ...categories.map((value) => ({
                  value,
                  label: categoryLabel(value),
                })),
              ]}
            />
            <CatalogSelect
              label="Sort by"
              value={filters.sort}
              onChange={(sort) => updateFilters({ sort, page: 1 })}
              options={sorting.filter(
                (option) =>
                  option.value !== "relevance" || filters.query.trim(),
              )}
            />
            <div className="flex min-h-11 flex-wrap items-center justify-between gap-3 self-end sm:col-span-2 lg:col-span-1 lg:justify-end">
              <p
                className="text-sm text-neutral-600 tabular-nums dark:text-neutral-300"
                aria-live="polite"
              >
                {loading
                  ? "Updating collection…"
                  : `${(data?.pagination.total ?? 0).toLocaleString("en-US")} ${data?.search?.truncated ? "ranked matches" : "products"}`}
              </p>
              {filtered && (
                <button
                  onClick={() =>
                    updateFilters({
                      category: "",
                      query: "",
                      sort: "newest",
                      page: 1,
                      minPrice: "",
                      maxPrice: "",
                      featured: false,
                    })
                  }
                  className="inline-flex min-h-11 items-center gap-1.5 text-xs font-medium text-neutral-600 hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-white"
                >
                  <X className="h-3.5 w-3.5" /> Clear filters
                </button>
              )}
            </div>
          </div>
          {filters.query && (
            <p className="mt-3 text-sm text-neutral-600 dark:text-neutral-300">
              Results for “{filters.query}”
            </p>
          )}
        </div>
      )}
      {error ? (
        <div
          role="alert"
          className="rounded-2xl border border-neutral-200 p-6 dark:border-neutral-800"
        >
          <p className="font-medium">The collection could not be loaded.</p>
          <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
            {error}
          </p>
          <button
            onClick={() => setRetry((value) => value + 1)}
            className="mt-4 inline-flex min-h-11 items-center text-sm font-medium underline underline-offset-4"
          >
            Try again
          </button>
        </div>
      ) : (
        <div className={PRODUCT_GRID_CLASS} aria-busy={loading}>
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
                        `/discover?similar=${encodeURIComponent(product.handle)}`,
                      ))
                  }
                />
              ))}
        </div>
      )}
      {!loading && !error && !data?.data.length && (
        <div className="rounded-2xl border border-dashed border-neutral-300 px-5 py-16 text-center dark:border-neutral-700">
          <SlidersHorizontal className="mx-auto h-6 w-6 text-neutral-400" />
          <h3 className="mt-4 text-lg font-medium">
            No products match these filters
          </h3>
          <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
            Try another category or clear your filters to explore the
            collection.
          </p>
          <button
            className="ui-button mt-5"
            onClick={() =>
              updateFilters({
                category: "",
                query: "",
                sort: "newest",
                page: 1,
                minPrice: "",
                maxPrice: "",
                featured: false,
              })
            }
          >
            Show all products
          </button>
        </div>
      )}
      {!preview && !loading && !error && data && data.pagination.pages > 1 && (
        <nav
          aria-label="Product pagination"
          className="mt-10 flex items-center justify-between gap-3 border-t border-neutral-200 pt-6 text-sm dark:border-neutral-800 sm:justify-center sm:gap-8"
        >
          <button
            disabled={filters.page === 1}
            onClick={() => updateFilters({ page: filters.page - 1 })}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-neutral-300 px-3 sm:px-4 disabled:opacity-40 dark:border-neutral-700"
          >
            <ArrowLeft className="h-4 w-4" /> Previous
          </button>
          <span className="text-center text-xs text-neutral-600 tabular-nums sm:text-sm dark:text-neutral-300">
            Page {filters.page.toLocaleString("en-US")} of{" "}
            {data.pagination.pages.toLocaleString("en-US")}
          </span>
          <button
            disabled={filters.page >= data.pagination.pages}
            onClick={() => updateFilters({ page: filters.page + 1 })}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-neutral-300 px-3 sm:px-4 disabled:opacity-40 dark:border-neutral-700"
          >
            Next <ArrowRight className="h-4 w-4" />
          </button>
        </nav>
      )}
    </section>
  );
}
