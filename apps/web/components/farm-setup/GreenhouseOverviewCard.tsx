import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { GreenhouseOverviewItem } from "@/lib/api/client";
import { classificationLabel, setupStatusLabel, structureSummaryLine } from "@/lib/format/greenhouseSummary";

const STATUS_TONE: Record<string, "neutral" | "attention" | "active"> = {
  empty: "neutral",
  partial: "attention",
  configured: "active",
};

/** Nursery structure rendered as a label/value list rather than one packed
 * horizontal metrics row -- the prior single-row layout overlapped at
 * narrow widths (release-blocking in the rejected A2 prototype). Only
 * dimensions that are actually part of a greenhouse's Nursery structure are
 * shown; Trolleys/Seeding Machines are farm-level equipment and are
 * intentionally excluded here (see structureSummaryLine). */
function NurseryStructureList({ counts }: { counts: GreenhouseOverviewItem["counts"] }) {
  const rows: { label: string; value: string }[] = [
    { label: "Seeding", value: counts.seeding_stations > 0 ? "Configured" : "Not configured" },
    { label: "Germination", value: counts.germination_chambers > 0 ? "Configured" : "Not configured" },
    { label: "Seedling", value: counts.seedling_tables > 0 ? `${counts.seedling_tables} tables` : "Not configured" },
    {
      label: "InterSalads",
      value: counts.intersalads_tables > 0 ? `${counts.intersalads_tables} tables` : "Not configured",
    },
    {
      label: "InterVines",
      value: counts.intervines_tables > 0 ? `${counts.intervines_tables} tables` : "Not configured",
    },
  ];

  return (
    <dl className="flex flex-col gap-1 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-3">
          <dt className="text-wl-text-secondary">{row.label}</dt>
          <dd className="font-medium text-wl-text">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function GreenhouseOverviewCard({ item, farmId }: { item: GreenhouseOverviewItem; farmId: string }) {
  return (
    <Link
      href={`/farms/${farmId}/farm-setup/${item.greenhouse_id}`}
      className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4 transition-colors hover:border-wl-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-sm font-medium text-wl-text">{item.code}</p>
          <p className="text-xs text-wl-text-secondary">{item.name}</p>
        </div>
        <StatusBadge label={setupStatusLabel(item.status)} tone={STATUS_TONE[item.status] ?? "neutral"} />
      </div>

      <p className="text-[11px] font-medium uppercase tracking-wide text-wl-text-tertiary">
        {classificationLabel(item.classification)}
      </p>

      {item.classification === "nursery" ? (
        <NurseryStructureList counts={item.counts} />
      ) : (
        <p className="text-sm text-wl-text">{structureSummaryLine(item)}</p>
      )}

      <span className="mt-1 inline-flex items-center gap-1 self-end text-xs font-medium text-wl-link">
        View
        <ArrowRight aria-hidden="true" className="h-3 w-3" />
      </span>
    </Link>
  );
}
