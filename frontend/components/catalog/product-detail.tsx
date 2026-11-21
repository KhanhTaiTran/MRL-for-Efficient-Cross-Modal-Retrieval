"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { formatPrice, type CatalogProduct } from "lib/api/catalog";
import { useRouter } from "next/navigation";
import { useAuth } from "components/auth/auth-provider";
import { setCartItem } from "lib/api/commerce";
import { ProductEngagement, WishlistButton } from "./product-engagement";
import { categoryLabel, displayText } from "lib/display-text";
import { ArrowLeft, ArrowUpRight, ShoppingBag } from "lucide-react";

export function ProductDetail({ product }: { product: CatalogProduct }) {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [adding, setAdding] = useState(false);
  const [cartMessage, setCartMessage] = useState("");
  const [variantID, setVariantID] = useState(
    product.default_variant_id || product.variants?.[0]?.id || "",
  );
  const [image, setImage] = useState(product.image_url);
  const [backHref, setBackHref] = useState("/search");
  useEffect(() => {
    try {
      const lastCatalog = sessionStorage.getItem("aurafind-catalog-url");
      if (lastCatalog && /^\/search(?:\?|$)/.test(lastCatalog))
        setBackHref(lastCatalog);
    } catch {
      /* Storage is optional. */
    }
  }, []);
  const name = displayText(product.name);
  const variant = product?.variants?.find((value) => value.id === variantID);
  return (
    <>
      <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 sm:py-10 lg:px-8">
        <Link
          href={backHref}
          className="inline-flex min-h-11 items-center gap-2 text-sm text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" /> Back to products
        </Link>
        {
          <div className="mt-5 grid gap-8 md:grid-cols-2 lg:gap-16">
            <div className="min-w-0">
              <div className="aspect-[3/4] max-h-[680px] overflow-hidden rounded-2xl border border-neutral-200 bg-white dark:border-neutral-800">
                <img
                  src={image}
                  alt={name}
                  className="h-full w-full object-contain"
                />
              </div>
              {(product.images?.length ?? 0) > 1 && (
                <div className="mt-4 flex flex-wrap gap-3">
                  {product.images?.map((value) => (
                    <button
                      key={value.id}
                      onClick={() => setImage(value.url)}
                      aria-label={`View ${displayText(value.alt) || name}`}
                      aria-pressed={image === value.url}
                      className={`h-20 w-16 overflow-hidden rounded-lg border-2 bg-white transition ${image === value.url ? "border-neutral-900 dark:border-white" : "border-transparent hover:border-neutral-300 dark:hover:border-neutral-600"}`}
                    >
                      <img
                        src={value.url}
                        alt={displayText(value.alt)}
                        className="h-full w-full object-contain"
                      />
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="min-w-0 py-2 lg:py-5">
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                {displayText(product.brand)}
              </p>
              <h1 className="mt-3 text-2xl font-semibold tracking-tight break-words text-balance sm:text-3xl lg:text-4xl">
                {name}
              </h1>
              <p className="mt-5 text-2xl font-semibold">
                {formatPrice(variant?.price ?? product.price, product.currency)}
              </p>
              {product.commerce_data_note && (
                <p className="mt-3 text-xs leading-5 text-neutral-500 dark:text-neutral-400">
                  {product.commerce_data_note}
                </p>
              )}
              <p className="mt-4 text-sm text-neutral-500 dark:text-neutral-400">
                {product.review_count > 0 && product.rating_average !== null
                  ? `${product.rating_average.toFixed(1)} out of 5 · ${product.review_count} reviews`
                  : "No reviews yet"}
              </p>
              <p className="mt-8 whitespace-pre-line text-sm leading-7 text-neutral-600 dark:text-neutral-300">
                {displayText(product.description)}
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
              <p className="mt-5 text-sm text-neutral-500 dark:text-neutral-400">
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
                className="mt-6 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                <ShoppingBag className="h-4 w-4" />
                {adding ? "Adding…" : "Add to cart"}
              </button>
              {cartMessage && (
                <p role="alert" className="mt-3 text-sm text-red-600">
                  {cartMessage}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-3">
                <WishlistButton id={product.id} handle={product.handle} />
                <Link
                  href={`/discover?similar=${encodeURIComponent(product.handle)}`}
                  className="inline-flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl border border-neutral-300 px-4 py-3 text-sm font-medium transition hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                >
                  Find similar styles <ArrowUpRight className="h-4 w-4" />
                </Link>
              </div>
              <p className="mt-8 text-xs uppercase tracking-wider text-neutral-500 dark:text-neutral-400">
                {categoryLabel(product.category)}
              </p>
            </div>
          </div>
        }
        <ProductEngagement handle={product.handle} />
      </div>
    </>
  );
}
