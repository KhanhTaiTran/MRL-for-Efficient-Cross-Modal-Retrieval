import { ProductDetail } from "components/catalog/product-detail";
import { getServerProduct } from "lib/api/server-catalog";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ handle: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const product = await getServerProduct((await params).handle);
  if (!product) return { title: "Product not found" };
  return {
    title: product.name,
    description: product.description,
    openGraph: { images: product.image_url ? [product.image_url] : [] },
  };
}
export default async function ProductPage({ params }: Props) {
  const product = await getServerProduct((await params).handle);
  if (!product) notFound();
  return <ProductDetail product={product} />;
}
