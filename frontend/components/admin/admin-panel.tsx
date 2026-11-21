"use client";

import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  ImageIcon,
  Plus,
  Search,
} from "lucide-react";
import { useAuth } from "components/auth/auth-provider";
import { AdminNav } from "./admin-nav";
import {
  adminRequest,
  servingIndex,
  type AdminProduct,
  type AdminVariant,
  type IndexJob,
  type IndexVersion,
} from "lib/api/admin";
import { money } from "lib/api/commerce";
import { displayText, categoryLabel } from "lib/display-text";

const input =
  "ui-input mt-1 w-full rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-white";
const button =
  "ui-button inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-neutral-900 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200";
const secondary =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-neutral-300 px-4 py-2.5 text-sm font-medium transition-colors hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800";
const panel =
  "rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6 dark:border-neutral-800 dark:bg-neutral-900/50";
const muted = "text-sm leading-6 text-neutral-500 dark:text-neutral-400";
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
type EditorSection = "general" | "variants" | "images";

function usdToCents(value: FormDataEntryValue | null): number {
  const text = String(value ?? "").trim();
  if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(text))
    throw new Error("Enter a USD price with at most two decimal places.");
  const [whole = "0", fraction = ""] = text.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(cents) || cents > 999999999999)
    throw new Error("Price is outside the supported range.");
  return cents;
}

function SearchBadge({ status }: { status: string }) {
  const label =
    (
      {
        ready: "Searchable",
        pending: "Needs indexing",
        indexing: "Indexing",
        failed: "Indexing failed",
      } as Record<string, string>
    )[status] || status;
  return (
    <span
      className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${status === "ready" ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" : status === "failed" ? "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" : "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"}`}
    >
      {label}
    </span>
  );
}

function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const leave = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest("a[href]");
      if (
        !anchor ||
        event.defaultPrevented ||
        anchor.getAttribute("target") === "_blank"
      )
        return;
      if (
        !window.confirm(
          "You have unsaved changes. Discard them and leave this editor?",
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", leave, true);
    return () => {
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", leave, true);
    };
  }, [dirty]);
}

export function AdminPanel() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-7xl px-5 py-12">
          Loading administration…
        </div>
      }
    >
      <AdminWorkspace />
    </Suspense>
  );
}

function IndexWorkspace({
  jobs,
  versions,
  serving,
  loaded,
  error,
  busy,
  rebuild,
}: {
  jobs: IndexJob[];
  versions: IndexVersion[];
  serving: string;
  loaded: boolean;
  error: string;
  busy: boolean;
  rebuild: () => void;
}) {
  const current = versions.find((v) => v.id === serving);
  const latest = jobs[0];
  const openJob = jobs.find((job) =>
    ["pending", "running"].includes(job.status),
  );
  return (
    <section>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Product search</h2>
          <p className={`mt-2 max-w-2xl ${muted}`}>
            Publish catalog changes to search. Customers can keep searching
            while a new index is prepared.
          </p>
        </div>
        <button
          className={button}
          disabled={busy || !!openJob || !loaded}
          onClick={rebuild}
        >
          {openJob ? "Rebuild in progress" : "Rebuild search index"}
        </button>
      </div>
      {error && (
        <p
          role="status"
          className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
        >
          {error}
        </p>
      )}
      <div className="mb-8 grid gap-4 sm:grid-cols-2">
        <div className={panel}>
          <p className={muted}>Currently serving</p>
          <p className="mt-3 flex items-center gap-2 text-xl font-semibold">
            {serving ? (
              <>
                <Check className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                Search available
              </>
            ) : loaded ? (
              "Unavailable"
            ) : (
              "Checking…"
            )}
          </p>
          {current && (
            <p className={`mt-2 ${muted}`}>
              {current.num_vectors.toLocaleString()} indexed images
            </p>
          )}
          {serving && (
            <details className="mt-4 text-xs text-neutral-500 dark:text-neutral-400">
              <summary className="cursor-pointer">Version details</summary>
              <p className="mt-2 break-all font-mono">{serving}</p>
            </details>
          )}
        </div>
        <div className={panel}>
          <p className={muted}>Latest rebuild</p>
          <p className="mt-3 text-xl font-semibold">
            {latest
              ? (
                  {
                    done: "Build completed",
                    failed: "Build failed",
                    pending: "Queued",
                    running: "Building index",
                  } as Record<string, string>
                )[latest.status] || latest.status
              : loaded
                ? "No rebuilds yet"
                : "Loading…"}
          </p>
          <p className={`mt-2 ${muted}`}>
            {latest
              ? new Date(latest.created_at).toLocaleString()
              : "Your build history will appear here."}
          </p>
          <p className="mt-3 text-xs leading-5 text-neutral-500 dark:text-neutral-400">
            A completed build is published first. Search switches after the new
            version passes validation.
          </p>
        </div>
      </div>
      <h3 className="mb-4 text-lg font-semibold">Build history</h3>
      <div className="space-y-3">
        {jobs.map((job) => (
          <article key={job.id} className={panel}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span
                className={`rounded-md px-2 py-1 text-xs font-medium ${job.status === "failed" ? "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300" : job.status === "done" ? "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200" : "bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200"}`}
              >
                {(
                  {
                    done: "Completed",
                    failed: "Failed",
                    pending: "Queued",
                    running: "Running",
                  } as Record<string, string>
                )[job.status] || job.status}
              </span>
              <time className="text-sm text-neutral-500 dark:text-neutral-400">
                {new Date(job.created_at).toLocaleString()}
              </time>
            </div>
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-neutral-600 dark:text-neutral-300">
                {job.error ? "View failure details" : "Build details"}
              </summary>
              <div className="mt-3 space-y-2 break-words text-xs leading-5 text-neutral-500 dark:text-neutral-400">
                <p className="break-all font-mono">Job: {job.id}</p>
                {job.started_at && (
                  <p>Started: {new Date(job.started_at).toLocaleString()}</p>
                )}
                {job.finished_at && (
                  <p>Finished: {new Date(job.finished_at).toLocaleString()}</p>
                )}
                {job.error && (
                  <p className="rounded-lg bg-red-50 p-3 text-red-700 dark:bg-red-950/40 dark:text-red-300">
                    {job.error}
                  </p>
                )}
              </div>
            </details>
          </article>
        ))}
      </div>
      {loaded && !jobs.length && (
        <p className={muted}>
          No rebuild jobs yet. Run a rebuild after you update catalog content.
        </p>
      )}
      <h3 className="mb-4 mt-10 text-lg font-semibold">Index versions</h3>
      <div className="space-y-3">
        {versions.map((version) => (
          <details key={version.id} className={panel}>
            <summary className="cursor-pointer">
              <span className="text-sm font-medium">
                {version.id === serving
                  ? "Serving customers"
                  : version.is_active
                    ? "Published · awaiting activation"
                    : "Retained version"}
              </span>
              <span className="mt-2 block text-xs text-neutral-500 dark:text-neutral-400">
                {version.num_vectors.toLocaleString()} images ·{" "}
                {new Date(version.built_at).toLocaleString()}
              </span>
            </summary>
            <p className="mt-4 break-all font-mono text-xs text-neutral-500 dark:text-neutral-400">
              {version.version_tag}
              <br />
              {version.id}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}

function ProductEditor({
  product,
  section,
  setSection,
  dirty,
  setDirty,
  saved,
  reload,
}: {
  product: AdminProduct;
  section: EditorSection;
  setSection: (value: EditorSection) => void;
  dirty: boolean;
  setDirty: (value: boolean) => void;
  saved: (value: AdminProduct) => void;
  reload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [formRevision, setFormRevision] = useState(0);
  const changedForms = useRef(new Set<HTMLFormElement>());
  async function mutate(
    path: string,
    method: string,
    body?: BodyInit,
    submittedForm?: HTMLFormElement,
  ) {
    if (
      Array.from(changedForms.current).some((form) => form !== submittedForm) &&
      !window.confirm(
        "This action will reload the product and discard unsaved changes in other forms. Continue?",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const result = await adminRequest<{ data: AdminProduct }>(path, {
        method,
        body,
      });
      setDirty(false);
      saved(result.data);
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
    try {
      void mutate(
        product.id ? `/products/${product.id}` : "/products",
        product.id ? "PUT" : "POST",
        JSON.stringify({
          handle: text("handle"),
          name: text("name"),
          description: text("description"),
          brand: text("brand"),
          category: text("category"),
          price_cents: usdToCents(form.get("price_usd")),
          is_active: form.has("is_active"),
          is_featured: form.has("is_featured"),
          revision: product.revision,
          default_variant_id: text("default_variant_id"),
        }),
        event.currentTarget,
      );
    } catch (error) {
      setError(message(error));
    }
  }
  function switchSection(value: EditorSection) {
    if (busy || value === section) return;
    if (
      dirty &&
      !window.confirm("Discard unsaved changes before switching sections?")
    )
      return;
    changedForms.current.clear();
    setDirty(false);
    setError("");
    setSection(value);
    setFormRevision((v) => v + 1);
  }
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-2 text-xs font-medium text-neutral-500 dark:text-neutral-400">
            {product.id ? "Product editor" : "Create product"}
          </p>
          <h2 className="break-words text-xl font-semibold sm:text-2xl">
            {displayText(product.name) || "New product"}
          </h2>
          <div className="mt-3 flex flex-wrap gap-3">
            {product.id && <SearchBadge status={product.search_status} />}
            <span className="self-center text-xs text-neutral-500 dark:text-neutral-400">
              {dirty
                ? "Unsaved changes"
                : product.id
                  ? "All changes saved"
                  : "Not saved yet"}
            </span>
          </div>
        </div>
        {product.id && (
          <button className={secondary} disabled={busy} onClick={reload}>
            Reload product
          </button>
        )}
      </div>
      <div
        className="mb-6 flex gap-2 overflow-x-auto"
        aria-label="Product editor sections"
      >
        {(
          [
            ["general", "General"],
            ["variants", "Variants & stock"],
            ["images", "Images"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={section === id}
            disabled={busy || (!product.id && id !== "general")}
            onClick={() => switchSection(id)}
            className={`min-h-11 shrink-0 rounded-xl px-4 py-2.5 text-sm font-medium disabled:opacity-40 ${section === id ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : "border border-neutral-300 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"}`}
          >
            {label}
            {id === "images" && product.images
              ? ` (${product.images.length})`
              : ""}
          </button>
        ))}
      </div>
      <p className={`mb-5 ${muted}`}>
        {product.id
          ? "Saved catalog edits become searchable after rebuilding the search index."
          : "Save the product first, then add variants and upload images."}
      </p>
      {error && (
        <p
          role="alert"
          className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
        >
          {error}
        </p>
      )}
      <div
        key={`${section}:${formRevision}`}
        onChangeCapture={(event) => {
          const target = event.target as HTMLInputElement;
          if (target.form) changedForms.current.add(target.form);
          setDirty(true);
        }}
      >
        {section === "general" && (
          <form
            onSubmit={save}
            className={`${panel} grid gap-5 sm:grid-cols-2`}
          >
            <label className="text-sm font-medium sm:col-span-2">
              Product name
              <input
                name="name"
                defaultValue={product.name}
                required
                maxLength={200}
                className={input}
              />
            </label>
            <label className="text-sm font-medium">
              URL handle
              <input
                name="handle"
                defaultValue={product.handle}
                required
                maxLength={120}
                pattern="[a-z0-9]+(-[a-z0-9]+)*"
                className={input}
              />
              <span className="mt-1 block text-xs font-normal text-neutral-500 dark:text-neutral-400">
                Lowercase words separated by hyphens.
              </span>
            </label>
            <label className="text-sm font-medium">
              Base price (USD)
              <input
                name="price_usd"
                type="number"
                min={0}
                max="9999999999.99"
                step="0.01"
                required
                defaultValue={(product.price_cents / 100).toFixed(2)}
                className={input}
              />
              <span className="mt-1 block text-xs font-normal text-neutral-500 dark:text-neutral-400">
                Enter 49.00 for $49.00.
              </span>
            </label>
            <label className="text-sm font-medium">
              Brand
              <input
                name="brand"
                defaultValue={product.brand}
                maxLength={120}
                className={input}
              />
            </label>
            <label className="text-sm font-medium">
              Category
              <input
                name="category"
                defaultValue={product.category}
                maxLength={100}
                className={input}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Description
              <textarea
                name="description"
                defaultValue={product.description}
                maxLength={5000}
                rows={5}
                className={input}
              />
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="is_active"
                defaultChecked={product.is_active}
              />
              Active in storefront
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="is_featured"
                defaultChecked={product.is_featured}
              />
              Featured on homepage
            </label>
            {product.id && (
              <label className="text-sm font-medium sm:col-span-2">
                Default variant
                <select
                  name="default_variant_id"
                  defaultValue={product.default_variant_id}
                  className={input}
                >
                  <option value="">No default</option>
                  {product.variants?.map((variant) => (
                    <option key={variant.id} value={variant.id}>
                      {[variant.size, variant.color]
                        .filter(Boolean)
                        .join(" / ") || "Default"}
                      {!variant.is_available ? " (unavailable)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex flex-wrap items-center gap-3 border-t border-neutral-200 pt-5 sm:col-span-2 dark:border-neutral-800">
              <button className={button} disabled={busy}>
                {busy ? "Saving…" : "Save product"}
              </button>
              {product.id && product.is_active && (
                <button
                  type="button"
                  className={secondary}
                  disabled={busy}
                  onClick={() => {
                    if (
                      window.confirm(
                        "Archive this product? It will be hidden from the storefront.",
                      )
                    )
                      void mutate(`/products/${product.id}`, "DELETE");
                  }}
                >
                  Archive product
                </button>
              )}
              {product.id && (
                <Link
                  className="min-h-11 py-3 text-sm underline underline-offset-4"
                  href={`/product/${product.handle}`}
                >
                  View storefront
                </Link>
              )}
            </div>
          </form>
        )}
        {section === "variants" && (
          <section>
            <div className="mb-5">
              <h3 className="text-lg font-semibold">Variants & stock</h3>
              <p className={`mt-2 ${muted}`}>
                Manage sizes, colors, prices and availability. Stock changes are
                checked against the last loaded inventory.
              </p>
            </div>
            <div className="space-y-4">
              {product.variants?.map((variant) => (
                <details key={variant.id} className={panel}>
                  <summary className="cursor-pointer">
                    <span className="font-medium">
                      {[variant.size, variant.color]
                        .filter(Boolean)
                        .join(" / ") || "Default variant"}
                    </span>
                    <span className="mt-2 block text-sm text-neutral-500 dark:text-neutral-400">
                      {money(variant.price_cents)} · {variant.stock} in stock ·{" "}
                      {variant.is_available ? "Available" : "Disabled"}
                    </span>
                  </summary>
                  <VariantForm
                    variant={variant}
                    busy={busy}
                    submit={(body, submittedForm) =>
                      mutate(
                        `/products/${product.id}/variants/${variant.id}`,
                        "PUT",
                        JSON.stringify(body),
                        submittedForm,
                      )
                    }
                    reportError={setError}
                  />
                  <button
                    type="button"
                    className="mt-4 min-h-11 text-sm underline underline-offset-4 disabled:opacity-40"
                    disabled={busy || !variant.is_available}
                    onClick={() => {
                      if (
                        window.confirm(
                          "Disable this variant for new purchases?",
                        )
                      )
                        void mutate(
                          `/products/${product.id}/variants/${variant.id}`,
                          "DELETE",
                        );
                    }}
                  >
                    Disable variant
                  </button>
                </details>
              ))}
              <details className={panel} open={!product.variants?.length}>
                <summary className="cursor-pointer font-medium">
                  Add a variant
                </summary>
                <VariantForm
                  busy={busy}
                  submit={(body, submittedForm) =>
                    mutate(
                      `/products/${product.id}/variants`,
                      "POST",
                      JSON.stringify(body),
                      submittedForm,
                    )
                  }
                  reportError={setError}
                />
              </details>
            </div>
          </section>
        )}
        {section === "images" && (
          <section>
            <div className="mb-5">
              <h3 className="text-lg font-semibold">Product images</h3>
              <p className={`mt-2 ${muted}`}>
                Choose a primary image and adjust the gallery order. Removed
                images remain retained for historical orders and indexes.
              </p>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              {product.images?.map((image) => (
                <form
                  key={image.id}
                  className={panel}
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
                      event.currentTarget,
                    );
                  }}
                >
                  <div className="mb-4 flex items-start gap-4">
                    <img
                      src={image.url}
                      alt={image.alt || product.name}
                      className="h-36 w-28 rounded-xl bg-white object-contain"
                    />
                    <div className="min-w-0">
                      <p className="font-medium">
                        {image.is_primary ? "Primary image" : "Gallery image"}
                      </p>
                      <p className={`mt-2 ${muted}`}>
                        Position {image.position}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-4">
                    <label className="block text-sm font-medium">
                      Image description
                      <input
                        name="alt"
                        defaultValue={image.alt}
                        maxLength={200}
                        className={input}
                      />
                    </label>
                    <label className="block text-sm font-medium">
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
                    <label className="flex min-h-11 items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        name="is_primary"
                        defaultChecked={image.is_primary}
                      />
                      Use as primary image
                    </label>
                    <div className="flex flex-wrap gap-3">
                      <button className={button} disabled={busy}>
                        Save image
                      </button>
                      <button
                        type="button"
                        className={secondary}
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              "Remove this image from the current gallery?",
                            )
                          )
                            void mutate(
                              `/products/${product.id}/images/${image.id}`,
                              "DELETE",
                            );
                        }}
                      >
                        Remove image
                      </button>
                    </div>
                  </div>
                </form>
              ))}
            </div>
            {!product.images?.length && (
              <div className={`${panel} mb-5 text-center`}>
                <ImageIcon className="mx-auto mb-3 h-8 w-8 text-neutral-400" />
                <p className="font-medium">No images yet</p>
                <p className={`mt-2 ${muted}`}>
                  Upload an image to complete this product.
                </p>
              </div>
            )}
            <form
              className={`${panel} mt-6 space-y-4`}
              onSubmit={(event) => {
                event.preventDefault();
                void mutate(
                  `/products/${product.id}/images`,
                  "POST",
                  new FormData(event.currentTarget),
                  event.currentTarget,
                );
              }}
            >
              <h4 className="font-semibold">Upload image</h4>
              <p className={muted}>
                JPEG or PNG, up to 10 MB. Up to 20 active images per product.
              </p>
              <label className="block text-sm font-medium">
                Image file
                <input
                  className={input}
                  name="image"
                  type="file"
                  accept="image/png,image/jpeg"
                  required
                />
              </label>
              <label className="block text-sm font-medium">
                Image description
                <input name="alt" maxLength={200} className={input} />
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input name="primary" type="checkbox" value="true" />
                Use as primary image
              </label>
              <button className={button} disabled={busy}>
                {busy ? "Uploading…" : "Upload image"}
              </button>
            </form>
          </section>
        )}
      </div>
    </div>
  );
}

function VariantForm({
  variant,
  busy,
  submit,
  reportError,
}: {
  variant?: AdminVariant;
  busy: boolean;
  submit: (body: unknown, submittedForm: HTMLFormElement) => Promise<void>;
  reportError: (message: string) => void;
}) {
  return (
    <form
      className="mt-5 grid gap-4 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        try {
          void submit(
            {
              sku: String(form.get("sku") || ""),
              size: String(form.get("size") || ""),
              color: String(form.get("color") || ""),
              price_cents: usdToCents(form.get("price_usd")),
              stock: Number(form.get("stock")),
              is_available: form.has("is_available"),
              ...(variant ? { expected_stock: variant.stock } : {}),
            },
            event.currentTarget,
          );
        } catch (error) {
          reportError(message(error));
        }
      }}
    >
      {(
        [
          { key: "sku", label: "SKU", max: 120 },
          { key: "size", label: "Size", max: 100 },
          { key: "color", label: "Color", max: 100 },
        ] as const
      ).map((field) => (
        <label className="text-sm font-medium" key={field.key}>
          {field.label}
          <input
            name={field.key}
            maxLength={field.max}
            defaultValue={variant?.[field.key] || ""}
            className={input}
          />
        </label>
      ))}
      <label className="text-sm font-medium">
        Price (USD)
        <input
          name="price_usd"
          type="number"
          min={0}
          max="9999999999.99"
          step="0.01"
          required
          defaultValue={((variant?.price_cents ?? 0) / 100).toFixed(2)}
          className={input}
        />
      </label>
      <label className="text-sm font-medium">
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
      <label className="flex min-h-11 items-center gap-2 self-end text-sm">
        <input
          name="is_available"
          type="checkbox"
          defaultChecked={variant?.is_available ?? true}
        />
        Available for purchase
      </label>
      <div className="sm:col-span-2">
        <button className={button} disabled={busy}>
          {busy ? "Saving…" : variant ? "Save variant" : "Create variant"}
        </button>
      </div>
    </form>
  );
}

function AdminWorkspace() {
  const { user, loading } = useAuth();
  const params = useSearchParams();
  const tab = params.get("tab") === "index" ? "index" : "products";
  const allowed = user?.role === "admin";
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [catalog, setCatalog] = useState<{
    owner: string;
    data: AdminProduct[];
    pages: number;
    total: number;
  } | null>(null);
  const [selected, setSelected] = useState<{
    owner: string;
    value: AdminProduct;
  } | null>(null);
  const [section, setSection] = useState<EditorSection>("general");
  const [dirty, setDirty] = useState(false);
  const [jobs, setJobs] = useState<IndexJob[]>([]);
  const [versions, setVersions] = useState<IndexVersion[]>([]);
  const [serving, setServing] = useState("");
  const [indexLoaded, setIndexLoaded] = useState(false);
  const [indexError, setIndexError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [editorGeneration, setEditorGeneration] = useState(0);
  useUnsavedChanges(dirty);
  useEffect(() => {
    setCatalog(null);
    setError("");
    if (!allowed || !user) return;
    let alive = true;
    adminRequest<{
      data: AdminProduct[];
      pagination: { pages: number; total: number };
    }>(`/products?page=${page}&q=${encodeURIComponent(query)}`)
      .then((value) => {
        if (alive)
          setCatalog({
            owner: user.id,
            data: value.data,
            pages: value.pagination.pages,
            total: value.pagination.total,
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
    setIndexLoaded(false);
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
            setIndexLoaded(true);
            setServing(s?.active_index_version || "");
            setIndexError(
              s
                ? ""
                : "Search is starting or temporarily unavailable. Catalog administration is still available.",
            );
          }
        })
        .catch((error) => {
          if (alive) {
            setIndexError(message(error));
            setIndexLoaded(true);
          }
        });
    };
    update();
    const timer = setInterval(update, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [allowed, user?.id, revision]);
  useEffect(() => {
    if (tab === "index") {
      setSelected(null);
      setDirty(false);
    }
  }, [tab]);
  const product =
    selected?.owner === user?.id ? (selected?.value ?? null) : null;
  const records = catalog?.owner === user?.id ? catalog : null;
  function discard() {
    return !dirty || window.confirm("Discard unsaved changes?");
  }
  async function open(id: string) {
    if (!discard()) return;
    setBusy(true);
    setError("");
    try {
      const result = await adminRequest<{ data: AdminProduct }>(
        `/products/${id}`,
      );
      if (user) {
        setSelected({ owner: user.id, value: result.data });
        setEditorGeneration((v) => v + 1);
        setDirty(false);
        setSection("general");
      }
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  function saved(value: AdminProduct) {
    if (user) setSelected({ owner: user.id, value });
    setEditorGeneration((v) => v + 1);
    setDirty(false);
    setRevision((v) => v + 1);
  }
  async function rebuild() {
    setBusy(true);
    setError("");
    try {
      await adminRequest("/index/jobs", { method: "POST" });
      setRevision((v) => v + 1);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-10 lg:px-8">
      <div className="mb-6">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500 dark:text-neutral-400">
          Workspace
        </p>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Administration
        </h1>
        <p className={`mt-2 ${muted}`}>
          Manage your catalog, customer reviews and product search.
        </p>
      </div>
      <AdminNav active={tab} />
      {loading ? (
        <p className={muted}>Loading account…</p>
      ) : !user ? (
        <div className={panel}>
          <h2 className="font-semibold">Sign in to continue</h2>
          <p className={`mt-2 ${muted}`}>
            Use an administrator account to manage this store.
          </p>
          <Link href="/login?next=/admin" className={`${button} mt-5`}>
            Sign in
          </Link>
        </div>
      ) : !allowed ? (
        <div role="alert" className={panel}>
          <h2 className="font-semibold">Administrator access required</h2>
          <p className={`mt-2 ${muted}`}>
            Your account can shop and manage personal orders.
          </p>
          <Link href="/search" className={`${secondary} mt-5`}>
            Back to shop
          </Link>
        </div>
      ) : (
        <>
          {error && (
            <div
              role="alert"
              className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
            >
              {error}
            </div>
          )}
          {tab === "index" ? (
            <IndexWorkspace
              jobs={jobs}
              versions={versions}
              serving={serving}
              loaded={indexLoaded}
              error={indexError}
              busy={busy}
              rebuild={rebuild}
            />
          ) : product ? (
            <>
              <button
                className="mb-5 flex min-h-11 items-center gap-2 text-sm font-medium"
                disabled={busy}
                onClick={() => {
                  if (discard()) {
                    setSelected(null);
                    setDirty(false);
                  }
                }}
              >
                <ArrowLeft className="h-4 w-4" />
                Back to products
              </button>
              <ProductEditor
                key={`${product.id}:${product.revision}:${editorGeneration}`}
                product={product}
                section={section}
                setSection={setSection}
                dirty={dirty}
                setDirty={setDirty}
                saved={saved}
                reload={() => void open(product.id)}
              />
            </>
          ) : (
            <section>
              <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">Products</h2>
                  <p className={`mt-1 ${muted}`}>
                    {records
                      ? `${records.total.toLocaleString()} ${query ? "matching " : ""}products`
                      : "Your catalog and storefront availability"}
                  </p>
                </div>
                <button
                  className={button}
                  disabled={busy}
                  onClick={() => {
                    if (user && discard()) {
                      setSelected({ owner: user.id, value: { ...empty } });
                      setSection("general");
                      setDirty(false);
                    }
                  }}
                >
                  <Plus className="h-4 w-4" />
                  Add product
                </button>
              </div>
              <form
                className="mb-6 flex max-w-xl gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  setQuery(search.trim());
                  setPage(1);
                }}
              >
                <label className="min-w-0 flex-1">
                  <span className="sr-only">Find products in catalog</span>
                  <input
                    className={input}
                    value={search}
                    placeholder="Find products by name, brand or handle…"
                    maxLength={200}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <button className={`${secondary} mt-1`}>
                  <Search className="h-4 w-4" />
                  <span className="hidden sm:inline">Find</span>
                  <span className="sr-only sm:hidden">Find products</span>
                </button>
              </form>
              {!records ? (
                error ? (
                  <p className={muted}>
                    Catalog unavailable.{" "}
                    <button
                      className="underline"
                      onClick={() => setRevision((v) => v + 1)}
                    >
                      Try again
                    </button>
                  </p>
                ) : (
                  <div aria-label="Loading products" className="space-y-3">
                    {[0, 1, 2].map((v) => (
                      <div
                        key={v}
                        className="h-20 animate-pulse rounded-xl bg-neutral-200 dark:bg-neutral-800"
                      />
                    ))}
                  </div>
                )
              ) : (
                <>
                  <div className="hidden overflow-hidden rounded-2xl border border-neutral-200 md:block dark:border-neutral-800">
                    <table className="w-full table-fixed text-left text-sm">
                      <thead className="bg-neutral-100 text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
                        <tr>
                          <th className="w-[42%] px-5 py-4">Product</th>
                          <th className="px-3 py-4">Price</th>
                          <th className="px-3 py-4">Storefront</th>
                          <th className="px-3 py-4">Search</th>
                          <th className="w-20 px-3 py-4">
                            <span className="sr-only">Action</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                        {records.data.map((item) => (
                          <tr
                            key={item.id}
                            className="bg-white hover:bg-neutral-50 dark:bg-neutral-950 dark:hover:bg-neutral-900"
                          >
                            <td className="px-5 py-4">
                              <button
                                className="text-left font-medium hover:underline"
                                disabled={busy}
                                onClick={() => void open(item.id)}
                              >
                                {displayText(item.name)}
                              </button>
                              <p className="mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400">
                                {[
                                  displayText(item.brand),
                                  categoryLabel(item.category),
                                ]
                                  .filter(Boolean)
                                  .join(" · ") || item.handle}
                              </p>
                            </td>
                            <td className="px-3 py-4 tabular-nums">
                              {money(item.price_cents, item.currency)}
                            </td>
                            <td className="px-3 py-4">
                              <span
                                className={
                                  item.is_active
                                    ? "text-neutral-900 dark:text-neutral-200"
                                    : "text-neutral-500"
                                }
                              >
                                {item.is_active ? "Active" : "Archived"}
                              </span>
                            </td>
                            <td className="px-3 py-4">
                              <SearchBadge status={item.search_status} />
                            </td>
                            <td className="px-3 py-4">
                              <button
                                aria-label={`Edit ${displayText(item.name)}`}
                                className="min-h-11 rounded-lg px-3 hover:bg-neutral-100 dark:hover:bg-neutral-800"
                                disabled={busy}
                                onClick={() => void open(item.id)}
                              >
                                <ChevronRight className="h-4 w-4" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="space-y-3 md:hidden">
                    {records.data.map((item) => (
                      <button
                        key={item.id}
                        disabled={busy}
                        onClick={() => void open(item.id)}
                        className={`${panel} w-full text-left`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <h3 className="font-medium">
                            {displayText(item.name)}
                          </h3>
                          <ChevronRight className="mt-1 h-4 w-4 shrink-0" />
                        </div>
                        <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                          {[
                            displayText(item.brand),
                            categoryLabel(item.category),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                          <span className="font-medium tabular-nums">
                            {money(item.price_cents, item.currency)}
                          </span>
                          <span className="text-xs">
                            {item.is_active ? "Active" : "Archived"}
                          </span>
                          <SearchBadge status={item.search_status} />
                        </div>
                      </button>
                    ))}
                  </div>
                  {!records.data.length && (
                    <div className={`${panel} py-12 text-center`}>
                      <h3 className="font-medium">No products found</h3>
                      <p className={`mt-2 ${muted}`}>
                        Try another name or brand, or add a new product.
                      </p>
                    </div>
                  )}
                  <nav
                    className="mt-6 flex items-center justify-between gap-3 text-sm"
                    aria-label="Admin product pages"
                  >
                    <button
                      className={secondary}
                      disabled={page === 1 || busy}
                      onClick={() => setPage((v) => v - 1)}
                    >
                      <ArrowLeft className="h-4 w-4" />
                      <span className="hidden sm:inline">Previous</span>
                    </button>
                    <span className="text-neutral-500 dark:text-neutral-400">
                      Page {page} of {Math.max(1, records.pages)}
                    </span>
                    <button
                      className={secondary}
                      disabled={page >= records.pages || busy}
                      onClick={() => setPage((v) => v + 1)}
                    >
                      <span className="hidden sm:inline">Next</span>
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </nav>
                </>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
