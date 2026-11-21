import { Suspense } from "react";
import { AuthForm } from "components/auth/auth-form";

export const metadata = {
  title: "Verify email",
  robots: { index: false, follow: false },
};
export default function Page() {
  return (
    <Suspense fallback={<p className="p-8">Loading…</p>}>
      <AuthForm mode="verify-email" />
    </Suspense>
  );
}
