export type SearchMode = "text" | "image";

export interface SearchResultItem {
  vector_id?: number;
  product_id: string;
  catalog_product_id?: string;
  handle?: string;
  image_url?: string;
  caption: string;
  name?: string;
  brand?: string;
  price?: number | null;
  currency?: string;
  rating_average?: number | null;
  review_count?: number;
  similarity_score?: number;
  distance?: number;
}

export interface SearchConfig {
  requested_dim: number;
  search_mode: string;
  stage1_dim: number;
  stage2_dim: number | null;
  aqe_enabled: boolean;
}

export interface SearchTiming {
  encode_ms: number;
  aqe_ms: number;
  stage1_ms: number;
  rerank_ms: number;
  worker_total_ms: number;
  http_overhead_ms?: number;
  request_total_ms?: number;
}

export interface SearchResponse {
  status: string;
  index_version?: string;
  mrl_dimension: number;
  search_latency_ms?: number;
  data: SearchResultItem[];
  search_config?: SearchConfig;
  timing?: SearchTiming;
}

export interface EnrichedProduct extends SearchResultItem {
  displayName: string;
  displayBrand: string;
  displayPrice: string | null;
  ratingAverage: number | null;
  reviewCount: number;
}

export const DEFAULT_MRL_DIMENSION = 512;
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export function getImageUrl(productId: string): string {
  return `${API_BASE_URL}/images/${productId}`;
}

export function enrichProduct(item: SearchResultItem): EnrichedProduct {
  // FashionGen captions begin with a brand followed by the first description sentence.
  const caption = item.caption.trim();
  const separator = caption.indexOf(". ");
  const displayBrand =
    item.brand?.trim() || (separator >= 0 ? caption.slice(0, separator) : "");
  const description =
    displayBrand && caption.startsWith(`${displayBrand}. `)
      ? caption.slice(displayBrand.length + 2)
      : caption;
  const displayName =
    item.name?.trim() ||
    description.split(/\.\s+/)[0]?.replace(/\.$/, "") ||
    "Product";
  const reviewCount =
    Number.isInteger(item.review_count) && item.review_count! > 0
      ? item.review_count!
      : 0;
  const ratingAverage =
    reviewCount > 0 &&
    item.rating_average != null &&
    Number.isFinite(item.rating_average) &&
    item.rating_average > 0 &&
    item.rating_average <= 5
      ? item.rating_average
      : null;
  const displayPrice =
    item.price != null && Number.isFinite(item.price) && item.price >= 0
      ? new Intl.NumberFormat("en-US", {
          style: "currency",
          currency: item.currency || "USD",
        }).format(item.price)
      : null;
  return {
    ...item,
    displayBrand,
    displayName,
    displayPrice,
    reviewCount,
    ratingAverage,
  };
}
