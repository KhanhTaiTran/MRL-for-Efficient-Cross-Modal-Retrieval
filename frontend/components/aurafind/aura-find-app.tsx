"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, Cpu, Sparkles, Zap } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { AuraFindHeader } from "./header";
import { HeroBanner, TrendingGrid } from "./home-content";
import {
  MobileBottomNav,
  type MobileNavTab,
} from "./mobile-bottom-nav";
import { ProductCard } from "./product-card";
import { ProductSkeleton } from "./product-skeleton";
import { SearchPanel } from "./search-panel";
import {
  fetchProductImageAsFile,
  getSearchErrorMessage,
  searchByImage,
  searchByText,
} from "./search-api";
import {
  DEFAULT_MRL_DIMENSION,
  enrichProduct,
  type EnrichedProduct,
  type SearchResultItem,
} from "./types";

import { PRODUCT_GRID_CLASS } from "./constants";

export function AuraFindApp() {
  const [query, setQuery] = useState("");
  const [mrlDimension, setMrlDimension] = useState(DEFAULT_MRL_DIMENSION);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [results, setResults] = useState<EnrichedProduct[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [activeDimension, setActiveDimension] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cartCount, setCartCount] = useState(0);
  const [searchFocused, setSearchFocused] = useState(false);
  const [mobileNavTab, setMobileNavTab] = useState<MobileNavTab>("home");

  const [isImageMode, setIsImageMode] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [scanningProductId, setScanningProductId] = useState<string | null>(
    null,
  );

  const previewUrlRef = useRef<string | null>(null);
  const mobileSearchRef = useRef<HTMLDivElement>(null);

  const applyImageFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) {
      toast.error("Please upload a valid image file.");
      return;
    }

    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
    }

    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;
    setSelectedFile(file);
    setPreviewUrl(url);
    setIsImageMode(true);
    setMobileNavTab("search");
  }, []);

  const clearImage = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setSelectedFile(null);
    setPreviewUrl(null);
    setIsImageMode(false);
  }, []);

  const runSearch = useCallback(
    async (mode: "text" | "image", file?: File) => {
      setIsLoading(true);
      setError(null);
      setResults([]);
      setLatencyMs(null);
      setActiveDimension(null);
      setHasSearched(true);
      setMobileNavTab("search");

      try {
        const payload =
          mode === "text"
            ? await searchByText(query, mrlDimension)
            : await searchByImage(file ?? selectedFile!, mrlDimension);

        setResults(payload.data.map(enrichProduct));
        setLatencyMs(payload.search_latency_ms);
        setActiveDimension(payload.mrl_dimension);

        if (payload.data.length === 0) {
          toast.message("No matches found. Try adjusting AI precision.");
        }
      } catch (err) {
        const message = getSearchErrorMessage(err);
        setError(message);
        toast.error(message);
      } finally {
        setIsLoading(false);
        setScanningProductId(null);
      }
    },
    [query, mrlDimension, selectedFile],
  );

  const handleTextSearch = () => {
    if (isImageMode && selectedFile) {
      void runSearch("image");
      return;
    }

    if (!query.trim()) {
      toast.error("Describe your style to search.");
      return;
    }

    void runSearch("text");
  };

  const handleFindSimilar = async (product: EnrichedProduct) => {
    setScanningProductId(product.product_id);
    setIsLoading(true);
    setError(null);
    setHasSearched(true);
    setMobileNavTab("search");

    try {
      const file = await fetchProductImageAsFile(product.product_id);
      applyImageFile(file);
      const payload = await searchByImage(file, mrlDimension);

      setResults(payload.data.map(enrichProduct));
      setLatencyMs(payload.search_latency_ms);
      setActiveDimension(payload.mrl_dimension);
      toast.success(`Similar styles to "${product.caption}"`);
    } catch (err) {
      const message = getSearchErrorMessage(err);
      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
      setScanningProductId(null);
    }
  };

  const resetHome = () => {
    setHasSearched(false);
    setResults([]);
    setError(null);
    setLatencyMs(null);
    setActiveDimension(null);
    setQuery("");
    clearImage();
    setMobileNavTab("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const scrollToMobileSearch = () => {
    setMobileNavTab("search");
    mobileSearchRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    const input = mobileSearchRef.current?.querySelector("input[type='text']");
    if (input instanceof HTMLInputElement) {
      setTimeout(() => input.focus(), 350);
    }
  };

  const handleAddToCart = (_product: SearchResultItem) => {
    setCartCount((count) => count + 1);
    toast.success("Added to cart");
  };

  const searchPanelProps = {
    query,
    onQueryChange: setQuery,
    onTextSearch: handleTextSearch,
    onImageSelect: applyImageFile,
    onClearImage: clearImage,
    imagePreview: previewUrl,
    imageFileName: selectedFile?.name ?? null,
    isImageMode,
    onImageModeChange: setIsImageMode,
    mrlDimension,
    onMrlDimensionChange: setMrlDimension,
    isLoading,
    searchFocused,
    onSearchFocusChange: setSearchFocused,
    onDropImage: applyImageFile,
  };

  return (
    <div className="min-h-dvh bg-neutral-50 pb-[calc(4.5rem+env(safe-area-inset-bottom))] text-neutral-900 md:pb-0 dark:bg-neutral-950 dark:text-white">
      <AuraFindHeader
        {...searchPanelProps}
        cartCount={cartCount}
        onLogoClick={resetHome}
        onCartClick={() => {
          setMobileNavTab("cart");
          toast.message(`${cartCount} item${cartCount === 1 ? "" : "s"} in cart`);
        }}
        onProfileClick={() => {
          setMobileNavTab("profile");
          toast.message("Profile coming soon");
        }}
      />

      {/* Mobile search — top of main content, hidden md+ */}
      <div
        ref={mobileSearchRef}
        className="sticky top-[57px] z-40 border-b border-neutral-200/80 bg-neutral-50/95 px-4 py-3 backdrop-blur-xl md:hidden dark:border-neutral-800 dark:bg-neutral-950/95"
      >
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-neutral-500">
          AI Visual Search
        </p>
        <SearchPanel {...searchPanelProps} alwaysShowSlider />
      </div>

      <AnimatePresence mode="wait">
        {!hasSearched && !isLoading ? (
          <motion.div
            key="home"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.35 }}
          >
            <HeroBanner />
            <TrendingGrid />
          </motion.div>
        ) : (
          <motion.div
            key="results"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8 lg:px-8"
          >
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="mb-6 flex flex-wrap items-center gap-2 rounded-2xl border border-neutral-200/80 bg-white/70 px-3 py-2.5 backdrop-blur-xl sm:mb-8 sm:gap-3 sm:px-5 sm:py-3 dark:border-neutral-800 dark:bg-neutral-900/70"
            >
              <div className="flex items-center gap-2 text-xs text-neutral-700 sm:text-sm dark:text-neutral-200">
                <Sparkles className="h-4 w-4 shrink-0 text-violet-500" />
                {isLoading ? (
                  <span>Searching vector index…</span>
                ) : (
                  <span>
                    Found{" "}
                    <strong className="font-semibold tabular-nums">
                      {results.length}
                    </strong>{" "}
                    results
                    {latencyMs !== null && activeDimension !== null && (
                      <>
                        {" "}
                        in{" "}
                        <strong className="tabular-nums">
                          {latencyMs.toFixed(1)} ms
                        </strong>{" "}
                        using{" "}
                        <strong className="tabular-nums">
                          {activeDimension}
                        </strong>
                        -dim vectors
                      </>
                    )}
                  </span>
                )}
              </div>

              {!isLoading && latencyMs !== null && activeDimension !== null && (
                <>
                  <span className="hidden h-4 w-px bg-neutral-200 md:block dark:bg-neutral-700" />
                  <div className="hidden items-center gap-1.5 rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-xs text-neutral-600 md:flex dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                    <Zap className="h-3.5 w-3.5 text-emerald-500" />
                    <span className="tabular-nums">{latencyMs.toFixed(1)} ms</span>
                  </div>
                  <div className="hidden items-center gap-1.5 rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-xs text-neutral-600 md:flex dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                    <Cpu className="h-3.5 w-3.5 text-violet-500" />
                    <span className="tabular-nums">
                      {activeDimension}-dim vectors
                    </span>
                  </div>
                </>
              )}
            </motion.div>

            {error && !isLoading && (
              <div className="mb-6 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>{error}</p>
              </div>
            )}

            <div className={PRODUCT_GRID_CLASS}>
              {isLoading && !scanningProductId
                ? Array.from({ length: 8 }).map((_, i) => (
                    <ProductSkeleton key={i} />
                  ))
                : results.map((product, index) => (
                    <ProductCard
                      key={`${product.product_id}-${index}`}
                      product={product}
                      index={index}
                      onFindSimilar={handleFindSimilar}
                      onAddToCart={() => handleAddToCart(product)}
                      isScanning={scanningProductId === product.product_id}
                    />
                  ))}
            </div>

            {!isLoading && !error && results.length === 0 && (
              <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-neutral-300 py-16 text-center dark:border-neutral-700">
                <p className="text-sm text-neutral-500">
                  No results yet. Refine your search or adjust AI precision.
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <MobileBottomNav
        activeTab={mobileNavTab}
        cartCount={cartCount}
        onHome={resetHome}
        onSearch={scrollToMobileSearch}
        onCart={() => {
          setMobileNavTab("cart");
          toast.message(`${cartCount} item${cartCount === 1 ? "" : "s"} in cart`);
        }}
        onProfile={() => {
          setMobileNavTab("profile");
          toast.message("Profile coming soon");
        }}
      />
    </div>
  );
}
