"use client";

import Link from "next/link";
import { useState } from "react";

import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { tableRowHoverClass, tableTdClass } from "@/components/ui/table";
import type { FarmWorkItemRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useBlockWorkItem,
  useCompleteWorkItem,
  useStartWorkItem,
  useUnblockWorkItem,
} from "@/lib/query/hooks";

const STATUS_TONE: Record<FarmWorkItemRead["status"], StatusTone> = {
  open: "neutral",
  in_progress: "active",
  blocked: "attention",
  completed: "closed",
  cancelled: "closed",
};

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function formatDue(dueAt: string | null): string {
  if (!dueAt) return "—";
  return new Date(dueAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** WHAT/WHERE/CONTEXT/OWNER/WHEN/STATUS/NEXT ACTION, one compact row --
 * every piece of context already resolved server-side (`FarmWorkItemRead`'s
 * nested summaries), never a second lookup by this component. */
export function WorkItemRow({ item, farmId, currentUserId }: { item: FarmWorkItemRead; farmId: string; currentUserId?: string }) {
  const [mode, setMode] = useState<"idle" | "blocking" | "completing">("idle");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const startMutation = useStartWorkItem(farmId);
  const blockMutation = useBlockWorkItem(farmId);
  const unblockMutation = useUnblockWorkItem(farmId);
  const completeMutation = useCompleteWorkItem(farmId);

  const isMine = currentUserId != null && item.assigned_to_user_id === currentUserId;
  const isAvailable = item.assigned_to_user_id == null;
  const canOperate = isMine || isAvailable;

  const quantity = item.quantity && item.quantity_uom ? `${item.quantity} ${item.quantity_uom.code}` : null;
  // PILOT-OPS-001 closure: every structured context piece the Work Item
  // actually carries is shown, never just the first one -- e.g. a Batch
  // AND a Location together (ticket example: "Check Batch B-... after
  // transfer"). A context kind that doesn't apply renders no placeholder
  // at all, never an empty "—" line for it specifically.
  const hasContext = Boolean(item.crop_batch || item.location || item.asset || item.carrier || quantity);

  function reset() {
    setMode("idle");
    setReason("");
    setNote("");
    setActionError(null);
  }

  return (
    <tr className={tableRowHoverClass}>
      <td className={`${tableTdClass} font-medium text-wl-text`}>
        {item.title}
        <div className="text-xs font-normal text-wl-text-secondary">{item.code}</div>
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>
        {item.crop_batch && <div>Batch {item.crop_batch.code}</div>}
        {item.location && (
          <div className={item.crop_batch ? "text-xs" : undefined}>
            {item.location.code} {item.location.name}
          </div>
        )}
        {item.asset && <div className="text-xs">{item.asset.name}</div>}
        {item.carrier && <div className="text-xs">{item.carrier.code}</div>}
        {quantity && <div className="text-xs">{quantity}</div>}
        {!hasContext && "—"}
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>
        {isMine ? "You" : item.assigned_to_user_id ? "Assigned" : "Unassigned"}
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>{formatDue(item.due_at)}</td>
      <td className={tableTdClass}>
        <div className="flex flex-col gap-1">
          <StatusBadge label={humanizeEnumCode(item.status)} tone={STATUS_TONE[item.status]} />
          {item.priority !== "normal" && (
            <StatusBadge label={humanizeEnumCode(item.priority)} tone={item.priority === "critical" ? "critical" : "attention"} />
          )}
        </div>
        {item.status === "blocked" && item.blocked_reason && (
          <p className="mt-1 max-w-[22ch] text-xs text-wl-hold-fg">{item.blocked_reason}</p>
        )}
      </td>
      <td className={tableTdClass}>
        {mode === "blocking" ? (
          <div className="flex min-w-[220px] flex-col gap-1.5">
            <input
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (required)"
              className="min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text"
            />
            {actionError && <span className="text-xs text-danger-700">{actionError}</span>}
            <div className="flex gap-1.5">
              <Button
                variant="primary"
                disabled={blockMutation.isPending}
                onClick={() => {
                  if (!reason.trim()) {
                    setActionError("Reason is required");
                    return;
                  }
                  blockMutation.mutate(
                    { workItemId: item.id, payload: { client_command_id: crypto.randomUUID(), reason: reason.trim() } },
                    { onSuccess: reset, onError: (e) => setActionError(errorMessage(e)) },
                  );
                }}
              >
                Confirm
              </Button>
              <Button variant="secondary" onClick={reset} disabled={blockMutation.isPending}>
                Cancel
              </Button>
            </div>
          </div>
        ) : mode === "completing" ? (
          <div className="flex min-w-[220px] flex-col gap-1.5">
            <input
              autoFocus
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note (optional)"
              className="min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text"
            />
            {actionError && <span className="text-xs text-danger-700">{actionError}</span>}
            <div className="flex gap-1.5">
              <Button
                variant="primary"
                disabled={completeMutation.isPending}
                onClick={() =>
                  completeMutation.mutate(
                    {
                      workItemId: item.id,
                      payload: { client_command_id: crypto.randomUUID(), completion_note: note.trim() || null },
                    },
                    { onSuccess: reset, onError: (e) => setActionError(errorMessage(e)) },
                  )
                }
              >
                Confirm
              </Button>
              <Button variant="secondary" onClick={reset} disabled={completeMutation.isPending}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {item.status === "open" && canOperate && (
              <Button
                disabled={startMutation.isPending}
                onClick={() =>
                  startMutation.mutate(
                    { workItemId: item.id, payload: { client_command_id: crypto.randomUUID() } },
                    { onError: (e) => setActionError(errorMessage(e)) },
                  )
                }
              >
                Start
              </Button>
            )}
            {(item.status === "open" || item.status === "in_progress") && (
              <Button variant="secondary" onClick={() => setMode("blocking")}>
                Block
              </Button>
            )}
            {item.status === "blocked" && (
              <Button
                disabled={unblockMutation.isPending}
                onClick={() =>
                  unblockMutation.mutate(
                    { workItemId: item.id, payload: { client_command_id: crypto.randomUUID() } },
                    { onError: (e) => setActionError(errorMessage(e)) },
                  )
                }
              >
                Resume
              </Button>
            )}
            {item.status !== "blocked" &&
              item.completion_mode === "manual_record" &&
              (item.status === "open" || item.status === "in_progress") && (
                <Button variant="secondary" onClick={() => setMode("completing")}>
                  Complete
                </Button>
              )}
            {item.completion_mode === "operational_record" &&
              item.work_type === "observation" &&
              item.crop_batch && (
                <Link
                  href={`/farms/${farmId}/observations?batchId=${item.crop_batch.id}&workItemId=${item.id}`}
                  className="text-sm font-medium text-wl-brand hover:underline"
                >
                  Open Observation
                </Link>
              )}
            {/* PILOT-OPS-001 closure: routes to the real Leafy Harvest
                operator UI only -- Vines Harvest is wired on the backend
                but a Work Item carries no crop-classification signal to
                safely route Leafy vs. Vines, so it is not linked from
                here (see docs/domain/FARM_WORK_ITEM_MODEL.md). */}
            {item.completion_mode === "operational_record" &&
              item.work_type === "harvest" &&
              item.crop_batch && (
                <Link
                  href={`/farms/${farmId}/leafy-production/harvest?batchId=${item.crop_batch.id}&workItemId=${item.id}`}
                  className="text-sm font-medium text-wl-brand hover:underline"
                >
                  Open Harvest
                </Link>
              )}
            {actionError && <span className="text-xs text-danger-700">{actionError}</span>}
          </div>
        )}
      </td>
    </tr>
  );
}
