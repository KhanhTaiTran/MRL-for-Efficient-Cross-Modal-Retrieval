"use client";

import Link from "next/link";
import { Package, MessageSquare, Layers } from "lucide-react";

export function AdminNav({
  active,
}: {
  active: "products" | "reviews" | "index";
}) {
  return (
    <nav
      aria-label="Administration"
      className="mb-8 flex gap-1 overflow-x-auto border-b border-neutral-200 dark:border-neutral-800"
    >
      {(
        [
          ["products", "/admin", "Products", Package],
          ["reviews", "/admin/reviews", "Reviews", MessageSquare],
          ["index", "/admin?tab=index", "Search index", Layers],
        ] as const
      ).map(([id, href, label, Icon]) => (
        <Link
          key={id}
          href={href}
          aria-current={active === id ? "page" : undefined}
          className={`flex shrink-0 items-center gap-2 border-b-2 px-4 py-4 text-sm font-medium transition-colors ${active === id ? "border-neutral-900 text-neutral-900 dark:border-white dark:text-white" : "border-transparent text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"}`}
        >
          <Icon className="h-4 w-4" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
