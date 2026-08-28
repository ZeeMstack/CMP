"use client";

import Link from "next/link";

import type { RecallCaseSummaryRead } from "@/lib/api/client";

/** Truncated + `font-mono` rather than a raw full uuid, matching the same
 * honest-until-resolved treatment used on the Recall Case detail page and
 * every other Batch F trace screen -- this list row has no cheap way to
 * resolve the id to a code without an extra fetch per row, so it stays
 * clearly-truncated rather than either a raw uuid or a fabricated label. */
function scopeSummary(recallCase: RecallCaseSummaryRead): string {
  if (recallCase.finished_goods_lot_id) return `Finished Goods Lot — ${recallCase.finished_goods_lot_id.slice(0, 8)}…`;
  if (recallCase.graded_produce_lot_id) return `Graded Produce Lot — ${recallCase.graded_produce_lot_id.slice(0, 8)}…`;
  if (recallCase.harvested_produce_lot_id) return `Harvested Produce Lot — ${recallCase.harvested_produce_lot_id.slice(0, 8)}…`;
  if (recallCase.crop_batch_id) return `Crop Batch — ${recallCase.crop_batch_id.slice(0, 8)}…`;
  return "—";
}

export function RecallCaseListItem({ recallCase, farmId }: { recallCase: RecallCaseSummaryRead; farmId: string }) {
  return (
    <li className="flex flex-col gap-1 rounded-xl border border-border-subtle bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={`/farms/${farmId}/processing/recall-cases/${recallCase.recall_case_id}`}
          className="font-serif text-sm font-semibold text-ink hover:underline"
        >
          {recallCase.code}
        </Link>
        <span
          className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium ${
            recallCase.is_open ? "bg-red-100 text-red-800" : "bg-surface-subtle text-ink-muted"
          }`}
        >
          {recallCase.is_open ? "Open" : "Closed"}
        </span>
      </div>
      <span className="text-xs text-ink-muted">{scopeSummary(recallCase)}</span>
      <span className="text-xs text-ink-muted">
        {recallCase.reason_code} — {recallCase.reason_text}
      </span>
      <span className="text-xs text-ink-muted">{new Date(recallCase.effective_time).toLocaleString()}</span>
    </li>
  );
}
