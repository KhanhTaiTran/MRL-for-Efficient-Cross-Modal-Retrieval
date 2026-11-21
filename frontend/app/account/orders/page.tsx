import { OrdersPage } from "components/commerce/commerce-pages";
export const metadata = {
  title: "Your orders",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <OrdersPage />;
}
