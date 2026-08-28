import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { GreenhouseOverviewItem } from "@/lib/api/client";
import { classificationLabel, setupStatusLabel, structureSummaryLine } from "@/lib/format/greenhouseSummary";

const STATUS_TONE: Record<string, "neutral" | "attention" | "active"> = {
  empty: "neutral",
  partial: "attention",
  configured: "active",
};

export function GreenhouseOverviewCard({ item, farmId }: { item: GreenhouseOverviewItem; farmId: string }) {
  return (
    <Link
      href={`/farms/${farmId}/farm-setup/${item.greenhouse_id}`}
      className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-4 transition-colors hover:border-brand-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-serif text-base font-semibold text-ink">{item.code}</p>
          <p className="text-xs text-ink-muted">{item.name}</p>
        </div>
        <StatusBadge label={setupStatusLabel(item.status)} tone={STATUS_TONE[item.status] ?? "neutral"} />
      </div>
      <p className="text-xs font-medium text-ink-muted">{classificationLabel(item.classification)}</p>
      <p className="text-sm text-ink">{structureSummaryLine(item)}</p>
    </Link>
  );
}
