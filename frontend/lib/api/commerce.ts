import { authenticatedRequest } from "./client";

export interface CartItem {
  variant_id: string;
  product_id: string;
  handle: string;
  name: string;
  sku: string;
  size: string;
  color: string;
  image_url: string;
  price_cents: number;
  quantity: number;
  stock: number;
  is_available: boolean;
  currency: string;
}
export interface Cart {
  items: CartItem[];
  subtotal_cents: number;
  shipping_cents: number;
  total_cents: number;
  currency: string;
  can_checkout: boolean;
  limit_exceeded: boolean;
}
export interface Address {
  name: string;
  line1: string;
  line2: string;
  city: string;
  region: string;
  postal_code: string;
  country: string;
}
export interface CheckoutInput {
  shipping_address: Address;
  items: { variant_id: string; quantity: number; price_cents: number }[];
  currency: string;
}
export interface Order {
  id: string;
  order_status: string;
  payment_status: string;
  payment_method: string;
  fulfillment_status: string;
  subtotal_cents: number;
  shipping_cents: number;
  total_cents: number;
  currency: string;
  shipping_address: Address;
  created_at: string;
  items?: Pick<
    CartItem,
    | "product_id"
    | "variant_id"
    | "name"
    | "sku"
    | "size"
    | "color"
    | "price_cents"
    | "quantity"
    | "image_url"
  >[];
}
export const getCart = () => authenticatedRequest<{ data: Cart }>("/cart");
function cartUpdated() {
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("aurafind-cart-updated"));
}
export const setCartItem = async (variant: string, quantity: number) => {
  const result = await authenticatedRequest<{ data: Cart }>(
    `/cart/items/${encodeURIComponent(variant)}`,
    {
      method: "PUT",
      body: JSON.stringify({ quantity }),
    },
  );
  cartUpdated();
  return result;
};
export const removeCartItem = async (variant: string) => {
  const result = await authenticatedRequest<{ data: Cart }>(
    `/cart/items/${encodeURIComponent(variant)}`,
    {
      method: "DELETE",
    },
  );
  cartUpdated();
  return result;
};
export const checkout = async (key: string, input: CheckoutInput) => {
  const result = await authenticatedRequest<{ data: Order; replayed: boolean }>(
    "/checkout",
    {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(input),
    },
  );
  cartUpdated();
  return result;
};
export const money = (cents: number, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    cents / 100,
  );
