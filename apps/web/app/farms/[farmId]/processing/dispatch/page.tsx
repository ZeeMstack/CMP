"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";
import { DispatchForm } from "@/components/processing/DispatchForm";
import { DispatchHistoryPanel } from "@/components/processing/DispatchHistoryPanel";
import { DispatchSourcePanel } from "@/components/processing/DispatchSourcePanel";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import type { FinishedGoodsLotRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useDispatchEvents, useFinishedGoodsLots, useRecallCases, useRecordDispatch } from "@/lib/query/hooks";

const TABS = [
  { id: "dispatch", label: "Dispatch Finished Goods" },
  { id: "history", label: "Dispatch History" },
] as const;

function asAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-READY-001: the Dispatch workspace -- "Dispatch Finished Goods"
 * (default) and "Dispatch History" tabs, mirroring `processing/packing/
 * page.tsx`'s own established two-section shape exactly. Closes a
 * confirmed pilot blocker: the backend has always supported Dispatch, but
 * no frontend page existed to record one.
 *
 * PILOT-UX-003: an optional `?finishedGoodsLotId=` deep link (the handoff
 * from Cold Storage's "Prepare dispatch") preselects that Lot -- resolved
 * against this page's own scoped `useFinishedGoodsLots` read, never trusted
 * directly, mirroring ColdStoragePage's/PackingPage's identical
 * `?...Id=` handling exactly. */
export default function DispatchPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const contextLotId = searchParams.get("finishedGoodsLotId");

  const [tab, setTab] = useState<"dispatch" | "history">("dispatch");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [contextResolved, setContextResolved] = useState(!contextLotId);
  const [contextInvalid, setContextInvalid] = useState(false);
  const [recordError, setRecordError] = useState<AppError | null>(null);
  const [recordSuccess, setRecordSuccess] = useState<{ code: string; lotCodes: string[] } | null>(null);

  const lotsQuery = useFinishedGoodsLots(farmId);
  const recallCasesQuery = useRecallCases(farmId);
  const dispatchEventsQuery = useDispatchEvents(farmId);
  const recordMutation = useRecordDispatch(farmId);

  const allLots = lotsQuery.data ?? [];

  // Resolve the `?finishedGoodsLotId=` context exactly once, against this
  // page's own scoped read -- never before the list has actually loaded,
  // and never more than once, so a later refetch can't re-fire this and
  // silently swap the operator's already-selected sources.
  if (!contextResolved && !lotsQuery.isLoading && !lotsQuery.isError) {
    const match = allLots.find((l) => l.id === contextLotId);
    if (match) {
      setSelectedIds((ids) => (ids.includes(match.id) ? ids : [...ids, match.id]));
    } else {
      setContextInvalid(true);
    }
    setContextResolved(true);
  }

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

      <div className="mb-6">
        <Tabs
          tabs={TABS.map(({ id, label }) => ({ id, label }))}
          activeId={tab}
          onChange={(id) => setTab(id as "dispatch" | "history")}
          aria-label="Dispatch sections"
        />
      </div>

      {/* PILOT-UX-003: both tab panels stay mounted (toggled with `hidden`,
          never a conditional-render unmount) so switching to "Dispatch
          History" and back never wipes an in-progress Dispatch draft --
          mirrors PackingPage/GradingPage's identical `hidden` convention. */}
      <div hidden={tab !== "dispatch"} className="flex flex-col gap-4">
        {contextInvalid && (
          <p role="alert" className="rounded-md border border-wl-border-strong bg-wl-flag-bg p-3 text-sm text-wl-flag-fg">
            The requested Finished Goods Lot could not be found in this Farm. Select a Lot below.
          </p>
        )}
        {recordSuccess ? (
          <div className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
            <h2 className="font-serif text-base font-semibold text-wl-text">Dispatch recorded</h2>
            <p className="text-sm text-wl-text">
              <span className="font-medium">{recordSuccess.code}</span> dispatched from{" "}
              <span className="font-medium">{recordSuccess.lotCodes.join(", ")}</span>
            </p>
            <Button
              type="button"
              variant="primary"
              className="self-start"
              onClick={() => {
                setSelectedIds([]);
                setRecordSuccess(null);
                setRecordError(null);
              }}
            >
              Record another Dispatch
            </Button>
          </div>
        ) : (
          <>
            {selectedLots.length > 0 && (
              <DispatchForm
                farmId={farmId}
                lots={selectedLots}
                onRemoveLot={(lotId) => setSelectedIds((ids) => ids.filter((id) => id !== lotId))}
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

      <div hidden={tab !== "history"}>
        <DispatchHistoryPanel events={dispatchEventsQuery.data ?? []} isLoading={dispatchEventsQuery.isLoading} />
      </div>
    </div>
  );
}
