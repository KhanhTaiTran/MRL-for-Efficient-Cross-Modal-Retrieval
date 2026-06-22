export type SearchMode = "text" | "image";

export interface SearchResultItem {
  product_id: string;
  caption: string;
  distance: number;
}

export interface SearchResponse {
  status: string;
  mrl_dimension: number;
  search_latency_ms: number;
  data: SearchResultItem[];
}

export interface TrendingProduct {
  id: string;
  name: string;
  price: string;
  image: string;
  category: string;
}

export interface EnrichedProduct extends SearchResultItem {
  price: string;
  matchScore: number;
}

export const MRL_DIMENSIONS = [8, 16, 32, 64, 128, 256, 512] as const; //set dims as const to make it a tuple of literal types
export const DEFAULT_MRL_DIMENSION = 512;
export const API_BASE_URL = "http://localhost:8080";

export function getImageUrl(productId: string): string {
  return `${API_BASE_URL}/images/${productId}`;
}

export function distanceToMatchScore(distance: number): number {
  return Math.max(1, Math.min(99, Math.round((1 - distance) * 100)));
}

export function mockPriceFromId(productId: string): string {
  let hash = 0;
  for (let i = 0; i < productId.length; i++) {
    hash += productId.charCodeAt(i);
  }
  return `$${((hash % 150) + 39).toFixed(2)}`;
}

export function enrichProduct(item: SearchResultItem): EnrichedProduct {
  return {
    ...item,
    price: mockPriceFromId(item.product_id),
    matchScore: distanceToMatchScore(item.distance),
  };
}
