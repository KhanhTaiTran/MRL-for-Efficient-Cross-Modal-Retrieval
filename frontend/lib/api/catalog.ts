import { request } from "./client";
import { enrichProduct } from "components/aurafind/types";

export interface ProductImage {
  id: string;
  url: string;
  alt: string;
  is_primary: boolean;
}
export interface ProductVariant {
  id: string;
  sku: string;
  size: string;
  color: string;
  price: number;
  stock: number;
  is_available: boolean;
}
export interface CatalogProduct {
  commerce_data_note?: string;
  id: string;
  handle: string;
  name: string;
  description: string;
  brand: string;
  category: string;
  price: number;
  currency: string;
  image_url: string;
  rating_average: number | null;
  review_count: number;
  is_featured: boolean;
  search_status: string;
  default_variant_id: string;
  images?: ProductImage[];
  variants?: ProductVariant[];
}
export interface CatalogResponse {
  data: CatalogProduct[];
  pagination: { page: number; limit: number; total: number; pages: number };
}
export const getProduct = (handle: string, signal?: AbortSignal) =>
  request<{ data: CatalogProduct }>(`/products/${encodeURIComponent(handle)}`, {
    signal,
  });
export function productForCard(product: CatalogProduct) {
  return enrichProduct({
    ...product,
    product_id: product.id,
    catalog_product_id: product.id,
    caption: product.description,
  });
}
export function formatPrice(price: number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    price,
  );
}
