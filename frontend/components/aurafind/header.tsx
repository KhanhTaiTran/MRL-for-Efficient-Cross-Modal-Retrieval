"use client";

import Image from "next/image";
import Link from "next/link";
import { ShoppingBag, User } from "lucide-react";
import { SearchPanel, type SearchPanelProps } from "./search-panel";

type HeaderSearchProps = Pick<
  SearchPanelProps,
  | "query"
  | "onQueryChange"
  | "onTextSearch"
  | "onImageSelect"
  | "onClearImage"
  | "imagePreview"
  | "imageFileName"
  | "isImageMode"
  | "onImageModeChange"
  | "mrlDimension"
  | "onMrlDimensionChange"
  | "isLoading"
  | "searchFocused"
  | "onSearchFocusChange"
  | "onDropImage"
>;

interface AuraFindHeaderProps extends HeaderSearchProps {
  cartCount: number;
  onLogoClick?: () => void;
  onCartClick?: () => void;
  onProfileClick?: () => void;
}

export function AuraFindHeader({
  cartCount,
  onLogoClick,
  onCartClick,
  onProfileClick,
  ...searchProps
}: AuraFindHeaderProps) {
  return (
    <header className="sticky top-0 z-50 border-b border-neutral-200/80 bg-white/80 backdrop-blur-xl dark:border-neutral-800 dark:bg-neutral-950/80">
      <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-4 py-3 sm:gap-4 sm:px-6 lg:px-8">
        {/* Logo */}
        <Link
          href="/"
          onClick={onLogoClick}
          className="flex shrink-0 items-center gap-2.5"
        >
          <div className="relative h-9 w-9 overflow-hidden rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
            <Image
              src="/logo-aurafind.png"
              alt="AuraFind"
              width={36}
              height={36}
              className="h-full w-full object-contain p-1"
              priority
            />
          </div>
          <span className="hidden text-sm font-semibold tracking-[0.18em] uppercase text-neutral-900 sm:block dark:text-white">
            AuraFind
          </span>
        </Link>

        {/* Tablet search (md–lg): compact */}
        <div className="hidden min-w-0 flex-1 md:block lg:hidden md:max-w-xs">
          <SearchPanel {...searchProps} compact className="w-full" />
        </div>

        {/* Desktop search (lg+): full width */}
        <div className="hidden min-w-0 flex-1 lg:mx-auto lg:block lg:max-w-[40%]">
          <SearchPanel {...searchProps} className="w-full" />
        </div>

        {/* Desktop cart + profile — hidden on mobile (bottom nav) */}
        <div className="ml-auto hidden shrink-0 items-center gap-2 md:flex sm:gap-3">
          <button
            type="button"
            onClick={onCartClick}
            className="relative flex h-10 w-10 items-center justify-center rounded-full border border-neutral-200 text-neutral-700 transition-colors hover:bg-neutral-50 dark:border-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-900"
            aria-label="Shopping cart"
          >
            <ShoppingBag className="h-4 w-4" />
            {cartCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-neutral-900 px-1 text-[10px] font-semibold text-white dark:bg-white dark:text-neutral-900">
                {cartCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={onProfileClick}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-neutral-200 text-neutral-700 transition-colors hover:bg-neutral-50 dark:border-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-900"
            aria-label="User profile"
          >
            <User className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
