import { CatalogBrowser } from "components/catalog/catalog-browser";

export const metadata = {
  title: "Shop",
  description: "Explore the AuraFind catalog.",
};
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{
    category?: string;
    q?: string;
    sort?: string;
    page?: string;
  }>;
}) {
  const params = await searchParams;
  return (
    <>
      <CatalogBrowser
        key={`${params.category ?? ""}:${params.q ?? ""}:${params.sort ?? ""}:${params.page ?? ""}`}
        initialCategory={params.category}
        initialQuery={params.q}
      />
    </>
  );
}
