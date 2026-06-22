"use client";

import { motion } from "framer-motion";
import { PRODUCT_GRID_CLASS } from "./constants";
import { TRENDING_PRODUCTS } from "./mock-data";

export function HeroBanner() {
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto max-w-[1600px] px-4 sm:px-6 lg:px-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="relative min-h-[52vh] overflow-hidden rounded-3xl bg-neutral-950 sm:min-h-[58vh]"
        >
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1469334031218-e382a71b716b?w=1600&q=80')] bg-cover bg-center opacity-70"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/75 via-black/45 to-black/20" />

          <div className="relative flex h-full min-h-[52vh] flex-col justify-end p-8 sm:min-h-[58vh] sm:p-12 lg:p-16">
            <motion.p
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15, duration: 0.5 }}
              className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/70"
            >
              AI-First Fashion
            </motion.p>
            <motion.h2
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25, duration: 0.6 }}
              className="max-w-2xl text-balance text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-6xl"
            >
              Find Your Perfect Fit with AI
            </motion.h2>
            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, duration: 0.6 }}
              className="mt-4 max-w-lg text-sm leading-relaxed text-white/75 sm:text-base"
            >
              Describe a look, upload a reference, or discover similar pieces
              with Matryoshka-powered visual search — precision you control.
            </motion.p>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

export function TrendingGrid() {
  return (
    <section className="mx-auto max-w-[1600px] px-4 py-14 sm:px-6 lg:px-8">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-neutral-500">
            Curated for you
          </p>
          <h3 className="mt-1 text-2xl font-semibold tracking-tight text-neutral-900 dark:text-white">
            Trending Products
          </h3>
        </div>
      </div>

      <div className={PRODUCT_GRID_CLASS}>
        {TRENDING_PRODUCTS.map((item, index) => (
          <motion.article
            key={item.id}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-40px" }}
            transition={{
              duration: 0.5,
              delay: index * 0.05,
              ease: [0.22, 1, 0.36, 1],
            }}
            className="group"
          >
            <div className="overflow-hidden rounded-2xl bg-neutral-100 dark:bg-neutral-900">
              <div className="relative aspect-[3/4] overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.image}
                  alt={item.name}
                  loading="lazy"
                  className="h-full w-full object-cover transition-transform duration-500 lg:group-hover:scale-105"
                />
                <span className="absolute left-3 top-3 rounded-full bg-white/90 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-neutral-700 backdrop-blur-sm">
                  {item.category}
                </span>
              </div>
            </div>
            <div className="mt-3">
              <h4 className="text-sm font-medium text-neutral-900 dark:text-white">
                {item.name}
              </h4>
              <p className="mt-0.5 text-sm tabular-nums text-neutral-500">
                {item.price}
              </p>
            </div>
          </motion.article>
        ))}
      </div>
    </section>
  );
}
