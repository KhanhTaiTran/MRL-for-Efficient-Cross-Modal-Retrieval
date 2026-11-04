"use client";

import { useState } from "react";
import Link from "next/link";
import { formatPrice, type CatalogProduct } from "lib/api/catalog";
import { StoreHeader } from "components/layout/store-header";
import { useRouter } from "next/navigation";
import { useAuth } from "components/auth/auth-provider";
import { setCartItem } from "lib/api/commerce";
import { ProductEngagement } from "./product-engagement";

export function ProductDetail({ product }: { product: CatalogProduct }) {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [adding, setAdding] = useState(false);
  const [cartMessage, setCartMessage] = useState("");
  const [variantID, setVariantID] = useState(
    product.default_variant_id || product.variants?.[0]?.id || "",
  );
  const [image, setImage] = useState(product.image_url);
  const variant = product?.variants?.find((value) => value.id === variantID);
  return (
    <>
      <StoreHeader />
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <Link
          href="/search"
          className="text-sm text-neutral-500 underline underline-offset-4"
        >
          Back to products
        </Link>
        {
          <div className="mt-8 grid gap-10 md:grid-cols-2 lg:gap-16">
            <div>
              <div className="aspect-[3/4] overflow-hidden rounded-2xl bg-white">
                <img
                  src={image}
                  alt={product.name}
                  className="h-full w-full object-contain"
                />
              </div>
              {(product.images?.length ?? 0) > 1 && (
                <div className="mt-4 flex flex-wrap gap-3">
                  {product.images?.map((value) => (
                    <button
                      key={value.id}
                      onClick={() => setImage(value.url)}
                      aria-label={`View ${value.alt || product.name}`}
                      aria-pressed={image === value.url}
                      className="h-20 w-16 overflow-hidden rounded-lg border"
                    >
                      <img
                        src={value.url}
                        alt={value.alt}
                        className="h-full w-full object-contain"
                      />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="py-3">
              <p className="text-sm text-neutral-500">{product.brand}</p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                {product.name}
              </h1>
              <p className="mt-5 text-2xl font-semibold">
                {formatPrice(variant?.price ?? product.price, product.currency)}
              </p>
              {product.commerce_data_note && (
                <p className="mt-3 text-xs leading-5 text-neutral-500">
                  {product.commerce_data_note}
                </p>
              )}
              <p className="mt-4 text-sm text-neutral-500">
                {product.review_count > 0 && product.rating_average !== null
                  ? `${product.rating_average.toFixed(1)} out of 5 · ${product.review_count} reviews`
                  : "No reviews yet"}
              </p>
              <p className="mt-8 whitespace-pre-line text-sm leading-7 text-neutral-600 dark:text-neutral-300">
                {product.description}
              </p>
              {!!product.variants?.length && (
                <fieldset className="mt-8">
                  <legend className="text-sm font-medium">Options</legend>
                  <div className="mt-3 flex flex-wrap gap-3">
                    {product.variants.map((value) => (
                      <button
                        key={value.id}
                        aria-pressed={variantID === value.id}
                        onClick={() => setVariantID(value.id)}
                        className={`rounded-lg border px-4 py-2 text-sm ${variantID === value.id ? "border-neutral-900 dark:border-white" : "border-neutral-300 dark:border-neutral-700"}`}
                      >
                        {[value.size, value.color]
                          .filter(Boolean)
                          .join(" / ") || "Default"}
                      </button>
                    ))}
                  </div>
                </fieldset>
              )}
              <p className="mt-5 text-sm text-neutral-500">
                {variant?.is_available && variant.stock > 0
                  ? "In stock"
                  : "Out of stock"}
              </p>
              <button
                type="button"
                disabled={
                  loading ||
                  adding ||
                  !variant?.is_available ||
                  variant.stock < 1
                }
                onClick={async () => {
                  if (!user) {
                    router.push(
                      `/login?next=${encodeURIComponent(`/product/${product.handle}`)}`,
                    );
                    return;
                  }
                  if (!variant) return;
                  setAdding(true);
                  setCartMessage("");
                  try {
                    await setCartItem(variant.id, 1);
                    router.push("/cart");
                  } catch (error) {
                    setCartMessage(
                      error instanceof Error
                        ? error.message
                        : "Please try again.",
                    );
                  } finally {
                    setAdding(false);
                  }
                }}
                className="mt-6 block rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
              >
                {adding ? "Adding…" : "Add to cart"}
              </button>
              {cartMessage && (
                <p role="alert" className="mt-3 text-sm text-red-600">
                  {cartMessage}
                </p>
              )}
              <Link
                href={`/?similar=${encodeURIComponent(product.handle)}`}
                className="mt-8 inline-block rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white dark:bg-white dark:text-neutral-900"
              >
                Find similar styles
              </Link>
              <p className="mt-8 text-xs uppercase tracking-wider text-neutral-500">
                {product.category}
              </p>
            </div>
          </div>
        }
        <ProductEngagement id={product.id} handle={product.handle} />
      </div>
    </>
  );
}
