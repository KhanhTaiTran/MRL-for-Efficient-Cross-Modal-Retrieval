import "server-only";
import { cache } from "react";
import type { CatalogProduct, CatalogResponse } from "./catalog";

const base =
  process.env.API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8080";
export const getServerProduct = cache(
  async (handle: string): Promise<CatalogProduct | null> => {
    const response = await fetch(
      `${base}/api/products/${encodeURIComponent(handle)}`,
      { cache: "no-store", signal: AbortSignal.timeout(10000) },
    );
    if (response.status === 404) return null;
    if (!response.ok)
      throw new Error("The catalog is temporarily unavailable.");
    return (await response.json()).data as CatalogProduct;
  },
);
export async function getSitemapProducts(): Promise<CatalogProduct[]> {
  const products: CatalogProduct[] = [];
  for (let page = 1; ; page++) {
    const response = await fetch(
      `${base}/api/products?limit=100&page=${page}`,
      { cache: "no-store", signal: AbortSignal.timeout(10000) },
    );
    if (!response.ok)
      throw new Error("The catalog is temporarily unavailable.");
    const payload = (await response.json()) as CatalogResponse;
    products.push(...payload.data);
    if (page >= payload.pagination.pages) break;
  }
  return products;
}
