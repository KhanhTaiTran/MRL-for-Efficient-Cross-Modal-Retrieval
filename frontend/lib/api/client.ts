import { API_BASE_URL } from "components/aurafind/types";

export interface AccountUser {
  id: string;
  email: string;
  name: string;
  role: "customer" | "admin";
  is_verified: boolean;
}
export interface Session {
  access_token: string;
  expires_in: number;
  user: AccountUser;
}

let session: Session | null = null;
let expiresAt = 0;
let refreshPromise: Promise<Session | null> | null = null;
let generation = 0;

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

export function currentSession() {
  return session;
}
export function acceptSession(value: Session | null) {
  generation++;
  session = value;
  expiresAt = value ? Date.now() + value.expires_in * 1000 : 0;
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("aurafind-session"));
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}/api${path}`, {
    ...init,
    signal: init.signal ?? AbortSignal.timeout(20000),
    credentials: "include",
    headers,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new APIError(
      response.status,
      data.error || "The request could not be completed.",
      data.code,
    );
  return data as T;
}

async function sessionLock<T>(action: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request("aurafind-session", action);
  }
  return action();
}

export function refreshSession(): Promise<Session | null> {
  if (refreshPromise) return refreshPromise;
  const started = generation;
  refreshPromise = sessionLock(async () => {
    try {
      const value = await request<Session>("/auth/refresh", { method: "POST" });
      if (started !== generation) return null;
      acceptSession(value);
      return value;
    } catch (error) {
      if (error instanceof APIError && error.status === 401) {
        if (started === generation) acceptSession(null);
        return null;
      }
      throw error;
    }
  }).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

export async function authenticatedRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let value = session;
  if (!value || Date.now() > expiresAt - 30000) value = await refreshSession();
  if (!value) throw new APIError(401, "Sign in to continue.");
  const call = (token: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return request<T>(path, { ...init, headers });
  };
  try {
    return await call(value.access_token);
  } catch (error) {
    if (!(error instanceof APIError) || error.status !== 401) throw error;
    const renewed = await refreshSession();
    if (!renewed) throw error;
    return call(renewed.access_token);
  }
}

export async function signOut() {
  await sessionLock(() => request("/auth/logout", { method: "POST" }));
  clearSession();
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel("aurafind-account");
    channel.postMessage("logout");
    channel.close();
  }
}
export function clearSession() {
  acceptSession(null);
}
