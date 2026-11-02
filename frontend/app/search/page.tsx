import { CatalogBrowser } from "components/catalog/catalog-browser";
import { StoreHeader } from "components/layout/store-header";

export const metadata = {
  title: "Shop",
  description: "Explore the AuraFind catalog.",
};
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; q?: string }>;
}) {
  const params = await searchParams;
  return (
    <>
      <StoreHeader />
      <CatalogBrowser
        key={`${params.category ?? ""}:${params.q ?? ""}`}
        initialCategory={params.category}
        initialQuery={params.q}
      />
    </>
  );
}
