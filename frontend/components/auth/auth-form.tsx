"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { clearSession, request, type Session } from "lib/api/client";
import { useAuth } from "./auth-provider";
import { StoreHeader } from "components/layout/store-header";

export type AuthMode =
  | "login"
  | "register"
  | "verify-email"
  | "forgot-password"
  | "reset-password";
const copy = {
  login: ["Welcome back", "Sign in to your AuraFind account.", "Sign in"],
  register: [
    "Make it yours",
    "Create an account to keep your style discoveries together.",
    "Create account",
  ],
  "verify-email": [
    "Check your inbox",
    "Enter the six-digit code we sent to your email.",
    "Verify email",
  ],
  "forgot-password": [
    "Forgot your password?",
    "We will send a code to your email if your account is eligible.",
    "Send reset code",
  ],
  "reset-password": [
    "A fresh start",
    "Use your email code to choose a new password.",
    "Reset password",
  ],
};
const inputClass =
  "mt-2 w-full rounded-xl border border-neutral-300 bg-transparent px-4 py-3 text-base outline-none focus:border-neutral-700 focus:ring-2 focus:ring-neutral-400/30 dark:border-neutral-700";

export function AuthForm({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const params = useSearchParams();
  const { setSession } = useAuth();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const hasPassword = ["login", "register", "reset-password"].includes(mode);
  const hasCode = mode === "verify-email" || mode === "reset-password";
  const [title, subtitle, button] = copy[mode];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    const fields = new FormData(event.currentTarget);
    try {
      const data = await request<Session & { message: string }>(
        `/auth/${mode}`,
        { method: "POST", body: JSON.stringify(Object.fromEntries(fields)) },
      );
      if (mode === "register") {
        router.push(`/verify-email?email=${encodeURIComponent(email)}`);
      } else if (mode === "login" || mode === "verify-email") {
        setSession(data);
        const next = params.get("next");
        router.replace(
          next?.startsWith("/") &&
            !/^\/[\\/]/.test(next) &&
            !next.includes("\\") &&
            !/[\u0000-\u001f]/.test(next)
            ? next
            : "/account",
        );
      } else if (mode === "forgot-password") {
        router.push(`/reset-password?email=${encodeURIComponent(email)}`);
      } else {
        clearSession();
        router.replace("/login?reset=success");
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  async function resend() {
    if (Date.now() < resendAt) {
      setMessage("Please wait 60 seconds before requesting another code.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const data = await request<{ message: string }>(
        "/auth/resend-verification",
        { method: "POST", body: JSON.stringify({ email }) },
      );
      setMessage(data.message);
      setResendAt(Date.now() + 60000);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <StoreHeader />
      <div className="mx-auto w-full max-w-md px-6 py-14 sm:py-20">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-neutral-500">{subtitle}</p>
        {params.get("reset") === "success" && (
          <p
            role="status"
            className="mt-5 text-sm text-green-700 dark:text-green-400"
          >
            Password updated. Sign in with your new password.
          </p>
        )}
        <form onSubmit={submit} className="mt-8 space-y-5">
          {mode === "register" && (
            <label className="block text-sm font-medium">
              Name
              <input
                name="name"
                autoComplete="name"
                required
                maxLength={120}
                className={inputClass}
              />
            </label>
          )}
          <label className="block text-sm font-medium">
            Email
            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </label>
          {hasCode && (
            <label className="block text-sm font-medium">
              Verification code
              <input
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                minLength={6}
                maxLength={6}
                required
                className={inputClass}
              />
            </label>
          )}
          {hasPassword && (
            <label className="block text-sm font-medium">
              {mode === "reset-password" ? "New password" : "Password"}
              <input
                name="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                minLength={mode === "login" ? undefined : 12}
                maxLength={72}
                required
                className={inputClass}
              />
              {mode !== "login" && (
                <span className="mt-2 block text-xs text-neutral-500">
                  Use at least 12 characters.
                </span>
              )}
            </label>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="text-sm text-neutral-500">
              {message}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-neutral-900 px-4 py-3.5 text-sm font-semibold text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            {busy ? "Please wait…" : button}
          </button>
        </form>
        <div className="mt-6 space-y-4 text-sm text-neutral-500">
          {mode === "login" && (
            <>
              <p>
                <Link
                  className="underline underline-offset-4"
                  href="/forgot-password"
                >
                  Forgot password?
                </Link>
              </p>
              <p>
                New here?{" "}
                <Link
                  className="text-neutral-900 underline underline-offset-4 dark:text-white"
                  href="/register"
                >
                  Create an account
                </Link>
              </p>
              <p>
                <Link
                  className="underline underline-offset-4"
                  href={`/verify-email?email=${encodeURIComponent(email)}`}
                >
                  Verify your email
                </Link>
              </p>
            </>
          )}
          {mode === "register" && (
            <p>
              Already have an account?{" "}
              <Link href="/login" className="underline underline-offset-4">
                Sign in
              </Link>
            </p>
          )}
          {mode === "verify-email" && (
            <button
              type="button"
              disabled={busy || !email}
              onClick={resend}
              className="underline underline-offset-4 disabled:opacity-50"
            >
              Send another code
            </button>
          )}
          {mode !== "login" && mode !== "register" && (
            <p>
              <Link href="/login" className="underline underline-offset-4">
                Back to sign in
              </Link>
            </p>
          )}
        </div>
      </div>
    </>
  );
}
