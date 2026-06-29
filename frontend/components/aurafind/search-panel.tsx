"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, Loader2, Search, X } from "lucide-react";
import { AiPrecisionSlider } from "./ai-precision-slider";

export interface SearchPanelProps {
  query: string;
  onQueryChange: (value: string) => void;
  onTextSearch: () => void;
  onImageSelect: (file: File) => void;
  onClearImage: () => void;
  imagePreview: string | null;
  imageFileName: string | null;
  isImageMode: boolean;
  onImageModeChange: (imageMode: boolean) => void;
  mrlDimension: number;
  onMrlDimensionChange: (dimension: number) => void;
  isLoading: boolean;
  searchFocused: boolean;
  onSearchFocusChange: (focused: boolean) => void;
  onDropImage: (file: File) => void;
  /** Always show the MRL slider (mobile main content) */
  alwaysShowSlider?: boolean;
  /** Compact variant for tablet header */
  compact?: boolean;
  className?: string;
}

export function SearchPanel({
  query,
  onQueryChange,
  onTextSearch,
  onImageSelect,
  onClearImage,
  imagePreview,
  imageFileName,
  isImageMode,
  onImageModeChange,
  mrlDimension,
  onMrlDimensionChange,
  isLoading,
  searchFocused,
  onSearchFocusChange,
  onDropImage,
  alwaysShowSlider = false,
  compact = false,
  className,
}: SearchPanelProps) {
  const showSlider =
    alwaysShowSlider || searchFocused || isImageMode || isLoading;

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files?.[0];
        if (file?.type.startsWith("image/")) {
          onDropImage(file);
        }
      }}
      className={clsx(
        "rounded-2xl border bg-white/90 p-2 shadow-sm transition-all duration-300 dark:bg-neutral-900/90",
        searchFocused
          ? "border-neutral-900 shadow-md dark:border-white/30"
          : "border-neutral-200 dark:border-neutral-800",
        className,
      )}
    >
      <AnimatePresence mode="wait">
        {isImageMode && imagePreview ? (
          <motion.div
            key="image-preview"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="flex items-center gap-3 px-2 py-1.5"
          >
            <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg ring-1 ring-neutral-200 dark:ring-neutral-700">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imagePreview}
                alt="Search reference"
                className="h-full w-full object-cover"
              />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-neutral-900 dark:text-white">
                Image search active
              </p>
              <p className="truncate text-[11px] text-neutral-500">
                {imageFileName ?? "Uploaded image"}
              </p>
            </div>
            <button
              type="button"
              onClick={onClearImage}
              className="rounded-full p-1.5 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-900 dark:hover:bg-neutral-800 dark:hover:text-white"
              aria-label="Clear image"
            >
              <X className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onTextSearch}
              disabled={isLoading}
              className="flex h-9 w-9 items-center justify-center rounded-xl bg-neutral-900 text-white transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 dark:bg-white dark:text-neutral-900"
              aria-label="Search by image"
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </button>
          </motion.div>
        ) : (
          <motion.div
            key="text-input"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="relative flex items-center"
          >
            <input
              type="text"
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              onFocus={() => onSearchFocusChange(true)}
              onBlur={() => {
                setTimeout(() => onSearchFocusChange(false), 150);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isLoading) {
                  onTextSearch();
                }
              }}
              placeholder={
                compact
                  ? "Describe your style or drop an image..."
                  : "Describe your style (e.g., A red summer dress) or drop an image..."
              }
              disabled={isLoading}
              className={clsx(
                "w-full bg-transparent pl-3 text-neutral-900 placeholder:text-neutral-400 outline-none disabled:opacity-60 dark:text-white",
                compact
                  ? "py-2 pr-20 text-sm"
                  : "py-2.5 pr-24 text-sm sm:text-base",
              )}
            />
            <div className="absolute right-1 flex items-center gap-1">
              <button
                type="button"
                onClick={onTextSearch}
                disabled={isLoading || !query.trim()}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-neutral-600 transition-all hover:bg-neutral-100 hover:text-neutral-900 disabled:opacity-40 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-white"
                aria-label="Text search"
              >
                {isLoading && !isImageMode ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
              </button>
              <label className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-xl text-neutral-600 transition-all hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-white">
                <Camera className="h-4 w-4" />
                <input
                  title="Upload an image"
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      onImageSelect(file);
                      onImageModeChange(true);
                    }
                  }}
                />
              </label>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AiPrecisionSlider
        value={mrlDimension}
        onChange={onMrlDimensionChange}
        disabled={isLoading}
        visible={showSlider}
      />
    </div>
  );
}
