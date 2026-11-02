"use client";

import { motion } from "framer-motion";

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
              that match your style.
            </motion.p>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
