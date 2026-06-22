export function ProductSkeleton() {
  return (
    <div className="animate-pulse">
      <div className="aspect-[3/4] rounded-2xl bg-neutral-200 dark:bg-neutral-800" />
      <div className="mt-3 space-y-2 px-1">
        <div className="h-4 w-3/4 rounded bg-neutral-200 dark:bg-neutral-800" />
        <div className="h-4 w-1/3 rounded bg-neutral-200 dark:bg-neutral-800" />
      </div>
    </div>
  );
}
