import { GeistSans } from "geist/font/sans";
import { ReactNode } from "react";
import { Toaster } from "sonner";
import "./globals.css";

export const metadata = {
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
        <main>{children}</main>
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
