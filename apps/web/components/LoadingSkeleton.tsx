export function LoadingSkeleton({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="animate-pulse space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 rounded-md bg-surface-subtle" />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}
