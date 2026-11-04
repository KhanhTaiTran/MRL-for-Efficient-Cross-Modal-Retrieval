import { WishlistPage } from "components/catalog/wishlist-page";
export const metadata = {
  title: "Your wishlist",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <WishlistPage />;
}
