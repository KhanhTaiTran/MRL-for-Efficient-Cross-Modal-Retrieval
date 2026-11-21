import { Suspense } from "react";
import { AuthForm } from "components/auth/auth-form";

export const metadata = {
  title: "Forgot password",
  robots: { index: false, follow: false },
};
export default function Page() {
  return (
    <Suspense fallback={<p className="p-8">Loading…</p>}>
      <AuthForm mode="forgot-password" />
    </Suspense>
  );
}
