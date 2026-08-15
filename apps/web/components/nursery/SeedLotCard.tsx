import Link from "next/link";

import type { SeedLotRead } from "@/lib/api/client";

export function SeedLotCard({ seedLot, farmId }: { seedLot: SeedLotRead; farmId: string }) {
  return (
    <Link
      href={`/farms/${farmId}/seed-lots/${seedLot.id}`}
      className="flex flex-col gap-1 rounded-lg border border-border-subtle bg-surface p-4 hover:border-brand-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
    >
      <p className="text-sm font-semibold text-ink">{seedLot.code}</p>
      <p className="text-xs text-ink-muted">
        {seedLot.crop.common_name} — {seedLot.variety.name}
      </p>
      {seedLot.supplier_name && <p className="text-xs text-ink-muted">{seedLot.supplier_name}</p>}
    </Link>
  );
}
