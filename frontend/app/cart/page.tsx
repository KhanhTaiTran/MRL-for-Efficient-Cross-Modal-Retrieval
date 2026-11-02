import { CartPage } from "components/commerce/commerce-pages";
export const metadata = {
  title: "Your cart",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <CartPage />;
}
