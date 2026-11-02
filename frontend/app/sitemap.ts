import { getSitemapProducts } from "lib/api/server-catalog";
import { baseUrl } from "lib/utils";
import type { MetadataRoute } from "next";

export const dynamic = "force-dynamic";
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const products = await getSitemapProducts();
  return ["", "/search"]
    .map((path) => ({ url: `${baseUrl}${path}` }))
    .concat(
      products.map((product) => ({
        url: `${baseUrl}/product/${product.handle}`,
      })),
    );
}
