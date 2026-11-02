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
import { StoreHeader } from "components/layout/store-header";

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
      <StoreHeader />
      <div className="mx-auto max-w-xl px-6 py-14">
        <h1 className="text-3xl font-semibold tracking-tight">Your account</h1>
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
            <p className="mt-4 text-sm text-neutral-500">
              {user.email} · Email verified
            </p>
            <form onSubmit={save} className="mt-8 space-y-5">
              <label className="block text-sm font-medium">
                Name
                <input
                  key={user.id}
                  name="name"
                  defaultValue={user.name}
                  autoComplete="name"
                  required
                  maxLength={120}
                  className="mt-2 w-full rounded-xl border border-neutral-300 bg-transparent px-4 py-3 dark:border-neutral-700"
                />
              </label>
              <button
                disabled={busy}
                className="rounded-xl bg-neutral-900 px-6 py-3 text-sm font-semibold text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
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
              className="mt-10 text-sm underline underline-offset-4"
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
      </div>
    </>
  );
}
