"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import {
  authenticatedRequest,
  currentSession,
  signOut,
  type AccountUser,
} from "lib/api/client";

export function AccountPage() {
  const { user, loading, setSession } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const name = new FormData(event.currentTarget).get("name");
      const result = await authenticatedRequest<{ user: AccountUser }>(
        "/auth/me",
        { method: "PATCH", body: JSON.stringify({ name }) },
      );
      const session = currentSession();
      if (session) setSession({ ...session, user: result.user });
      setMessage("Your profile has been updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6 sm:py-12">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Your account
        </h1>
        {loading ? (
          <p role="status" className="mt-6 text-neutral-500">
            Loading your account…
          </p>
        ) : !user ? (
          <div className="mt-6 space-y-5">
            <p className="text-neutral-500">Sign in to manage your account.</p>
            <Link
              href="/login?next=/account"
              className="inline-block rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white dark:bg-white dark:text-neutral-900"
            >
              Sign in
            </Link>
            <p className="text-sm">
              <Link className="underline" href="/register">
                Create an account
              </Link>
            </p>
          </div>
        ) : (
          <>
            <p className="mt-4 break-words text-sm text-neutral-600 dark:text-neutral-400">
              {user.email} · Email verified
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                href="/account/orders"
                className="inline-flex min-h-11 items-center rounded-xl border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
              >
                Your orders
              </Link>
              <Link
                href="/wishlist"
                className="inline-flex min-h-11 items-center rounded-xl border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
              >
                Saved items
              </Link>
              {user.role === "admin" && (
                <Link
                  href="/admin"
                  className="inline-flex min-h-11 items-center rounded-xl border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
                >
                  Manage catalog
                </Link>
              )}
            </div>
            <form
              onSubmit={save}
              className="mt-8 space-y-5 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-7 dark:border-neutral-800 dark:bg-neutral-900/40"
            >
              <h2 className="text-lg font-semibold">Profile details</h2>
              <label className="block text-sm font-medium">
                Name
                <input
                  key={user.id}
                  name="name"
                  defaultValue={user.name}
                  autoComplete="name"
                  required
                  maxLength={120}
                  className="mt-2 min-h-12 w-full rounded-xl border border-neutral-300 bg-white px-4 py-3 text-base dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
                />
              </label>
              <button
                disabled={busy}
                className="min-h-11 w-full rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:opacity-50 sm:w-auto dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
              >
                {busy ? "Saving…" : "Save changes"}
              </button>
            </form>
            {message && (
              <p role="status" className="mt-5 text-sm">
                {message}
              </p>
            )}
            <button
              type="button"
              disabled={busy}
              className="mt-8 min-h-11 text-sm text-neutral-600 underline underline-offset-4 dark:text-neutral-400"
              onClick={async () => {
                setBusy(true);
                try {
                  await signOut();
                  router.replace("/login");
                } catch (error) {
                  setMessage(
                    error instanceof Error
                      ? error.message
                      : "Please try again.",
                  );
                  setBusy(false);
                }
              }}
            >
              Sign out
            </button>
          </>
        )}
      </section>
    </>
  );
}
