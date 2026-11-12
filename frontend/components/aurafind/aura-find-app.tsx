"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { HeroBanner } from "./home-content";
import { CatalogBrowser } from "components/catalog/catalog-browser";
export function AuraFindApp() {
  const router = useRouter();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const similar = params.get("similar");
    if (similar)
      router.replace(`/discover?similar=${encodeURIComponent(similar)}`);
    else if (params.get("q"))
      router.replace(`/discover?q=${encodeURIComponent(params.get("q")!)}`);
  }, [router]);
  return (
    <div className="pt-5 sm:pt-8">
      <HeroBanner />
      <CatalogBrowser preview />
    </div>
  );
}
