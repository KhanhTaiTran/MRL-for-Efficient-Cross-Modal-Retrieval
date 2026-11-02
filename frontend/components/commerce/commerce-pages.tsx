"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "components/auth/auth-provider";
import { StoreHeader } from "components/layout/store-header";
import { APIError, authenticatedRequest } from "lib/api/client";
import {
  checkout,
  money,
  removeCartItem,
  setCartItem,
  type Address,
  type Cart,
  type CheckoutInput,
  type Order,
} from "lib/api/commerce";

const button =
  "inline-block rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900";
const input =
  "mt-2 w-full rounded-lg border border-neutral-300 bg-transparent px-3 py-2.5 dark:border-neutral-700";
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Please try again.";

function Frame({ title, children }: { title: string; children: ReactNode }) {
  const { user, loading } = useAuth();
  const path = usePathname();
  return (
    <>
      <StoreHeader />
      <main className="mx-auto max-w-5xl px-6 py-12">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        {loading ? (
          <p className="mt-8" role="status">
            Loading your account…
          </p>
        ) : !user ? (
          <div className="mt-8 space-y-5">
            <p>Sign in to view your cart and orders.</p>
            <Link
              className={button}
              href={`/login?next=${encodeURIComponent(path)}`}
            >
              Sign in
            </Link>
          </div>
        ) : (
          children
        )}
      </main>
    </>
  );
}

function useData<T>(path: string) {
  const { user, loading: authLoading } = useAuth();
  const [result, setResult] = useState<{ owner: string; value: T } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setError("");
    setLoading(true);
    setResult(null);
    if (!user || authLoading) return;
    let alive = true;
    authenticatedRequest<T>(path)
      .then((value) => {
        if (alive) setResult({ owner: user.id, value });
      })
      .catch((error) => {
        if (alive) setError(message(error));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [user?.id, authLoading, path, revision]);
  return {
    data: result?.owner === user?.id ? result?.value : undefined,
    error,
    loading,
    reload: () => setRevision((value) => value + 1),
  };
}
function LoadState({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error: string;
  retry: () => void;
}) {
  return (
    <>
      {loading && (
        <p className="mt-8" role="status">
          Loading…
        </p>
      )}
      {error && (
        <div className="mt-6">
          <p role="alert" className="text-red-600">
            {error}
          </p>
          <button className="mt-3 underline" onClick={retry}>
            Try again
          </button>
        </div>
      )}
    </>
  );
}
function Totals({
  value,
}: {
  value: {
    subtotal_cents: number;
    shipping_cents: number;
    total_cents: number;
    currency: string;
  };
}) {
  return (
    <dl className="space-y-3 border-t border-neutral-200 pt-5 text-sm dark:border-neutral-800">
      <div className="flex justify-between gap-8">
        <dt>Subtotal</dt>
        <dd>{money(value.subtotal_cents, value.currency)}</dd>
      </div>
      <div className="flex justify-between gap-8">
        <dt>Shipping</dt>
        <dd>{money(value.shipping_cents, value.currency)}</dd>
      </div>
      <div className="flex justify-between gap-8 text-lg font-semibold">
        <dt>Total</dt>
        <dd>{money(value.total_cents, value.currency)}</dd>
      </div>
    </dl>
  );
}

export function CartPage() {
  const state = useData<{ data: Cart }>("/cart");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cart = state.data?.data;
  async function change(variant: string, quantity?: number) {
    setBusy(true);
    setError("");
    try {
      if (quantity === undefined) await removeCartItem(variant);
      else await setCartItem(variant, quantity);
      state.reload();
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Frame title="Your cart">
      <LoadState {...state} retry={state.reload} />
      {error && (
        <p role="alert" className="mt-5 text-red-600">
          {error}
        </p>
      )}
      {cart && (
        <>
          {cart.items.length === 0 ? (
            <div className="mt-10 space-y-5">
              <p>Your cart is empty.</p>
              <Link href="/search" className={button}>
                Explore products
              </Link>
            </div>
          ) : (
            <div className="mt-10 grid gap-10 md:grid-cols-[1fr_280px]">
              <div className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {cart.items.map((item) => (
                  <article
                    key={item.variant_id}
                    className="flex gap-5 py-6 first:pt-0"
                  >
                    {item.image_url && (
                      <img
                        src={item.image_url}
                        alt={item.name}
                        className="h-28 w-20 rounded-lg bg-white object-contain"
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <Link
                        className="font-medium"
                        href={`/product/${item.handle}`}
                      >
                        {item.name}
                      </Link>
                      <p className="mt-1 text-sm text-neutral-500">
                        {[item.size, item.color].filter(Boolean).join(" / ") ||
                          "Default"}
                      </p>
                      <p className="mt-2 text-sm">
                        {money(item.price_cents, item.currency)} each
                      </p>
                      {(!item.is_available || item.stock < item.quantity) && (
                        <p className="mt-2 text-sm text-red-600">
                          {item.is_available
                            ? `Only ${item.stock} left. Update quantity.`
                            : "Currently unavailable. Remove this item to continue."}
                        </p>
                      )}
                      <form
                        className="mt-3 flex flex-wrap items-center gap-3"
                        onSubmit={(event: FormEvent<HTMLFormElement>) => {
                          event.preventDefault();
                          const quantity = Number(
                            new FormData(event.currentTarget).get("quantity"),
                          );
                          void change(item.variant_id, quantity);
                        }}
                      >
                        <label className="text-sm">
                          Quantity{" "}
                          <input
                            key={item.quantity}
                            name="quantity"
                            type="number"
                            min={1}
                            max={99}
                            required
                            defaultValue={item.quantity}
                            className="ml-2 w-16 rounded border bg-transparent p-1.5"
                          />
                        </label>
                        <button
                          disabled={busy || state.loading}
                          className="text-sm underline"
                        >
                          Update
                        </button>
                        <button
                          type="button"
                          disabled={busy || state.loading}
                          className="text-sm underline"
                          onClick={() => void change(item.variant_id)}
                        >
                          Remove
                        </button>
                      </form>
                    </div>
                    <p className="text-sm font-medium">
                      {money(item.price_cents * item.quantity, item.currency)}
                    </p>
                  </article>
                ))}
              </div>
              <aside className="space-y-6">
                <Totals value={cart} />
                <p className="text-sm text-neutral-500">
                  Stock is confirmed at checkout. This demo uses simulated
                  payment.
                </p>
                {cart.can_checkout ? (
                  <Link href="/checkout" className={button}>
                    Continue to checkout
                  </Link>
                ) : (
                  <p role="status" className="text-sm">
                    {cart.limit_exceeded
                      ? "Cart exceeds the supported order total. Remove items to continue."
                      : "Review unavailable items before checkout."}
                  </p>
                )}
              </aside>
            </div>
          )}
        </>
      )}
    </Frame>
  );
}

interface PendingCheckout {
  key: string;
  input: CheckoutInput;
}
export function CheckoutPage() {
  const { user } = useAuth();
  const router = useRouter();
  const state = useData<{ data: Cart }>("/cart");
  const [pending, setPending] = useState<{
    owner: string;
    value: PendingCheckout;
  } | null>(null);
  const [restored, setRestored] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const storageKey = user ? `aurafind-checkout:${user.id}` : "";
  useEffect(() => {
    setPending(null);
    setError("");
    setRestored(null);
    if (!user) return;
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        const value = JSON.parse(saved) as PendingCheckout;
        if (!value.key || !value.input?.items || !value.input.shipping_address)
          throw new Error("Invalid saved checkout");
        setPending({ owner: user.id, value });
      }
    } catch {
      sessionStorage.removeItem(storageKey);
    }
    setRestored(user.id);
  }, [user?.id, storageKey]);
  const attempt = pending && pending.owner === user?.id ? pending.value : null;
  const cart = state.data?.data;
  async function place(value: PendingCheckout) {
    if (!user || busy) return;
    setBusy(true);
    setError("");
    try {
      // Persist the exact key and payload before sending. A lost response can be retried safely.
      sessionStorage.setItem(storageKey, JSON.stringify(value));
      setPending({ owner: user.id, value });
      const result = await checkout(value.key, value.input);
      sessionStorage.removeItem(storageKey);
      setPending(null);
      router.replace(`/account/orders/${result.data.id}?placed=1`);
    } catch (error) {
      if (error instanceof APIError && [400, 404, 409].includes(error.status)) {
        sessionStorage.removeItem(storageKey);
        setPending(null);
        state.reload();
      }
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cart || !cart.can_checkout || !user) return;
    const address = Object.fromEntries(
      new FormData(event.currentTarget),
    ) as unknown as Address;
    void place({
      key: crypto.randomUUID(),
      input: {
        shipping_address: address,
        currency: cart.currency,
        items: cart.items.map(({ variant_id, quantity, price_cents }) => ({
          variant_id,
          quantity,
          price_cents,
        })),
      },
    });
  }
  const fields: {
    key: keyof Address;
    label: string;
    complete: string;
    required?: boolean;
    max?: number;
  }[] = [
    { key: "name", label: "Full name", complete: "name", required: true },
    {
      key: "line1",
      label: "Street address",
      complete: "address-line1",
      required: true,
    },
    {
      key: "line2",
      label: "Apartment, suite (optional)",
      complete: "address-line2",
    },
    { key: "city", label: "City", complete: "address-level2", required: true },
    {
      key: "region",
      label: "State / province (optional)",
      complete: "address-level1",
    },
    {
      key: "postal_code",
      label: "Postal code",
      complete: "postal-code",
      required: true,
    },
    {
      key: "country",
      label: "Country code (e.g. US or VN)",
      complete: "country",
      required: true,
      max: 2,
    },
  ];
  return (
    <Frame title="Checkout">
      <p className="mt-4 text-sm text-neutral-500">
        Demo checkout · Payment is simulated. No money is charged.
      </p>
      {error && (
        <p role="alert" className="mt-6 text-red-600">
          {error}
        </p>
      )}
      {restored === user?.id && attempt ? (
        <div className="mt-10 max-w-xl space-y-5">
          <h2 className="text-xl font-medium">Resume your checkout</h2>
          <p>
            A previous attempt may have completed. Retry it to retrieve the same
            order safely.
          </p>
          <p>
            Ship to {attempt.input.shipping_address.name},{" "}
            {attempt.input.shipping_address.line1},{" "}
            {attempt.input.shipping_address.city}.
          </p>
          <p className="font-semibold">
            {money(
              attempt.input.items.reduce(
                (sum, item) => sum + item.price_cents * item.quantity,
                0,
              ),
              attempt.input.currency,
            )}
          </p>
          <button
            className={button}
            disabled={busy}
            onClick={() => void place(attempt)}
          >
            {busy ? "Confirming…" : "Retry checkout"}
          </button>
          <p className="text-sm text-neutral-500">
            Keep this attempt until its result is confirmed.
          </p>
        </div>
      ) : (
        <>
          <LoadState {...state} retry={state.reload} />
          {cart &&
            restored === user?.id &&
            (cart.can_checkout ? (
              <div className="mt-10 grid gap-12 md:grid-cols-[1fr_280px]">
                <form onSubmit={submit} className="space-y-5">
                  <h2 className="text-xl font-medium">Shipping address</h2>
                  {fields.map((field) => (
                    <label
                      className="block text-sm font-medium"
                      key={field.key}
                    >
                      {field.label}
                      <input
                        name={field.key}
                        required={field.required}
                        maxLength={field.max ?? 200}
                        pattern={
                          field.key === "country" ? "[A-Za-z]{2}" : undefined
                        }
                        autoComplete={field.complete}
                        defaultValue={field.key === "name" ? user?.name : ""}
                        className={input}
                      />
                    </label>
                  ))}
                  <button className={button} disabled={busy}>
                    {busy ? "Placing order…" : "Place demo order"}
                  </button>
                </form>
                <aside className="space-y-6">
                  <h2 className="text-xl font-medium">Your order</h2>
                  {cart.items.map((item) => (
                    <div
                      key={item.variant_id}
                      className="flex justify-between gap-4 text-sm"
                    >
                      <span>
                        {item.name} × {item.quantity}
                      </span>
                      <span>{money(item.price_cents * item.quantity)}</span>
                    </div>
                  ))}
                  <Totals value={cart} />
                  <Link className="inline-block text-sm underline" href="/cart">
                    Edit cart
                  </Link>
                </aside>
              </div>
            ) : (
              <div className="mt-8 space-y-5">
                <p>
                  {cart.items.length
                    ? "Review your cart before checkout."
                    : "Your cart is empty."}
                </p>
                <Link className={button} href="/cart">
                  Back to cart
                </Link>
              </div>
            ))}
        </>
      )}
    </Frame>
  );
}

export function OrdersPage() {
  const [page, setPage] = useState(1);
  const state = useData<{
    data: Order[];
    pagination: { pages: number; total: number };
  }>(`/orders?page=${page}&limit=12`);
  return (
    <Frame title="Your orders">
      <LoadState {...state} retry={state.reload} />
      {state.data && (
        <>
          {state.data.data.length === 0 ? (
            <p className="mt-8">
              No orders yet.{" "}
              <Link href="/search" className="underline">
                Explore products
              </Link>
            </p>
          ) : (
            <div className="mt-8 divide-y divide-neutral-200 dark:divide-neutral-800">
              {state.data.data.map((order) => (
                <Link
                  href={`/account/orders/${order.id}`}
                  key={order.id}
                  className="flex flex-wrap items-center justify-between gap-4 py-6"
                >
                  <div>
                    <p className="font-medium">Order {order.id.slice(0, 8)}</p>
                    <p className="mt-1 text-sm text-neutral-500">
                      {new Date(order.created_at).toLocaleDateString()} ·{" "}
                      {order.order_status} · Simulated payment
                    </p>
                  </div>
                  <span className="font-medium">
                    {money(order.total_cents, order.currency)}
                  </span>
                </Link>
              ))}
            </div>
          )}
          <nav
            aria-label="Order pages"
            className="mt-8 flex items-center gap-5"
          >
            <button
              className="underline disabled:opacity-40"
              disabled={page === 1 || state.loading}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </button>
            <span className="text-sm">
              Page {page} of {Math.max(1, state.data.pagination.pages)}
            </span>
            <button
              className="underline disabled:opacity-40"
              disabled={page >= state.data.pagination.pages || state.loading}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </Frame>
  );
}

export function OrderPage({ id }: { id: string }) {
  const state = useData<{ data: Order }>(`/orders/${encodeURIComponent(id)}`);
  const order = state.data?.data;
  return (
    <Frame title="Order details">
      <Link
        className="mt-5 inline-block text-sm underline"
        href="/account/orders"
      >
        Back to orders
      </Link>
      <LoadState {...state} retry={state.reload} />
      {order && (
        <div className="mt-8 grid gap-10 md:grid-cols-[1fr_280px]">
          <div>
            <p className="break-all text-sm text-neutral-500">
              Order {order.id}
            </p>
            <h2 className="mt-4 text-xl font-medium">Order confirmed</h2>
            <p className="mt-2 text-sm">
              {new Date(order.created_at).toLocaleString()} ·{" "}
              {order.order_status} · {order.fulfillment_status}
            </p>
            <p className="mt-3 text-sm text-neutral-500">
              Payment is simulated. No money was charged.
            </p>
            <div className="mt-8 divide-y divide-neutral-200 dark:divide-neutral-800">
              {order.items?.map((item, index) => (
                <div key={index} className="flex gap-4 py-5">
                  {item.image_url && (
                    <img
                      src={item.image_url}
                      alt={item.name}
                      className="h-24 w-16 rounded bg-white object-contain"
                    />
                  )}
                  <div className="flex-1">
                    <p className="font-medium">{item.name}</p>
                    <p className="mt-1 text-sm text-neutral-500">
                      {[item.size, item.color].filter(Boolean).join(" / ")}
                    </p>
                    <p className="mt-2 text-sm">
                      {item.quantity} ×{" "}
                      {money(item.price_cents, order.currency)}
                    </p>
                  </div>
                  <p className="text-sm">
                    {money(item.quantity * item.price_cents, order.currency)}
                  </p>
                </div>
              ))}
            </div>
          </div>
          <aside className="space-y-7">
            <Totals value={order} />
            <section>
              <h2 className="font-medium">Shipping address</h2>
              <address className="mt-3 whitespace-pre-line text-sm not-italic leading-6 text-neutral-500">
                {[
                  order.shipping_address.name,
                  order.shipping_address.line1,
                  order.shipping_address.line2,
                  [
                    order.shipping_address.city,
                    order.shipping_address.region,
                    order.shipping_address.postal_code,
                  ]
                    .filter(Boolean)
                    .join(", "),
                  order.shipping_address.country,
                ]
                  .filter(Boolean)
                  .join("\n")}
              </address>
            </section>
          </aside>
        </div>
      )}
    </Frame>
  );
}
