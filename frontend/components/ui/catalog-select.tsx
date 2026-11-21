"use client";
import {
  Combobox,
  ComboboxButton,
  ComboboxInput,
  ComboboxOption,
  ComboboxOptions,
} from "@headlessui/react";
import { Check, ChevronDown, Search } from "lucide-react";
import { useId, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}
export function CatalogSelect({
  label,
  value,
  onChange,
  options,
  searchable = false,
  name,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  searchable?: boolean;
  name?: string;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const selected =
    options.find((option) => option.value === value) ?? options[0];
  const filtered = query
    ? options.filter((option) =>
        option.label.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : options;
  return (
    <div className="min-w-0">
      <label
        htmlFor={id}
        className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-300"
      >
        {label}
      </label>
      {name && <input type="hidden" name={name} value={value} />}
      <Combobox
        value={selected ?? null}
        onChange={(option) => {
          if (option) onChange(option.value);
        }}
        onClose={() => setQuery("")}
        immediate
      >
        <div className="relative">
          {searchable && (
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-neutral-500 dark:text-neutral-400" />
          )}
          <ComboboxInput
            id={id}
            aria-label={label}
            autoComplete="off"
            onFocus={(event) => {
              if (searchable) event.currentTarget.select();
            }}
            readOnly={!searchable}
            displayValue={(option: SelectOption | null) => option?.label ?? ""}
            onChange={(event) => setQuery(event.target.value)}
            className={`h-11 w-full rounded-xl border border-neutral-300 bg-white pr-11 text-base sm:text-sm text-neutral-900 outline-none transition focus:border-neutral-700 focus:ring-2 focus:ring-neutral-200 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:focus:border-neutral-400 dark:focus:ring-neutral-700 ${searchable ? "pl-9" : "pl-3"}`}
          />
          <ComboboxButton
            aria-label={`Open ${label.toLowerCase()}`}
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-xl text-neutral-500 dark:text-neutral-300"
          >
            <ChevronDown className="h-4 w-4" />
          </ComboboxButton>
        </div>
        <ComboboxOptions
          anchor="bottom start"
          transition
          className="z-40 mt-2 max-h-72 [--anchor-max-height:18rem] w-[var(--input-width)] min-w-48 overflow-y-auto rounded-xl border border-neutral-200 bg-white p-1.5 text-sm text-neutral-900 shadow-lg outline-none transition duration-100 data-closed:opacity-0 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
        >
          {filtered.map((option) => (
            <ComboboxOption
              key={option.value}
              value={option}
              className="group flex min-h-11 cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2.5 select-none data-focus:bg-neutral-100 data-selected:font-medium dark:data-focus:bg-neutral-800"
            >
              <span>{option.label}</span>
              <Check className="h-4 w-4 shrink-0 opacity-0 group-data-selected:opacity-100" />
            </ComboboxOption>
          ))}
          {!filtered.length && (
            <p className="px-3 py-4 text-neutral-500 dark:text-neutral-400">
              No matching categories.
            </p>
          )}
        </ComboboxOptions>
      </Combobox>
    </div>
  );
}
