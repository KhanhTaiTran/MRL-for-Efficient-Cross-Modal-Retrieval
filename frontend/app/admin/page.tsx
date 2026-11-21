import { AdminPanel } from "components/admin/admin-panel";
export const metadata = {
  title: "Catalog administration",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <AdminPanel />;
}
