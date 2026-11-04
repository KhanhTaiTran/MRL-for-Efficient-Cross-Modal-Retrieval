"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "components/auth/auth-provider";
import { StoreHeader } from "components/layout/store-header";
import {
  adminRequest,
  servingIndex,
  type AdminProduct,
  type AdminVariant,
  type IndexJob,
  type IndexVersion,
} from "lib/api/admin";
import { money } from "lib/api/commerce";

const input =
  "mt-1 w-full rounded-lg border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700";
const button =
  "rounded-lg bg-neutral-900 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-40 dark:bg-white dark:text-neutral-900";
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Please try again.";
const empty: AdminProduct = {
  id: "",
  handle: "",
  name: "",
  description: "",
  brand: "",
  category: "",
  price_cents: 0,
  currency: "USD",
  is_active: true,
  is_featured: false,
  revision: 0,
  default_variant_id: "",
  search_status: "pending",
};

export function AdminPanel() {
  const { user, loading } = useAuth();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [catalog, setCatalog] = useState<{
    owner: string;
    data: AdminProduct[];
    pages: number;
  } | null>(null);
  const [selected, setSelected] = useState<{
    owner: string;
    value: AdminProduct;
  } | null>(null);
  const [jobs, setJobs] = useState<IndexJob[]>([]);
  const [versions, setVersions] = useState<IndexVersion[]>([]);
  const [serving, setServing] = useState("");
  const [indexError, setIndexError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const allowed = user?.role === "admin";
  useEffect(() => {
    setCatalog(null);
    setError("");
    if (!allowed || !user) return;
    let alive = true;
    adminRequest<{ data: AdminProduct[]; pagination: { pages: number } }>(
      `/products?page=${page}&q=${encodeURIComponent(query)}`,
    )
      .then((value) => {
        if (alive)
          setCatalog({
            owner: user.id,
            data: value.data,
            pages: value.pagination.pages,
          });
      })
      .catch((error) => {
        if (alive) setError(message(error));
      });
    return () => {
      alive = false;
    };
  }, [allowed, user?.id, page, query, revision]);
  useEffect(() => {
    setJobs([]);
    setVersions([]);
    setServing("");
    setIndexError("");
    if (!allowed) return;
    let alive = true;
    const update = () => {
      Promise.all([
        adminRequest<{ data: IndexJob[] }>("/index/jobs"),
        adminRequest<{ data: IndexVersion[] }>("/index/versions"),
        servingIndex().catch(() => null),
      ])
        .then(([j, v, s]) => {
          if (alive) {
            setJobs(j.data);
            setVersions(v.data);
            if (s) {
              setServing(s.active_index_version);
              setIndexError("");
            } else {
              setIndexError(
                "Search is starting or temporarily unavailable. Catalog administration is still available.",
              );
            }
          }
        })
        .catch((error) => {
          if (alive) setIndexError(message(error));
        });
    };
    update();
    const timer = setInterval(update, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [allowed, user?.id, revision]);
  async function open(id: string) {
    setBusy(true);
    setError("");
    try {
      const result = await adminRequest<{ data: AdminProduct }>(
        `/products/${id}`,
      );
      if (user) setSelected({ owner: user.id, value: result.data });
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  const product = selected?.owner === user?.id ? selected?.value : null;
  const records = catalog?.owner === user?.id ? catalog : null;
  function saved(value: AdminProduct) {
    if (user) setSelected({ owner: user.id, value });
    setRevision((value) => value + 1);
  }
  return (
    <>
      <StoreHeader />
      <main className="mx-auto max-w-7xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">
          Catalog administration
        </h1>
        <Link
          href="/admin/reviews"
          className="mt-4 inline-block text-sm underline"
        >
          Moderate customer reviews
        </Link>
        {loading ? (
          <p className="mt-8">Loading account…</p>
        ) : !user ? (
          <p className="mt-8">
            <Link className="underline" href="/login?next=/admin">
              Sign in
            </Link>{" "}
            with an administrator account.
          </p>
        ) : !allowed ? (
          <p role="alert" className="mt-8">
            Administrator access is required.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-6 text-sm text-red-600">
                {error}
              </p>
            )}
            <section className="mt-10 border-y border-neutral-200 py-6 dark:border-neutral-800">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div>
                  <h2 className="text-xl font-medium">Search index</h2>
                  <p className="mt-2 max-w-2xl text-sm text-neutral-500">
                    Catalog edits become searchable after a rebuild. Existing
                    search stays available while the new version is prepared.
                  </p>
                  <p className="mt-3 break-all text-xs text-neutral-500">
                    Search serving: {serving || "Loading…"}
                  </p>
                </div>
                <button
                  className={button}
                  disabled={
                    busy ||
                    jobs.some((job) =>
                      ["pending", "running"].includes(job.status),
                    )
                  }
                  onClick={async () => {
                    setBusy(true);
                    setError("");
                    try {
                      await adminRequest("/index/jobs", { method: "POST" });
                      setRevision((value) => value + 1);
                    } catch (error) {
                      setError(message(error));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Rebuild search index
                </button>
              </div>
              {indexError && (
                <p role="status" className="mt-4 text-sm text-neutral-500">
                  {indexError}
                </p>
              )}
              {jobs.length > 0 && (
                <div className="mt-5 space-y-2">
                  {jobs.slice(0, 5).map((job) => (
                    <div key={job.id} className="text-sm">
                      <span className="font-medium">{job.status}</span> ·{" "}
                      {new Date(job.created_at).toLocaleString()}{" "}
                      <span className="text-xs text-neutral-500">
                        {job.id.slice(0, 8)}
                      </span>
                      {job.error && (
                        <details className="mt-1 text-red-600">
                          <summary className="cursor-pointer">
                            View failure details
                          </summary>
                          <p className="mt-2 break-all text-xs">{job.error}</p>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {versions.length > 0 && (
                <details className="mt-5">
                  <summary className="cursor-pointer text-sm underline">
                    Retained index versions ({versions.length})
                  </summary>
                  <ul className="mt-3 space-y-2 text-xs text-neutral-500">
                    {versions.map((version) => (
                      <li key={version.id} className="break-all">
                        {version.is_active ? "Published · " : "Retained · "}
                        {version.id} · {version.num_vectors} vectors ·{" "}
                        {new Date(version.built_at).toLocaleString()}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>
            <div className="mt-10 grid items-start gap-10 lg:grid-cols-[340px_1fr]">
              <section>
                <div className="flex items-center justify-between gap-4">
                  <h2 className="text-xl font-medium">Products</h2>
                  <button
                    className="text-sm underline"
                    disabled={busy}
                    onClick={() => {
                      if (user)
                        setSelected({ owner: user.id, value: { ...empty } });
                    }}
                  >
                    New product
                  </button>
                </div>
                <form
                  className="mt-4 flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setQuery(search);
                    setPage(1);
                  }}
                >
                  <label className="flex-1 text-sm">
                    Find products
                    <input
                      className={input}
                      value={search}
                      maxLength={200}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </label>
                  <button className="self-end rounded-lg border px-3 py-2 text-sm">
                    Find
                  </button>
                </form>
                {!records ? (
                  <p className="mt-6 text-sm">Loading catalog…</p>
                ) : (
                  <>
                    <ul className="mt-5 divide-y divide-neutral-200 dark:divide-neutral-800">
                      {records.data.map((item) => (
                        <li key={item.id}>
                          <button
                            disabled={busy}
                            onClick={() => void open(item.id)}
                            className="w-full py-4 text-left"
                          >
                            <span className="block font-medium">
                              {item.name}
                            </span>
                            <span className="mt-1 block text-xs text-neutral-500">
                              {item.is_active ? "Active" : "Archived"} ·{" "}
                              {item.search_status} ·{" "}
                              {money(item.price_cents, item.currency)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    {!records.data.length && (
                      <p className="mt-5 text-sm">No matching products.</p>
                    )}
                    <nav
                      className="mt-5 flex justify-between text-sm"
                      aria-label="Admin product pages"
                    >
                      <button
                        disabled={page === 1 || busy}
                        className="underline disabled:opacity-40"
                        onClick={() => setPage((value) => value - 1)}
                      >
                        Previous
                      </button>
                      <span>
                        {page} / {Math.max(1, records.pages)}
                      </span>
                      <button
                        disabled={page >= records.pages || busy}
                        className="underline disabled:opacity-40"
                        onClick={() => setPage((value) => value + 1)}
                      >
                        Next
                      </button>
                    </nav>
                  </>
                )}
              </section>
              <section>
                {product ? (
                  <ProductEditor
                    key={`${product.id}:${product.revision}`}
                    product={product}
                    saved={saved}
                    reload={() => void open(product.id)}
                  />
                ) : (
                  <p className="pt-2 text-sm text-neutral-500">
                    Select a product or create a new one.
                  </p>
                )}
              </section>
            </div>
          </>
        )}
      </main>
    </>
  );
}

function ProductEditor({
  product,
  saved,
  reload,
}: {
  product: AdminProduct;
  saved: (value: AdminProduct) => void;
  reload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function mutate(path: string, method: string, body?: BodyInit) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await adminRequest<{ data: AdminProduct }>(path, {
        method,
        body,
      });
      saved(result.data);
      setNotice("Saved. Rebuild the search index to include catalog changes.");
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (key: string) => String(form.get(key) || "");
    void mutate(
      product.id ? `/products/${product.id}` : "/products",
      product.id ? "PUT" : "POST",
      JSON.stringify({
        handle: text("handle"),
        name: text("name"),
        description: text("description"),
        brand: text("brand"),
        category: text("category"),
        price_cents: Number(text("price_cents")),
        is_active: form.has("is_active"),
        is_featured: form.has("is_featured"),
        revision: product.revision,
        default_variant_id: text("default_variant_id"),
      }),
    );
  }
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h2 className="text-xl font-medium">
          {product.id ? "Edit product" : "New product"}
        </h2>
        {product.id && (
          <button
            className="text-sm underline"
            disabled={busy}
            onClick={reload}
          >
            Reload product
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-5 text-sm text-red-600">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-5 text-sm">
          {notice}
        </p>
      )}
      <form onSubmit={save} className="mt-6 grid gap-4 sm:grid-cols-2">
        <label className="text-sm sm:col-span-2">
          Product name
          <input
            name="name"
            defaultValue={product.name}
            required
            maxLength={200}
            className={input}
          />
        </label>
        <label className="text-sm">
          Handle
          <input
            name="handle"
            defaultValue={product.handle}
            required
            maxLength={120}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            className={input}
          />
        </label>
        <label className="text-sm">
          Base price (USD cents)
          <input
            name="price_cents"
            type="number"
            min={0}
            max={999999999999}
            step={1}
            required
            defaultValue={product.price_cents}
            className={input}
          />
        </label>
        <label className="text-sm">
          Brand
          <input
            name="brand"
            defaultValue={product.brand}
            maxLength={120}
            className={input}
          />
        </label>
        <label className="text-sm">
          Category
          <input
            name="category"
            defaultValue={product.category}
            maxLength={100}
            className={input}
          />
        </label>
        <label className="text-sm sm:col-span-2">
          Description
          <textarea
            name="description"
            defaultValue={product.description}
            maxLength={5000}
            rows={4}
            className={input}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="is_active"
            defaultChecked={product.is_active}
          />
          Active in storefront
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="is_featured"
            defaultChecked={product.is_featured}
          />
          Featured
        </label>
        {product.id && (
          <label className="text-sm sm:col-span-2">
            Default variant
            <select
              name="default_variant_id"
              defaultValue={product.default_variant_id}
              className={input}
            >
              <option value="">No default</option>
              {product.variants?.map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {[variant.size, variant.color].filter(Boolean).join(" / ") ||
                    "Default"}
                  {!variant.is_available ? " (unavailable)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex flex-wrap gap-5 sm:col-span-2">
          <button className={button} disabled={busy}>
            {busy ? "Saving…" : "Save product"}
          </button>
          {product.id && product.is_active && (
            <button
              type="button"
              className="text-sm underline"
              disabled={busy}
              onClick={() => void mutate(`/products/${product.id}`, "DELETE")}
            >
              Archive product
            </button>
          )}
          {product.id && (
            <Link
              className="self-center text-sm underline"
              href={`/product/${product.handle}`}
            >
              View storefront
            </Link>
          )}
        </div>
      </form>
      {product.id && (
        <>
          <section className="mt-10 border-t border-neutral-200 pt-7 dark:border-neutral-800">
            <h3 className="text-lg font-medium">Variants and inventory</h3>
            <p className="mt-2 text-sm text-neutral-500">
              Prices use USD cents. Stock updates are checked against the last
              loaded stock to protect concurrent purchases.
            </p>
            <div className="mt-4 space-y-4">
              {product.variants?.map((variant) => (
                <details key={variant.id}>
                  <summary className="cursor-pointer text-sm">
                    {[variant.size, variant.color]
                      .filter(Boolean)
                      .join(" / ") || "Default"}{" "}
                    · {money(variant.price_cents)} · {variant.stock} in stock ·{" "}
                    {variant.is_available ? "Available" : "Disabled"}
                  </summary>
                  <VariantForm
                    variant={variant}
                    busy={busy}
                    submit={(body) =>
                      mutate(
                        `/products/${product.id}/variants/${variant.id}`,
                        "PUT",
                        JSON.stringify(body),
                      )
                    }
                  />
                  <button
                    className="mt-3 text-sm underline"
                    disabled={busy || !variant.is_available}
                    onClick={() =>
                      void mutate(
                        `/products/${product.id}/variants/${variant.id}`,
                        "DELETE",
                      )
                    }
                  >
                    Disable variant
                  </button>
                </details>
              ))}
              <details>
                <summary className="cursor-pointer text-sm font-medium">
                  Add variant
                </summary>
                <VariantForm
                  busy={busy}
                  submit={(body) =>
                    mutate(
                      `/products/${product.id}/variants`,
                      "POST",
                      JSON.stringify(body),
                    )
                  }
                />
              </details>
            </div>
          </section>
          <section className="mt-10 border-t border-neutral-200 pt-7 dark:border-neutral-800">
            <h3 className="text-lg font-medium">Product images</h3>
            <p className="mt-2 text-sm text-neutral-500">
              PNG or JPEG, up to 10 MB and 20 million pixels. Removed images
              remain stored for historical indexes and orders.
            </p>
            <div className="mt-5 space-y-5">
              {product.images?.map((image) => (
                <form
                  key={image.id}
                  className="flex flex-wrap items-start gap-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = new FormData(event.currentTarget);
                    void mutate(
                      `/products/${product.id}/images/${image.id}`,
                      "PUT",
                      JSON.stringify({
                        alt: String(form.get("alt") || ""),
                        position: Number(form.get("position")),
                        is_primary: form.has("is_primary"),
                      }),
                    );
                  }}
                >
                  <img
                    src={image.url}
                    alt={image.alt}
                    className="h-28 w-20 rounded bg-white object-contain"
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <label className="block text-sm">
                      Image description
                      <input
                        name="alt"
                        defaultValue={image.alt}
                        maxLength={200}
                        className={input}
                      />
                    </label>
                    <label className="block text-sm">
                      Position
                      <input
                        name="position"
                        type="number"
                        min={0}
                        max={32767}
                        defaultValue={image.position}
                        required
                        className={input}
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        name="is_primary"
                        defaultChecked={image.is_primary}
                      />
                      Primary image
                    </label>
                    <div className="flex gap-4">
                      <button className="text-sm underline" disabled={busy}>
                        Save image
                      </button>
                      <button
                        type="button"
                        className="text-sm underline"
                        disabled={busy}
                        onClick={() =>
                          void mutate(
                            `/products/${product.id}/images/${image.id}`,
                            "DELETE",
                          )
                        }
                      >
                        Remove image
                      </button>
                    </div>
                  </div>
                </form>
              ))}
            </div>
            <form
              className="mt-6 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void mutate(
                  `/products/${product.id}/images`,
                  "POST",
                  new FormData(event.currentTarget),
                );
              }}
            >
              <label className="block text-sm">
                Upload image
                <input
                  className={input}
                  name="image"
                  type="file"
                  accept="image/png,image/jpeg"
                  required
                />
              </label>
              <label className="block text-sm">
                New image description
                <input name="alt" maxLength={200} className={input} />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input name="primary" type="checkbox" value="true" />
                Use as primary image
              </label>
              <button className={button} disabled={busy}>
                Upload image
              </button>
            </form>
          </section>
        </>
      )}
    </div>
  );
}

function VariantForm({
  variant,
  busy,
  submit,
}: {
  variant?: AdminVariant;
  busy: boolean;
  submit: (body: unknown) => Promise<void>;
}) {
  return (
    <form
      className="mt-4 grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void submit({
          sku: String(form.get("sku") || ""),
          size: String(form.get("size") || ""),
          color: String(form.get("color") || ""),
          price_cents: Number(form.get("price_cents")),
          stock: Number(form.get("stock")),
          is_available: form.has("is_available"),
          ...(variant ? { expected_stock: variant.stock } : {}),
        });
      }}
    >
      {(
        [
          { key: "sku", label: "SKU", max: 120 },
          { key: "size", label: "Size", max: 100 },
          { key: "color", label: "Color", max: 100 },
        ] as const
      ).map((field) => (
        <label className="text-sm" key={field.key}>
          {field.label}
          <input
            name={field.key}
            maxLength={field.max}
            defaultValue={variant?.[field.key] || ""}
            className={input}
          />
        </label>
      ))}
      <label className="text-sm">
        Variant price (USD cents)
        <input
          name="price_cents"
          type="number"
          min={0}
          max={999999999999}
          step={1}
          required
          defaultValue={variant?.price_cents ?? 0}
          className={input}
        />
      </label>
      <label className="text-sm">
        Stock
        <input
          name="stock"
          type="number"
          min={0}
          max={2147483647}
          step={1}
          required
          defaultValue={variant?.stock ?? 0}
          className={input}
        />
      </label>
      <label className="flex items-center gap-2 self-end py-3 text-sm">
        <input
          name="is_available"
          type="checkbox"
          defaultChecked={variant?.is_available ?? true}
        />
        Available
      </label>
      <div className="sm:col-span-2">
        <button className={button} disabled={busy}>
          {variant ? "Save variant" : "Create variant"}
        </button>
      </div>
    </form>
  );
}
