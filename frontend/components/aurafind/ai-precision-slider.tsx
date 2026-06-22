"use client";

import { motion } from "framer-motion";
import { MRL_DIMENSIONS } from "./types";

interface AiPrecisionSliderProps {
  value: number;
  onChange: (dimension: number) => void;
  disabled?: boolean;
  visible: boolean;
}

export function AiPrecisionSlider({
  value,
  onChange,
  disabled,
  visible,
}: AiPrecisionSliderProps) {
  const index = MRL_DIMENSIONS.indexOf(
    value as (typeof MRL_DIMENSIONS)[number],
  );
  const sliderIndex = index >= 0 ? index : MRL_DIMENSIONS.length - 1;

  return (
    <motion.div
      initial={false}
      animate={{
        height: visible ? "auto" : 0,
        opacity: visible ? 1 : 0,
        marginTop: visible ? 12 : 0,
      }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="overflow-hidden"
    >
      <div className="rounded-2xl border border-neutral-200/80 bg-white/70 px-4 py-4 shadow-sm backdrop-blur-xl dark:border-neutral-800 dark:bg-neutral-950/70">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-neutral-500">
              AI Precision
            </p>
            <p className="text-xs text-neutral-400">MRL Dimension</p>
          </div>
          <span className="rounded-full bg-neutral-900 px-3 py-1 text-xs font-semibold tabular-nums text-white dark:bg-white dark:text-neutral-900">
            {value}
          </span>
        </div>

        <div className="relative px-1">
          <input
            type="range"
            min={0}
            max={MRL_DIMENSIONS.length - 1}
            step={1}
            value={sliderIndex}
            disabled={disabled}
            onChange={(e) => {
              const nextIndex = Number(e.target.value);
              onChange(MRL_DIMENSIONS[nextIndex] ?? value);
            }}
            className="aurafind-slider h-1.5 w-full cursor-pointer appearance-none rounded-full bg-neutral-200 disabled:opacity-50 dark:bg-neutral-800"
            aria-label="AI Precision MRL Dimension"
          />

          <div className="mt-1 flex justify-between px-0.5">
            {MRL_DIMENSIONS.map((dim) => (
              <span
                key={dim}
                className={`text-[9px] tabular-nums transition-colors ${
                  dim === value
                    ? "font-semibold text-neutral-900 dark:text-white"
                    : "text-neutral-300 dark:text-neutral-600"
                }`}
              >
                {dim}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wider text-neutral-400">
          <span>Fast & Creative</span>
          <span className="normal-case tracking-normal text-neutral-500">
            Balanced
          </span>
          <span>High Precision</span>
        </div>
      </div>
    </motion.div>
  );
}
