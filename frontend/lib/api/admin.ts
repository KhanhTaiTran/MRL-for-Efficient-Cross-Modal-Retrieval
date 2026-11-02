import { authenticatedRequest, request } from "./client";
export interface AdminVariant {
  id: string;
  sku: string;
  size: string;
  color: string;
  price_cents: number;
  stock: number;
  is_available: boolean;
}
export interface AdminImage {
  id: string;
  url: string;
  alt: string;
  position: number;
  is_primary: boolean;
}
export interface AdminProduct {
  id: string;
  handle: string;
  name: string;
  description: string;
  brand: string;
  category: string;
  price_cents: number;
  currency: string;
  is_active: boolean;
  is_featured: boolean;
  revision: number;
  default_variant_id: string;
  search_status: string;
  variants?: AdminVariant[];
  images?: AdminImage[];
}
export interface IndexJob {
  id: string;
  status: string;
  index_version_id: string | null;
  error: string | null;
  created_at: string;
}
export interface IndexVersion {
  id: string;
  version_tag: string;
  num_vectors: number;
  is_active: boolean;
  built_at: string;
}
export const adminRequest = <T>(path: string, init?: RequestInit) =>
  authenticatedRequest<T>(`/admin${path}`, init);
export const servingIndex = () =>
  request<{ active_index_version: string }>("/search/config");
