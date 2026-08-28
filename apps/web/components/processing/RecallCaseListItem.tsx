"use client";

import Link from "next/link";

import type { RecallCaseSummaryRead } from "@/lib/api/client";

function scopeSummary(recallCase: RecallCaseSummaryRead): string {
  if (recallCase.finished_goods_lot_id) return `Finished Goods Lot — ${recallCase.finished_goods_lot_id}`;
  if (recallCase.graded_produce_lot_id) return `Graded Produce Lot — ${recallCase.graded_produce_lot_id}`;
  if (recallCase.harvested_produce_lot_id) return `Harvested Produce Lot — ${recallCase.harvested_produce_lot_id}`;
  if (recallCase.crop_batch_id) return `Crop Batch — ${recallCase.crop_batch_id}`;
  return "—";
}

export function RecallCaseListItem({ recallCase, farmId }: { recallCase: RecallCaseSummaryRead; farmId: string }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={`/farms/${farmId}/processing/recall-cases/${recallCase.recall_case_id}`}
          className="text-sm font-semibold text-ink hover:underline"
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
