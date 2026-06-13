import { Carousel } from "components/carousel";
import { ThreeItemGrid } from "components/grid/three-items";
import Footer from "components/layout/footer";
import {
  ArrowRightIcon,
  BoltIcon,
  SparklesIcon,
} from "@heroicons/react/24/outline";
import Link from "next/link";

export const metadata = {
  description:
    "E-commerce prototype with smart visual search powered by Matryoshka Representation Learning.",
  openGraph: {
    type: "website",
  },
};

export default function HomePage() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-950">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(124,58,237,0.12),transparent_55%)] dark:bg-[radial-gradient(ellipse_at_top_right,rgba(124,58,237,0.18),transparent_55%)]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(0,0,0,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(0,0,0,0.03)_1px,transparent_1px)] bg-size-[4rem_4rem] dark:bg-[linear-gradient(to_right,rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.04)_1px,transparent_1px)]"
        />

        <div className="relative mx-auto max-w-(--breakpoint-2xl) px-4 py-16 sm:py-20 lg:px-6 lg:py-28">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-violet-200 bg-violet-50 px-3 py-1 text-xs font-medium tracking-wide text-violet-700 dark:border-violet-800/60 dark:bg-violet-950/50 dark:text-violet-300">
              <SparklesIcon className="h-3.5 w-3.5" />
              Powered by Matryoshka Representation Learning
            </div>

            <h1 className="text-balance text-4xl font-semibold tracking-tight text-neutral-900 sm:text-5xl lg:text-6xl dark:text-white">
              Find products by{" "}
              <span className="text-violet-600 dark:text-violet-400">
                what they look like
              </span>
            </h1>

            <p className="mx-auto mt-6 max-w-2xl text-pretty text-base leading-relaxed text-neutral-600 sm:text-lg dark:text-neutral-400">
              Smart Visual Search uses MRL embeddings to match your uploaded
              image against a FAISS index. Tune the embedding dimension to
              explore the tradeoff — lower dimensions scan faster, higher
              dimensions retrieve with greater accuracy.
            </p>

            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/image-search"
                className="group inline-flex items-center gap-2 rounded-full bg-violet-600 px-6 py-3 text-sm font-semibold text-white transition-all duration-200 hover:bg-violet-500 active:scale-[0.98] dark:bg-violet-500 dark:hover:bg-violet-400"
              >
                Try Visual Search
                <ArrowRightIcon className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
              </Link>
              <span className="inline-flex items-center gap-1.5 text-sm text-neutral-500 dark:text-neutral-400">
                <BoltIcon className="h-4 w-4 text-violet-500" />
                Adjustable latency · accuracy curve
              </span>
            </div>
          </div>

          <div className="mx-auto mt-14 grid max-w-4xl gap-4 sm:grid-cols-3">
            {[
              {
                label: "Upload",
                value: "Drop any product photo",
              },
              {
                label: "Embed",
                value: "MRL vector at chosen dim",
              },
              {
                label: "Retrieve",
                value: "Nearest neighbors via FAISS",
              },
            ].map((step) => (
              <div
                key={step.label}
                className="rounded-xl border border-neutral-200 bg-neutral-50/80 px-4 py-4 text-center backdrop-blur-sm dark:border-neutral-800 dark:bg-neutral-900/60"
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
                  {step.label}
                </p>
                <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-300">
                  {step.value}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trending Products */}
      <section className="mx-auto max-w-(--breakpoint-2xl) px-4 pt-10 lg:px-6">
        <div className="mb-4 flex items-end justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-500 dark:text-neutral-400">
              Curated catalog
            </p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight text-neutral-900 dark:text-white">
              Trending products
            </h2>
          </div>
        </div>
      </section>

      <ThreeItemGrid />
      <Carousel />
      <Footer />
    </>
  );
}
