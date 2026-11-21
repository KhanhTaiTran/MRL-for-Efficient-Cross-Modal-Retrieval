"use client";
import { SearchProvider } from "components/aurafind/search-provider";
import { ThemeProvider } from "./theme-provider";
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
export function SiteShell({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <SearchProvider>
        <div className="flex min-h-dvh flex-col">
          <SiteHeader />
          <main id="main-content" className="min-w-0 flex-1" tabIndex={-1}>
            {children}
          </main>
          <SiteFooter />
        </div>
      </SearchProvider>
    </ThemeProvider>
  );
}
