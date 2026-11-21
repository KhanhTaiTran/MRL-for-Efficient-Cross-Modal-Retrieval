import { Suspense } from "react";
import { SearchResults } from "components/aurafind/search-results";
export const metadata = {
  title: "Discover",
  description: "Find fashion by describing a look or uploading an image.",
};
export default function DiscoverPage() {
  return (
    <Suspense
      fallback={
        <div className="site-container py-12" role="status">
          Preparing your search…
        </div>
      }
    >
      <SearchResults />
    </Suspense>
  );
}
