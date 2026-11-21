"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSearch } from "components/aurafind/search-provider";
export function SiteFooter() {
  const admin = usePathname().startsWith("/admin");
  const { config } = useSearch();
  return (
    <footer className="mt-auto border-t border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900/40">
      <div className={`site-container ${admin ? "py-6" : "py-10 sm:py-12"}`}>
        <div className="flex flex-col justify-between gap-7 sm:flex-row sm:items-start">
          <div className="max-w-md">
            <Link
              href="/"
              className="text-sm font-semibold uppercase tracking-[0.18em]"
            >
              AuraFind
            </Link>
            {!admin && (
              <p className="mt-3 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                Find your next favourite. Describe a look, bring a reference, or
                explore the collection.
              </p>
            )}
          </div>
          <nav
            aria-label="Footer navigation"
            className="flex flex-wrap gap-x-6 gap-y-4 text-sm"
          >
            <Link href="/search">Shop</Link>
            <Link href="/wishlist">Saved items</Link>
            <Link href="/account/orders">My orders</Link>
            <Link href="/account">Account</Link>
          </nav>
        </div>
        <div className="mt-7 flex flex-col justify-between gap-3 border-t border-neutral-200 pt-5 text-xs leading-5 text-neutral-500 dark:border-neutral-800 dark:text-neutral-400 sm:flex-row">
          <p>© {new Date().getFullYear()} AuraFind</p>
          <p className="max-w-xl sm:text-right">
            {config?.catalog_source === "FashionGen"
              ? "FashionGen photos and descriptions. "
              : ""}
            Prices and stock are simulated. Demo checkout does not charge money.
          </p>
        </div>
      </div>
    </footer>
  );
}
