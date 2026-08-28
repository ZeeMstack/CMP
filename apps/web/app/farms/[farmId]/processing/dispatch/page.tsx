"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { DispatchForm } from "@/components/processing/DispatchForm";
import { DispatchHistoryPanel } from "@/components/processing/DispatchHistoryPanel";
import { DispatchSourcePanel } from "@/components/processing/DispatchSourcePanel";
import type { FinishedGoodsLotRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useDispatchEvents, useFinishedGoodsLots, useRecallCases, useRecordDispatch } from "@/lib/query/hooks";

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: the Dispatch workspace -- "Dispatch Finished Goods"
 * (default) and "Dispatch History" tabs, mirroring `processing/packing/
 * page.tsx`'s own established two-section shape exactly. Closes a
 * confirmed pilot blocker: the backend has always supported Dispatch, but
 * no frontend page existed to record one. */
export default function DispatchPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const [tab, setTab] = useState<"dispatch" | "history">("dispatch");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ code: string; lotCodes: string[] } | null>(null);

  const lotsQuery = useFinishedGoodsLots(farmId);
  const recallCasesQuery = useRecallCases(farmId);
  const dispatchEventsQuery = useDispatchEvents(farmId);
  const recordMutation = useRecordDispatch(farmId);

  const allLots = lotsQuery.data ?? [];
  const selectedLots: FinishedGoodsLotRead[] = selectedIds
    .map((id) => allLots.find((l) => l.id === id))
    .filter((l): l is FinishedGoodsLotRead => Boolean(l));

  return (
    <div>
      <PageHeader
        title="Dispatch"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Processing", href: `/farms/${farmId}/processing` },
              { label: "Dispatch" },
            ]}
          />
        }
      />

      <div className="mb-4 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("dispatch")}
          className={`min-h-11 rounded-md border px-4 text-sm font-medium ${
            tab === "dispatch" ? "border-brand-700 bg-brand-700 text-white" : "border-border-subtle text-ink hover:bg-surface-subtle"
          }`}
        >
          Dispatch Finished Goods
        </button>
        <button
          type="button"
          onClick={() => setTab("history")}
          className={`min-h-11 rounded-md border px-4 text-sm font-medium ${
            tab === "history" ? "border-brand-700 bg-brand-700 text-white" : "border-border-subtle text-ink hover:bg-surface-subtle"
          }`}
        >
          Dispatch History
        </button>
      </div>

      {tab === "dispatch" && (
        <div className="flex flex-col gap-4">
          {recordSuccess ? (
            <div className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface p-4">
              <h2 className="text-sm font-semibold text-ink">Dispatch recorded</h2>
              <p className="text-sm text-ink">
                <span className="font-medium">{recordSuccess.code}</span> dispatched from{" "}
                <span className="font-medium">{recordSuccess.lotCodes.join(", ")}</span>
              </p>
              <button
                type="button"
                onClick={() => {
                  setSelectedIds([]);
                  setRecordSuccess(null);
                  setRecordError(null);
                }}
                className="min-h-11 self-start rounded-md bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800"
              >
                Done
              </button>
            </div>
          ) : (
            <>
              {selectedLots.length > 0 && (
                <DispatchForm
                  key={selectedIds.join(",")}
                  farmId={farmId}
                  lots={selectedLots}
                  isSubmitting={recordMutation.isPending}
                  serverError={recordError}
                  onSubmit={(payload) => {
                    setRecordError(null);
                    recordMutation.mutate(payload, {
                      onSuccess: (result) => {
                        setRecordSuccess({
                          code: result.code,
                          lotCodes: result.lines.map((l) => l.finished_goods_lot_code),
                        });
                        setSelectedIds([]);
                      },
                      onError: (error) => setRecordError(asAppError(error)),
                    });
                  }}
                />
              )}
              <DispatchSourcePanel
                lots={allLots}
                farmId={farmId}
                recallCases={recallCasesQuery.data}
                selectedIds={selectedIds}
                isLoading={lotsQuery.isLoading}
                onAdd={(lot) => setSelectedIds((ids) => [...ids, lot.id])}
                onRemove={(lotId) => setSelectedIds((ids) => ids.filter((id) => id !== lotId))}
              />
            </>
          )}
        </div>
      )}

      {tab === "history" && (
        <DispatchHistoryPanel events={dispatchEventsQuery.data ?? []} isLoading={dispatchEventsQuery.isLoading} />
      )}
    </div>
  );
}
