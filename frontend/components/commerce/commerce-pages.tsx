"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "components/auth/auth-provider";
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
  "inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-neutral-900 px-5 py-3 text-center text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200";
const input =
  "mt-2 min-h-11 w-full rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-base text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100";
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Please try again.";

function Frame({ title, children }: { title: string; children: ReactNode }) {
  const { user, loading } = useAuth();
  const path = usePathname();
  return (
    <>
      <section className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
        <Link
          href="/search"
          className="mb-5 inline-flex min-h-8 items-center text-sm text-neutral-600 underline underline-offset-4 dark:text-neutral-400"
        >
          Continue shopping
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {title}
        </h1>
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
      </section>
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
          <p role="alert" className="text-red-700 dark:text-red-400">
            {error}
          </p>
          <button
            className="mt-3 min-h-11 underline underline-offset-4"
            onClick={retry}
          >
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
        <p role="alert" className="mt-5 text-red-700 dark:text-red-400">
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
            <div className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
              <div className="min-w-0 divide-y divide-neutral-200 dark:divide-neutral-800">
                {cart.items.map((item) => (
                  <article
                    key={item.variant_id}
                    className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 py-6 first:pt-0 sm:grid-cols-[80px_minmax(0,1fr)_auto] sm:gap-5"
                  >
                    {item.image_url && (
                      <img
                        src={item.image_url}
                        alt={item.name}
                        className="h-24 w-16 shrink-0 rounded-xl bg-white object-contain sm:h-28 sm:w-20"
                      />
                    )}
                    <div className="col-start-2 min-w-0">
                      <Link
                        className="break-words font-medium leading-6 hover:underline"
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
                        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
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
                            className="ml-2 min-h-11 w-16 rounded-lg border border-neutral-300 bg-white px-2 text-base dark:border-neutral-700 dark:bg-neutral-900"
                          />
                        </label>
                        <button
                          disabled={busy || state.loading}
                          className="min-h-11 text-sm underline underline-offset-4 disabled:opacity-50"
                        >
                          Update
                        </button>
                        <button
                          type="button"
                          disabled={busy || state.loading}
                          className="min-h-11 text-sm text-neutral-600 underline underline-offset-4 disabled:opacity-50 dark:text-neutral-400"
                          onClick={() => void change(item.variant_id)}
                        >
                          Remove
                        </button>
                      </form>
                    </div>
                    <p className="col-start-2 text-sm font-semibold tabular-nums sm:col-start-3">
                      {money(item.price_cents * item.quantity, item.currency)}
                    </p>
                  </article>
                ))}
              </div>
              <aside className="space-y-6 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6 dark:border-neutral-800 dark:bg-neutral-900/50">
                <h2 className="text-lg font-semibold">Order summary</h2>
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
        <p role="alert" className="mt-6 text-red-700 dark:text-red-400">
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
              <div className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
                <form
                  onSubmit={submit}
                  className="min-w-0 space-y-5 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-7 dark:border-neutral-800 dark:bg-neutral-900/50"
                >
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
                <aside className="min-w-0 space-y-6 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6 dark:border-neutral-800 dark:bg-neutral-900/50">
                  <h2 className="text-xl font-medium">Your order</h2>
                  {cart.items.map((item) => (
                    <div
                      key={item.variant_id}
                      className="flex justify-between gap-4 text-sm"
                    >
                      <span className="min-w-0 break-words">
                        {item.name} × {item.quantity}
                      </span>
                      <span className="shrink-0 tabular-nums">
                        {money(item.price_cents * item.quantity)}
                      </span>
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
                  className="flex flex-wrap items-center justify-between gap-4 rounded-xl px-3 py-6 transition hover:bg-neutral-100 dark:hover:bg-neutral-900"
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
            className="mt-8 flex flex-wrap items-center justify-between gap-4 sm:justify-start sm:gap-5"
          >
            <button
              className="min-h-11 rounded-lg border border-neutral-300 px-4 text-sm disabled:opacity-40 dark:border-neutral-700"
              disabled={page === 1 || state.loading}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </button>
            <span className="text-sm">
              Page {page} of {Math.max(1, state.data.pagination.pages)}
            </span>
            <button
              className="min-h-11 rounded-lg border border-neutral-300 px-4 text-sm disabled:opacity-40 dark:border-neutral-700"
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
        <div className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
          <div className="min-w-0">
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
                <div
                  key={index}
                  className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 py-5 sm:grid-cols-[64px_minmax(0,1fr)_auto]"
                >
                  {item.image_url && (
                    <img
                      src={item.image_url}
                      alt={item.name}
                      className="h-24 w-16 rounded bg-white object-contain"
                    />
                  )}
                  <div className="col-start-2 min-w-0">
                    <p className="break-words font-medium leading-6">
                      {item.name}
                    </p>
                    <p className="mt-1 text-sm text-neutral-500">
                      {[item.size, item.color].filter(Boolean).join(" / ")}
                    </p>
                    <p className="mt-2 text-sm">
                      {item.quantity} ×{" "}
                      {money(item.price_cents, order.currency)}
                    </p>
                  </div>
                  <p className="col-start-2 text-sm font-semibold tabular-nums sm:col-start-3">
                    {money(item.quantity * item.price_cents, order.currency)}
                  </p>
                </div>
              ))}
            </div>
          </div>
          <aside className="min-w-0 space-y-7 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6 dark:border-neutral-800 dark:bg-neutral-900/50">
            <Totals value={order} />
            <section>
              <h2 className="font-medium">Shipping address</h2>
              <address className="mt-3 break-words whitespace-pre-line text-sm not-italic leading-6 text-neutral-600 dark:text-neutral-400">
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
