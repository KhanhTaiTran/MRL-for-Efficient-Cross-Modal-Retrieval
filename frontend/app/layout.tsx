import { GeistSans } from "geist/font/sans";
import { ReactNode } from "react";
import { Toaster } from "sonner";
import "./globals.css";
import { AuthProvider } from "components/auth/auth-provider";
import { baseUrl } from "lib/utils";

export const metadata = {
  metadataBase: new URL(baseUrl),
  title: {
    default: "AuraFind",
    template: "%s | AuraFind",
  },
  description:
    "AI-first fashion e-commerce with Matryoshka-powered visual search.",
  robots: {
    follow: true,
    index: true,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={GeistSans.variable}>
      <body className="bg-neutral-50 text-neutral-900 antialiased dark:bg-neutral-950 dark:text-white">
        <AuthProvider>
          <main>{children}</main>
        </AuthProvider>
        <Toaster
          closeButton
          toastOptions={{
            classNames: {
              toast:
                "border border-neutral-200 bg-white/95 text-neutral-900 backdrop-blur-md dark:border-neutral-800 dark:bg-neutral-900/95 dark:text-white",
            },
          }}
        />
      </body>
    </html>
  );
}
