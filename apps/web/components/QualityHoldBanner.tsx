import Link from "next/link";

/** Shown on Batch Overview only when `open_quality_hold_count > 0` --
 * makes an open hold visible without opening the Quality tab. Uses the
 * existing StatusBadge "attention" tone palette (amber) for consistency. */
export function QualityHoldBanner({ count, href }: { count: number; href: string }) {
  if (count <= 0) return null;
  const label = count === 1 ? "1 open quality hold" : `${count} open quality holds`;

  return (
    <div
      role="status"
      className="mb-4 flex flex-col gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <p className="text-sm font-semibold text-amber-900">Quality hold</p>
        <p className="text-sm text-amber-800">This batch currently has {label}.</p>
      </div>
      <Link
        href={href}
        className="flex min-h-11 shrink-0 items-center justify-center rounded-md border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-600"
      >
        View quality details
      </Link>
    </div>
  );
}
