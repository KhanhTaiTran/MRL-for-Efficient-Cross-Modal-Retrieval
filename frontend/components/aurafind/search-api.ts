import {
  API_BASE_URL,
  type SearchResponse,
  type SearchResultItem,
} from "./types";

async function parseSearchResponse(
  response: Response,
): Promise<SearchResponse> {
  let payload: SearchResponse & { error?: string; message?: string };

  try {
    payload = await response.json();
  } catch {
    throw new Error("Invalid response from server.");
  }

  if (!response.ok) {
    throw new Error(
      payload.error ??
        payload.message ??
        `Request failed (${response.status})`,
    );
  }

  if (payload.status !== "success" || !Array.isArray(payload.data)) {
    throw new Error(
      payload.message ?? "Search returned an unexpected result.",
    );
  }

  return payload;
}

export async function searchByText(
  query: string,
  mrlDimension: number,
): Promise<SearchResponse> {
  const formData = new FormData();
  formData.append("query", query.trim());
  formData.append("mrl_dimension", String(mrlDimension));

  const response = await fetch(`${API_BASE_URL}/api/search/text`, {
    method: "POST",
    body: formData,
  });

  return parseSearchResponse(response);
}

export async function searchByImage(
  image: File,
  mrlDimension: number,
): Promise<SearchResponse> {
  const formData = new FormData();
  formData.append("image", image);
  formData.append("mrl_dimension", String(mrlDimension));

  const response = await fetch(`${API_BASE_URL}/api/search/image`, {
    method: "POST",
    body: formData,
  });

  return parseSearchResponse(response);
}

export async function fetchProductImageAsFile(
  productId: string,
): Promise<File> {
  const response = await fetch(`${API_BASE_URL}/images/${productId}`);

  if (!response.ok) {
    throw new Error("Could not load product image for similar search.");
  }

  const blob = await response.blob();
  return new File([blob], productId, {
    type: blob.type || "image/jpeg",
  });
}

export function getSearchErrorMessage(err: unknown): string {
  if (err instanceof TypeError) {
    return "Cannot reach the search backend. Is it running on localhost:8080?";
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

export type { SearchResultItem };
