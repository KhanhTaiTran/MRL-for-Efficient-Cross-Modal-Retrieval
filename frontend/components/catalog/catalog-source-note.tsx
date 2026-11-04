"use client";

import { useEffect, useState } from "react";
import { fetchSearchConfig } from "components/aurafind/search-api";

export function CatalogSourceNote() {
  const [note, setNote] = useState("");
  useEffect(() => {
    let alive = true;
    fetchSearchConfig()
      .then((config) => {
        if (alive && config.catalog_source === "FashionGen") {
          setNote(
            `FashionGen · ${(config.num_products ?? 0).toLocaleString("en-US")} products · ${(config.num_vectors ?? 0).toLocaleString("en-US")} photos · Trained MRL. Prices and stock are simulated.`,
          );
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  if (!note) return null;
  return (
    <p className="border-b border-neutral-200 bg-neutral-50 px-5 py-3 text-center text-xs leading-5 text-neutral-600 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-300">
      {note}
    </p>
  );
}
