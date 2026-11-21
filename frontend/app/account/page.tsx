import { AccountPage } from "components/auth/account-page";

export const metadata = {
  title: "Your account",
  robots: { index: false, follow: false },
};
export default function Page() {
  return <AccountPage />;
}
