import { OrderPage } from "components/commerce/commerce-pages";
export const metadata = {
  title: "Order details",
  robots: { index: false, follow: false },
};
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <OrderPage id={id} />;
}
