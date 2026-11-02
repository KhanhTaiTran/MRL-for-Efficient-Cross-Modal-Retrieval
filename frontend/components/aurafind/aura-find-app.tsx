"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AuraFindHeader } from "./header";
import { HeroBanner } from "./home-content";
import { CatalogBrowser } from "components/catalog/catalog-browser";
import { getProduct, productForCard } from "lib/api/catalog";
import { useRouter } from "next/navigation";
import { MobileBottomNav, type MobileNavTab } from "./mobile-bottom-nav";
import { ProductCard } from "./product-card";
import { ProductSkeleton } from "./product-skeleton";
import { SearchPanel } from "./search-panel";
import {
  fetchSearchConfig,
  fetchProductImageAsFile,
  getSearchErrorMessage,
  searchByImage,
  searchByText,
} from "./search-api";
import {
  DEFAULT_MRL_DIMENSION,
  enrichProduct,
  type EnrichedProduct,
} from "./types";

import { PRODUCT_GRID_CLASS } from "./constants";

export function AuraFindApp() {
  const [query, setQuery] = useState("");
  const [searchReady, setSearchReady] = useState(false);
  useEffect(() => {
    fetchSearchConfig()
      .then((c) => {
        setSearchReady(c.supported_dims.length > 0);
        setMrlDimension(c.default_dim);
      })
      .catch((err) => toast.error(getSearchErrorMessage(err)));
  }, []);

  const [mrlDimension, setMrlDimension] = useState(DEFAULT_MRL_DIMENSION);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [results, setResults] = useState<EnrichedProduct[]>([]);
  const retrievalMode = "adaptive" as const;
  const [error, setError] = useState<string | null>(null);
  const cartCount = 0;
  const router = useRouter();
  const initialSimilar = useRef(false);
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

      setHasSearched(true);
      setMobileNavTab("search");

      try {
        const payload =
          mode === "text"
            ? await searchByText(query, mrlDimension, retrievalMode)
            : await searchByImage(
                file ?? selectedFile!,
                mrlDimension,
                retrievalMode,
              );

        setResults(payload.data.map(enrichProduct));

        if (payload.data.length === 0) {
          toast.message("No products found. Try a different description.");
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
    [query, mrlDimension, selectedFile, retrievalMode],
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
      const file = await fetchProductImageAsFile(
        product.product_id,
        product.image_url,
        product.displayName,
      );
      applyImageFile(file);
      const payload = await searchByImage(file, mrlDimension, retrievalMode);

      setResults(payload.data.map(enrichProduct));
      toast.success(`Similar styles to "${product.displayName}"`);
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

  useEffect(() => {
    if (!searchReady || initialSimilar.current) return;
    const handle = new URLSearchParams(window.location.search).get("similar");
    if (!handle) return;
    initialSimilar.current = true;
    getProduct(handle)
      .then(({ data }) => handleFindSimilar(productForCard(data)))
      .catch((error) => toast.error(getSearchErrorMessage(error)));
  }, [searchReady]);

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
    isLoading: isLoading || !searchReady,
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
          toast.message("Your shopping bag will be available soon.");
        }}
        onProfileClick={() => {
          setMobileNavTab("profile");
          router.push("/account");
        }}
      />

      {/* Mobile search — top of main content, hidden md+ */}
      <div
        ref={mobileSearchRef}
        className="sticky top-[57px] z-40 border-b border-neutral-200/80 bg-neutral-50/95 px-4 py-3 backdrop-blur-xl md:hidden dark:border-neutral-800 dark:bg-neutral-950/95"
      >
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-neutral-500">
          Find products
        </p>
        <SearchPanel {...searchPanelProps} />
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
            <CatalogBrowser preview onFindSimilar={handleFindSimilar} />
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
            <div
              className="mb-6 flex items-baseline justify-between gap-4"
              aria-live="polite"
            >
              <h2 className="text-lg font-semibold tracking-tight sm:text-xl">
                {isLoading ? "Searching for products…" : "Search results"}
              </h2>
              {!isLoading && !error && (
                <p className="text-sm text-neutral-500">
                  {results.length}{" "}
                  {results.length === 1 ? "product" : "products"}
                </p>
              )}
            </div>

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
                      isScanning={scanningProductId === product.product_id}
                    />
                  ))}
            </div>

            {!isLoading && !error && results.length === 0 && (
              <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-neutral-300 py-16 text-center dark:border-neutral-700">
                <p className="text-sm text-neutral-500">
                  No matching products. Try a different description or upload an
                  image.
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
          toast.message("Your shopping bag will be available soon.");
        }}
        onProfile={() => {
          setMobileNavTab("profile");
          router.push("/account");
        }}
      />
    </div>
  );
}
