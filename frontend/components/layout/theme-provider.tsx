"use client";
import { createContext, useContext, useEffect, useState } from "react";
type Theme = "light" | "dark" | "system";
const ThemeContext = createContext<{
  theme: Theme;
  setTheme: (theme: Theme) => void;
}>({ theme: "system", setTheme: () => {} });
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setValue] = useState<Theme>("system");
  useEffect(() => {
    try {
      const stored = localStorage.getItem("aurafind-theme");
      if (stored === "light" || stored === "dark" || stored === "system")
        setValue(stored);
    } catch {}
  }, []);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      let saved: string = theme;
      try {
        saved = localStorage.getItem("aurafind-theme") || theme;
      } catch {}
      const dark = saved === "dark" || (saved === "system" && media.matches);
      document.documentElement.classList.toggle("dark", dark);
      document.documentElement.style.colorScheme = dark ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
    const sync = (event: StorageEvent) => {
      if (event.key === "aurafind-theme") {
        setValue(
          event.newValue === "light" || event.newValue === "dark"
            ? event.newValue
            : "system",
        );
        apply();
      }
    };
    window.addEventListener("storage", sync);
    return () => {
      media.removeEventListener("change", apply);
      window.removeEventListener("storage", sync);
    };
  }, [theme]);
  const setTheme = (value: Theme) => {
    try {
      localStorage.setItem("aurafind-theme", value);
    } catch {}
    const dark =
      value === "dark" ||
      (value === "system" &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    setValue(value);
  };
  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
export const useTheme = () => useContext(ThemeContext);
