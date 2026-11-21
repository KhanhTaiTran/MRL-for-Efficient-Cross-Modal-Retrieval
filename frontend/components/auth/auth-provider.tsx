"use client";

import { createContext, useContext, useEffect, useState } from "react";
import {
  acceptSession,
  clearSession,
  currentSession,
  refreshSession,
  type AccountUser,
  type Session,
} from "lib/api/client";

const Context = createContext<{
  user: AccountUser | null;
  loading: boolean;
  setSession: (session: Session | null) => void;
}>({ user: null, loading: true, setSession: acceptSession });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    const update = () => {
      if (alive) setUser(currentSession()?.user ?? null);
    };
    window.addEventListener("aurafind-session", update);
    refreshSession()
      .catch(() => {})
      .finally(() => {
        if (alive) setLoading(false);
      });
    const channel =
      typeof BroadcastChannel !== "undefined"
        ? new BroadcastChannel("aurafind-account")
        : null;
    if (channel)
      channel.onmessage = (message) => {
        if (message.data === "logout") clearSession();
      };
    return () => {
      alive = false;
      window.removeEventListener("aurafind-session", update);
      channel?.close();
    };
  }, []);
  return (
    <Context.Provider value={{ user, loading, setSession: acceptSession }}>
      {children}
    </Context.Provider>
  );
}
export function useAuth() {
  return useContext(Context);
}
