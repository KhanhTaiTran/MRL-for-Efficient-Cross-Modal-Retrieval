"use client";

import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
import { CatalogSourceNote } from "components/catalog/catalog-source-note";

export function StoreHeader() {
  const { user } = useAuth();
  return (
    <>
      <header className="border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-950">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-5 sm:px-8"
        >
          <Link href="/" className="text-sm font-semibold tracking-[0.18em]">
            AURAFIND
          </Link>
          <div className="flex items-center gap-6 text-sm">
            <Link href="/search">Shop</Link>
            <Link href="/cart">Cart</Link>
            <Link href="/wishlist">Saved</Link>
            {user?.role === "admin" && <Link href="/admin">Admin</Link>}
            <Link href="/account">{user ? user.name : "Account"}</Link>
          </div>
        </nav>
      </header>
      <CatalogSourceNote />
    </>
  );
}
