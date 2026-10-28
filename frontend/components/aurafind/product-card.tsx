"use client";

import { motion } from "framer-motion";
import { Plus, Sparkles, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { getImageUrl, type EnrichedProduct } from "./types";

interface ProductCardProps {
  product: EnrichedProduct;
  index: number;
  onFindSimilar: (product: EnrichedProduct) => void;
  onAddToCart: () => void;
  isScanning?: boolean;
}

function useIsDesktopHover() {
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

export function ProductCard({
  product,
  index,
  onFindSimilar,
  onAddToCart,
  isScanning = false,
}: ProductCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const isDesktop = useIsDesktopHover();

  const showQuickAdd = isDesktop ? isHovered : true;
  const imageScale = isDesktop && isHovered ? 1.06 : 1;

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.45,
        delay: index * 0.06,
        ease: [0.22, 1, 0.36, 1],
      }}
      onMouseEnter={() => isDesktop && setIsHovered(true)}
      onMouseLeave={() => isDesktop && setIsHovered(false)}
      className="group relative"
    >
      <div className="relative overflow-hidden rounded-2xl bg-neutral-100 dark:bg-neutral-900">
        <div className="relative aspect-[3/4] overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <motion.img
            src={getImageUrl(product.product_id)}
            alt={product.displayName}
            crossOrigin="anonymous"
            loading="lazy"
            animate={{ scale: imageScale }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="h-full w-full bg-white object-contain"
          />

          {isScanning && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="absolute inset-0 bg-neutral-900/40 backdrop-blur-[2px]"
            >
              <motion.div
                animate={{ top: ["0%", "100%", "0%"] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: "linear" }}
                className="absolute inset-x-0 h-px bg-white/80 shadow-[0_0_20px_rgba(255,255,255,0.8)]"
              />
              <div className="flex h-full items-center justify-center">
                <span className="rounded-full border border-white/30 bg-white/15 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-md">
                  AI scanning…
                </span>
              </div>
            </motion.div>
          )}

          <button
            type="button"
            onClick={() => onFindSimilar(product)}
            disabled={isScanning}
            className="absolute right-2 top-2 flex items-center gap-1 rounded-full border border-white/25 bg-white/90 px-2 py-1 text-[10px] font-semibold text-neutral-900 shadow-lg shadow-black/10 backdrop-blur-md transition-all active:scale-95 disabled:opacity-60 sm:right-3 sm:top-3 sm:px-2.5 sm:py-1.5 sm:text-[11px] lg:hover:scale-105 lg:hover:bg-white dark:bg-neutral-900/90 dark:text-white"
          >
            <Sparkles className="h-3 w-3 text-violet-500" />
            <span className="hidden sm:inline">Find Similar</span>
            <span className="sm:hidden">Similar</span>
          </button>

          <motion.div
            initial={false}
            animate={{ y: showQuickAdd ? 0 : "100%" }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-x-0 bottom-0 p-2 sm:p-3"
          >
            <button
              type="button"
              onClick={onAddToCart}
              className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-neutral-900 py-2 text-[10px] font-semibold uppercase tracking-wider text-white transition-colors active:bg-neutral-700 sm:gap-2 sm:py-2.5 sm:text-xs lg:hover:bg-neutral-800 dark:bg-white dark:text-neutral-900 dark:active:bg-neutral-200 lg:dark:hover:bg-neutral-100"
            >
              <Plus className="h-3.5 w-3.5" />
              Quick Add
            </button>
          </motion.div>
        </div>
      </div>

      <div className="space-y-2 px-0.5 pb-1 pt-3 sm:px-1">
        {product.displayBrand && (
          <p className="truncate text-xs font-medium text-neutral-500 dark:text-neutral-400">
            {product.displayBrand}
          </p>
        )}
        <h3
          title={product.displayName}
          className="line-clamp-2 min-h-10 text-sm font-medium leading-5 text-neutral-900 dark:text-white"
        >
          {product.displayName}
        </h3>
        {product.ratingAverage !== null ? (
          <div
            className="flex flex-wrap items-center gap-1.5 text-xs"
            aria-label={`${product.ratingAverage} out of 5 stars, ${product.reviewCount} reviews`}
          >
            <span className="flex gap-0.5 text-amber-500" aria-hidden="true">
              {Array.from({ length: 5 }, (_, i) => (
                <span key={i} className="relative block h-3.5 w-3.5">
                  <Star className="h-3.5 w-3.5" />
                  <span
                    className="absolute inset-y-0 left-0 overflow-hidden"
                    style={{
                      width: `${Math.max(0, Math.min(1, product.ratingAverage! - i)) * 100}%`,
                    }}
                  >
                    <Star className="h-3.5 w-3.5 fill-current" />
                  </span>
                </span>
              ))}
            </span>
            <span className="tabular-nums text-neutral-600 dark:text-neutral-300">
              {product.ratingAverage.toFixed(1)} ({product.reviewCount})
            </span>
          </div>
        ) : (
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            No reviews yet
          </p>
        )}
        {product.displayPrice ? (
          <p className="text-base font-semibold tabular-nums tracking-tight text-neutral-900 sm:text-lg dark:text-white">
            {product.displayPrice}
          </p>
        ) : (
          <p className="text-sm font-medium text-neutral-500 dark:text-neutral-400">
            Price unavailable
          </p>
        )}
      </div>
    </motion.article>
  );
}
