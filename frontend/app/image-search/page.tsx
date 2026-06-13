"use client";

import {
  ArrowUpTrayIcon,
  InformationCircleIcon,
  MagnifyingGlassIcon,
  PhotoIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import Image from "next/image";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

const MRL_DIMENSIONS = [8, 16, 32, 64, 128, 256, 512] as const;

interface SearchResult {
  product_id: string;
  distance: number;
}

interface SearchResponse {
  status: string;
  data?: SearchResult[];
  message?: string;
  mrl_dimension?: number;
  search_latency_ms?: number;
  request_latency_ms?: number;
}

interface ComparisonRow {
  dimension: number;
  requestLatencyMs: number;
  searchLatencyMs: number;
  topResult: SearchResult | null;
}

function formatProductName(productId: string): string {
  return productId
    .replace(/\.[^.]+$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getDimensionHint(dimension: number): string {
  if (dimension <= 32) return "Fastest scan — lower recall";
  if (dimension <= 128) return "Balanced speed and accuracy";
  if (dimension <= 256) return "Higher precision — slower index scan";
  return "Maximum accuracy — highest latency";
}

function ResultSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <div className="aspect-square animate-pulse bg-neutral-100 dark:bg-neutral-800" />
      <div className="space-y-2 p-4">
        <div className="h-4 w-3/4 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
        <div className="h-5 w-1/2 animate-pulse rounded-full bg-neutral-100 dark:bg-neutral-800" />
      </div>
    </div>
  );
}

export default function ImageSearchPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isComparing, setIsComparing] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searchLatencyMs, setSearchLatencyMs] = useState<number | null>(null);
  const [requestLatencyMs, setRequestLatencyMs] = useState<number | null>(null);
  const [comparisonRows, setComparisonRows] = useState<ComparisonRow[]>([]);
  const [mrlDimension, setMrlDimension] = useState<number>(64);
  const [isDragOver, setIsDragOver] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string | null>(null);

  const applyFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) {
      toast.error("Please upload an image file.");
      return;
    }

    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
    }

    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;
    setSelectedFile(file);
    setPreviewUrl(url);
    setResults([]);
    setComparisonRows([]);
    setSearchLatencyMs(null);
    setRequestLatencyMs(null);
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) applyFile(file);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) applyFile(file);
  };

  const clearSelection = () => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setSelectedFile(null);
    setPreviewUrl(null);
    setResults([]);
    setComparisonRows([]);
    setSearchLatencyMs(null);
    setRequestLatencyMs(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const runSearch = async (dimension: number) => {
    if (!selectedFile) return null;

    const formData = new FormData();
    formData.append("image", selectedFile);
    formData.append("mrl_dimension", String(dimension));

    const response = await fetch("http://localhost:8080/api/search", {
      method: "POST",
      body: formData,
    });

    const data = (await response.json()) as SearchResponse;
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message ?? "Search failed. Please try again.");
    }

    return data;
  };

  const handleSearch = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setResults([]);
    setComparisonRows([]);

    try {
      const data = await runSearch(mrlDimension);
      if (!data) return;

      setResults(data.data ?? []);
      setSearchLatencyMs(data.search_latency_ms ?? null);
      setRequestLatencyMs(data.request_latency_ms ?? null);
    } catch (error) {
      console.error("Error calling API:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : "Cannot connect to the search system.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleCompareAll = async () => {
    if (!selectedFile) return;

    setIsComparing(true);
    setIsLoading(false);
    setResults([]);
    setComparisonRows([]);
    setSearchLatencyMs(null);
    setRequestLatencyMs(null);

    try {
      const rows: ComparisonRow[] = [];

      for (const dimension of MRL_DIMENSIONS) {
        const data = await runSearch(dimension);
        if (!data) return;

        rows.push({
          dimension,
          requestLatencyMs: data.request_latency_ms ?? 0,
          searchLatencyMs: data.search_latency_ms ?? 0,
          topResult: data.data?.[0] ?? null,
        });

        if (dimension === mrlDimension) {
          setResults(data.data ?? []);
          setSearchLatencyMs(data.search_latency_ms ?? null);
          setRequestLatencyMs(data.request_latency_ms ?? null);
        }
      }

      setComparisonRows(rows);
    } catch (error) {
      console.error("Error running comparison sweep:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : "Cannot connect to the search system.",
      );
    } finally {
      setIsComparing(false);
    }
  };

  const showResultsSection = isLoading || results.length > 0;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:py-14 lg:px-6">
      {/* Header */}
      <div className="mb-10 text-center">
        <p className="text-xs font-medium uppercase tracking-wider text-violet-600 dark:text-violet-400">
          MRL Visual Search
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-neutral-900 sm:text-4xl dark:text-white">
          Search by image
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-neutral-600 sm:text-base dark:text-neutral-400">
          Upload a product photo and adjust the embedding dimension to compare
          retrieval speed against similarity accuracy.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        {/* Upload + Results */}
        <div className="space-y-8">
          {/* Drag & Drop Zone */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={`relative cursor-pointer rounded-2xl border-2 border-dashed p-8 transition-all duration-200 sm:p-10 ${
              isDragOver
                ? "border-violet-500 bg-violet-50/80 dark:border-violet-400 dark:bg-violet-950/30"
                : "border-neutral-300 bg-neutral-50 hover:border-violet-400 hover:bg-violet-50/40 dark:border-neutral-700 dark:bg-neutral-900/50 dark:hover:border-violet-600 dark:hover:bg-violet-950/20"
            }`}
          >
            <input
              ref={fileInputRef}
              title="Upload an image to search for similar products"
              type="file"
              accept="image/*"
              onChange={handleFileChange}
              className="sr-only"
            />

            {previewUrl ? (
              <div className="flex flex-col items-center gap-4">
                <div className="relative">
                  <Image
                    src={previewUrl}
                    alt="Uploaded preview"
                    width={240}
                    height={240}
                    className="rounded-xl object-cover shadow-lg ring-1 ring-neutral-200 dark:ring-neutral-700"
                  />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      clearSelection();
                    }}
                    className="absolute -right-2 -top-2 rounded-full bg-neutral-900 p-1.5 text-white transition-colors hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                    aria-label="Remove image"
                  >
                    <XMarkIcon className="h-4 w-4" />
                  </button>
                </div>
                <p className="text-sm text-neutral-500 dark:text-neutral-400">
                  Click or drop to replace image
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center text-center">
                <div className="mb-4 rounded-full bg-violet-100 p-4 dark:bg-violet-950/60">
                  <ArrowUpTrayIcon className="h-8 w-8 text-violet-600 dark:text-violet-400" />
                </div>
                <p className="text-base font-medium text-neutral-900 dark:text-white">
                  Drag & drop your image here
                </p>
                <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
                  or click to browse — PNG, JPG, WEBP
                </p>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={handleSearch}
              disabled={!selectedFile || isLoading || isComparing}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-neutral-900 px-6 py-3.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-neutral-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-neutral-300 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 dark:disabled:bg-neutral-700 dark:disabled:text-neutral-500"
            >
              {isLoading ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white dark:border-neutral-900/30 dark:border-t-neutral-900" />
                  Scanning FAISS index...
                </>
              ) : (
                <>
                  <MagnifyingGlassIcon className="h-5 w-5" />
                  Search similar products
                </>
              )}
            </button>

            <button
              type="button"
              onClick={handleCompareAll}
              disabled={!selectedFile || isLoading || isComparing}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-6 py-3.5 text-sm font-semibold text-violet-700 transition-all duration-200 hover:border-violet-300 hover:bg-violet-100 active:scale-[0.98] disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-neutral-100 disabled:text-neutral-400 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200 dark:hover:border-violet-700 dark:hover:bg-violet-950/50 dark:disabled:border-neutral-800 dark:disabled:bg-neutral-900 dark:disabled:text-neutral-600"
            >
              {isComparing ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-violet-500/30 border-t-violet-600 dark:border-violet-200/30 dark:border-t-violet-200" />
                  Comparing all dims...
                </>
              ) : (
                <>
                  <InformationCircleIcon className="h-5 w-5" />
                  Compare all dims
                </>
              )}
            </button>
          </div>

          {/* Results */}
          {showResultsSection && (
            <div>
              <div className="mb-5 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-neutral-900 dark:text-white">
                  {isLoading ? "Retrieving matches" : "Search results"}
                </h2>
                {!isLoading && results.length > 0 && (
                  <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium tabular-nums text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                    {results.length} matches · dim {mrlDimension}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {isLoading
                  ? Array.from({ length: 6 }).map((_, index) => (
                      <ResultSkeleton key={index} />
                    ))
                  : results.map((item, index) => (
                      <article
                        key={`${item.product_id}-${index}`}
                        className="group overflow-hidden rounded-xl border border-neutral-200 bg-white transition-all duration-300 hover:-translate-y-1 hover:border-violet-300 hover:shadow-lg hover:shadow-violet-500/10 dark:border-neutral-800 dark:bg-neutral-900 dark:hover:border-violet-700"
                      >
                        <div className="relative aspect-square overflow-hidden bg-neutral-100 dark:bg-neutral-800">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={`/mock_data/${item.product_id}`}
                            alt={formatProductName(item.product_id)}
                            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                          />
                          <span className="absolute right-2 top-2 rounded-full bg-violet-600 px-2.5 py-1 text-xs font-semibold tabular-nums text-white shadow-sm">
                            d={item.distance.toFixed(4)}
                          </span>
                        </div>
                        <div className="p-4">
                          <h3 className="font-medium text-neutral-900 dark:text-white">
                            {formatProductName(item.product_id)}
                          </h3>
                          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                            Similarity distance
                          </p>
                        </div>
                      </article>
                    ))}
              </div>

              {!isLoading &&
                (searchLatencyMs !== null || requestLatencyMs !== null) && (
                  <div className="mt-4 flex flex-wrap gap-2 text-xs text-neutral-500 dark:text-neutral-400">
                    {requestLatencyMs !== null && (
                      <span className="rounded-full bg-neutral-100 px-3 py-1 dark:bg-neutral-800">
                        Request latency {requestLatencyMs} ms
                      </span>
                    )}
                    {searchLatencyMs !== null && (
                      <span className="rounded-full bg-neutral-100 px-3 py-1 dark:bg-neutral-800">
                        FAISS search {searchLatencyMs} ms
                      </span>
                    )}
                  </div>
                )}
            </div>
          )}

          {!isLoading && comparisonRows.length > 0 && (
            <div className="overflow-hidden rounded-2xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
              <div className="border-b border-neutral-200 px-5 py-4 dark:border-neutral-800">
                <h2 className="text-lg font-semibold text-neutral-900 dark:text-white">
                  Dimension comparison
                </h2>
                <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
                  Lower distance means a closer match. Compare latency and match
                  quality across supported dimensions.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-neutral-200 text-left text-sm dark:divide-neutral-800">
                  <thead className="bg-neutral-50 text-xs uppercase tracking-wider text-neutral-500 dark:bg-neutral-950 dark:text-neutral-400">
                    <tr>
                      <th className="px-5 py-3 font-medium">Dim</th>
                      <th className="px-5 py-3 font-medium">Request latency</th>
                      <th className="px-5 py-3 font-medium">FAISS latency</th>
                      <th className="px-5 py-3 font-medium">Top match</th>
                      <th className="px-5 py-3 font-medium">Top distance</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                    {comparisonRows.map((row) => (
                      <tr
                        key={row.dimension}
                        className={
                          row.dimension === mrlDimension
                            ? "bg-violet-50/70 dark:bg-violet-950/20"
                            : undefined
                        }
                      >
                        <td className="px-5 py-4 font-semibold text-neutral-900 dark:text-white">
                          {row.dimension}
                        </td>
                        <td className="px-5 py-4 tabular-nums text-neutral-600 dark:text-neutral-300">
                          {row.requestLatencyMs} ms
                        </td>
                        <td className="px-5 py-4 tabular-nums text-neutral-600 dark:text-neutral-300">
                          {row.searchLatencyMs} ms
                        </td>
                        <td className="px-5 py-4 text-neutral-600 dark:text-neutral-300">
                          {row.topResult
                            ? formatProductName(row.topResult.product_id)
                            : "No result"}
                        </td>
                        <td className="px-5 py-4 tabular-nums text-neutral-600 dark:text-neutral-300">
                          {row.topResult
                            ? row.topResult.distance.toFixed(4)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* MRL Controls Sidebar */}
        <aside className="h-fit space-y-6 rounded-2xl border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900 lg:sticky lg:top-6">
          <div>
            <div className="flex items-center gap-2">
              <PhotoIcon className="h-5 w-5 text-violet-600 dark:text-violet-400" />
              <h2 className="text-sm font-semibold text-neutral-900 dark:text-white">
                MRL embedding dimension
              </h2>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-neutral-500 dark:text-neutral-400">
              Matryoshka embeddings are truncated at the selected dimension.
              Smaller vectors reduce FAISS scan time; larger vectors improve
              nearest-neighbor precision.
            </p>
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <label
                htmlFor="mrl-dimension"
                className="text-xs font-medium uppercase tracking-wider text-neutral-500 dark:text-neutral-400"
              >
                Dimension
              </label>
              <span className="rounded-md bg-violet-100 px-2.5 py-1 text-sm font-semibold tabular-nums text-violet-700 dark:bg-violet-950 dark:text-violet-300">
                {mrlDimension}
              </span>
            </div>

            <input
              id="mrl-dimension"
              type="range"
              min={0}
              max={MRL_DIMENSIONS.length - 1}
              step={1}
              value={MRL_DIMENSIONS.indexOf(
                mrlDimension as (typeof MRL_DIMENSIONS)[number],
              )}
              onChange={(e) => {
                const index = Number(e.target.value);
                setMrlDimension(MRL_DIMENSIONS[index] ?? 64);
              }}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-neutral-200 accent-violet-600 dark:bg-neutral-700"
            />

            <div className="mt-2 flex justify-between text-[10px] font-medium uppercase tracking-wide text-neutral-400">
              <span>Faster</span>
              <span>More accurate</span>
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {MRL_DIMENSIONS.map((dim) => (
                <button
                  key={dim}
                  type="button"
                  onClick={() => setMrlDimension(dim)}
                  className={`rounded-md px-2 py-1 text-xs font-medium tabular-nums transition-colors duration-200 ${
                    mrlDimension === dim
                      ? "bg-violet-600 text-white"
                      : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700"
                  }`}
                >
                  {dim}
                </button>
              ))}
            </div>

            <p className="mt-4 flex items-start gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
              <InformationCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-violet-500" />
              {getDimensionHint(mrlDimension)}
            </p>
          </div>

          <div className="rounded-xl bg-neutral-50 p-4 dark:bg-neutral-950">
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-500 dark:text-neutral-400">
              Pipeline
            </p>
            <ol className="mt-3 space-y-2 text-xs text-neutral-600 dark:text-neutral-300">
              <li className="flex gap-2">
                <span className="font-semibold text-violet-600 dark:text-violet-400">
                  1.
                </span>
                ResNet-18 encodes the uploaded image
              </li>
              <li className="flex gap-2">
                <span className="font-semibold text-violet-600 dark:text-violet-400">
                  2.
                </span>
                Vector truncated to {mrlDimension} dimensions
              </li>
              <li className="flex gap-2">
                <span className="font-semibold text-violet-600 dark:text-violet-400">
                  3.
                </span>
                FAISS returns nearest catalog neighbors
              </li>
            </ol>
          </div>
        </aside>
      </div>
    </div>
  );
}
