import Link from "next/link";

import type { SeedLotRead } from "@/lib/api/client";

export function SeedLotCard({ seedLot, farmId }: { seedLot: SeedLotRead; farmId: string }) {
  return (
    <Link
      href={`/farms/${farmId}/seed-lots/${seedLot.id}`}
      className="flex flex-col gap-1 rounded-xl border border-wl-border bg-wl-surface-raised p-4 transition-colors hover:border-wl-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
    >
      <p className="font-serif text-base font-semibold text-wl-text">{seedLot.code}</p>
      <p className="text-xs text-wl-text-secondary">
        {seedLot.crop.common_name} — {seedLot.variety.name}
      </p>
      {seedLot.supplier_name && <p className="text-xs text-wl-text-secondary">{seedLot.supplier_name}</p>}
    </Link>
  );
}
