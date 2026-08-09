"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import type { FarmRead } from "@/lib/api/client";

/** Preserves the current logical destination (Home/Locations/Batches) when
 * switching farms; falls back to the target farm's home for anything more
 * specific (e.g. a batch-detail page, since that batch won't exist in
 * another farm). */
function destinationSuffix(pathname: string, currentFarmId: string): string {
  const prefix = `/farms/${currentFarmId}`;
  const rest = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : "";
  if (rest === "/locations") return "/locations";
  if (rest === "/crop-batches") return "/crop-batches";
  return "";
}

export function FarmSelector({ farms, currentFarmId }: { farms: FarmRead[]; currentFarmId: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const current = farms.find((f) => f.id === currentFarmId);

  if (farms.length <= 1) {
    return <span className="truncate text-sm font-medium text-ink">{current?.name ?? "…"}</span>;
  }

  const suffix = destinationSuffix(pathname, currentFarmId);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex min-h-11 items-center gap-1 rounded-md px-2 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
      >
        <span className="truncate">{current?.name ?? "Select farm"}</span>
        <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0" />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Farms"
          className="absolute left-0 z-10 mt-1 min-w-48 rounded-md border border-border-subtle bg-surface py-1 shadow-lg"
        >
          {farms.map((farm) => (
            <li key={farm.id} role="option" aria-selected={farm.id === currentFarmId}>
              <Link
                href={`/farms/${farm.id}${farm.id === currentFarmId ? "" : suffix}`}
                onClick={() => setOpen(false)}
                className={`block min-h-11 px-3 py-2 text-sm hover:bg-surface-subtle ${
                  farm.id === currentFarmId ? "font-medium text-brand-700" : "text-ink"
                }`}
              >
                {farm.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
