"use client";

import type { RecallCaseSummaryRead } from "@/lib/api/client";

export type RecallScopeKind =
  | "harvested_produce_lot_id"
  | "graded_produce_lot_id"
  | "finished_goods_lot_id"
  | "crop_batch_id";

/** No lot carries its own recall flag (see `lib/api/client.ts`'s note) --
 * this is the one client-side join every Processing screen uses to answer
 * "is this specific Lot under an open Recall Case right now". */
export function findOpenRecallCase(
  cases: RecallCaseSummaryRead[] | undefined,
  kind: RecallScopeKind,
  id: string,
): RecallCaseSummaryRead | null {
  if (!cases) return null;
  return cases.find((c) => c.is_open && c[kind] === id) ?? null;
}

export function RecallBadge({ recallCase }: { recallCase: RecallCaseSummaryRead | null }) {
  if (!recallCase) return null;
  return (
    <span className="inline-flex w-fit items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
      Open recall — {recallCase.code}
    </span>
  );
}
