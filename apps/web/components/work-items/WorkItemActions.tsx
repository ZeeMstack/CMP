"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useFrozenSubmission } from "@/lib/commands/frozenSubmission";
import type {
  FarmWorkItemBlockIn,
  FarmWorkItemCompleteIn,
  FarmWorkItemRead,
  FarmWorkItemStartIn,
  FarmWorkItemUnblockIn,
} from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import {
  useBlockWorkItem,
  useCompleteWorkItem,
  useInvalidateWorkItems,
  useStartWorkItem,
  useUnblockWorkItem,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function toAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** The Work Item action-button cluster, extracted from `WorkItemRow` so it
 * can be reused verbatim inside a narrow selected-item inspector (UX-OPS-
 * 001B R1) without embedding a six-column table row in a rail. Same
 * commands/payloads/eligibility as before -- command-identity is managed
 * by `useFrozenSubmission` per the frozen-payload contract (R2):
 *
 * - The first attempt mints a `client_command_id` and freezes the whole
 *   wire payload (`submit()`).
 * - A network/server error is "uncertain" -- the visible action re-labels
 *   to "Retry" and, when clicked, resends the exact frozen payload
 *   (`retry()`), never a payload rebuilt from current field values. The
 *   Block/Complete reason/note fields become read-only while uncertain, so
 *   a field can't be edited underneath an in-flight retry.
 * - A definitive rejection (validation/conflict/etc.) clears the frozen
 *   attempt (handled inside `useFrozenSubmission.handleError`) so the next
 *   submit mints a genuinely new id.
 * - Cancel out of the Block/Complete compose step always clears the
 *   attempt (`abandon()`); when the abandoned attempt was uncertain, an
 *   authoritative query refresh runs FIRST, so a command that actually
 *   succeeded server-side (slow response, lost ack) is reflected before
 *   the local attempt is discarded.
 * - Every command instance here is scoped to `item.id` by the CALLER:
 *   `WorkItemRow`/`WorkItemInspectorPanel` render this component with
 *   `key={item.id}`, so selecting a different Work Item remounts this
 *   component (and its four `useFrozenSubmission` instances) from
 *   scratch -- an uncertain attempt for one item can never leak its
 *   frozen id into another item's attempt. */
export function WorkItemActions({
  item, farmId, currentUserId,
}: {
  item: FarmWorkItemRead;
  farmId: string;
  currentUserId?: string;
}) {
  const [mode, setMode] = useState<"idle" | "blocking" | "completing">("idle");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const startMutation = useStartWorkItem(farmId);
  const blockMutation = useBlockWorkItem(farmId);
  const unblockMutation = useUnblockWorkItem(farmId);
  const completeMutation = useCompleteWorkItem(farmId);
  const invalidate = useInvalidateWorkItems(farmId);

  const startCmd = useFrozenSubmission<FarmWorkItemStartIn>();
  const blockCmd = useFrozenSubmission<FarmWorkItemBlockIn>();
  const unblockCmd = useFrozenSubmission<FarmWorkItemUnblockIn>();
  const completeCmd = useFrozenSubmission<FarmWorkItemCompleteIn>();

  const isMine = currentUserId != null && item.assigned_to_user_id === currentUserId;
  const isAvailable = item.assigned_to_user_id == null;
  const canOperate = isMine || isAvailable;

  function closeCompose() {
    setMode("idle");
    setReason("");
    setNote("");
    setValidationError(null);
  }

  function runStart() {
    if (startCmd.outcome === "uncertain") {
      const payload = startCmd.retry();
      if (!payload) return;
      startMutation.mutate(
        { workItemId: item.id, payload },
        { onSuccess: () => startCmd.handleSuccess(), onError: (e) => startCmd.handleError(toAppError(e)) },
      );
      return;
    }
    const payload = startCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId }));
    startMutation.mutate(
      { workItemId: item.id, payload },
      { onSuccess: () => startCmd.handleSuccess(), onError: (e) => startCmd.handleError(toAppError(e)) },
    );
  }

  function runUnblock() {
    if (unblockCmd.outcome === "uncertain") {
      const payload = unblockCmd.retry();
      if (!payload) return;
      unblockMutation.mutate(
        { workItemId: item.id, payload },
        { onSuccess: () => unblockCmd.handleSuccess(), onError: (e) => unblockCmd.handleError(toAppError(e)) },
      );
      return;
    }
    const payload = unblockCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId }));
    unblockMutation.mutate(
      { workItemId: item.id, payload },
      { onSuccess: () => unblockCmd.handleSuccess(), onError: (e) => unblockCmd.handleError(toAppError(e)) },
    );
  }

  function confirmBlock() {
    if (blockCmd.outcome === "uncertain") {
      const payload = blockCmd.retry();
      if (!payload) return;
      blockMutation.mutate(
        { workItemId: item.id, payload },
        {
          onSuccess: () => { blockCmd.handleSuccess(); closeCompose(); },
          onError: (e) => blockCmd.handleError(toAppError(e)),
        },
      );
      return;
    }
    if (!reason.trim()) {
      setValidationError("Reason is required");
      return;
    }
    setValidationError(null);
    const payload = blockCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId, reason: reason.trim() }));
    blockMutation.mutate(
      { workItemId: item.id, payload },
      {
        onSuccess: () => { blockCmd.handleSuccess(); closeCompose(); },
        onError: (e) => blockCmd.handleError(toAppError(e)),
      },
    );
  }

  function cancelBlock() {
    if (blockCmd.outcome === "uncertain") invalidate(item.id);
    blockCmd.abandon();
    closeCompose();
  }

  function confirmComplete() {
    if (completeCmd.outcome === "uncertain") {
      const payload = completeCmd.retry();
      if (!payload) return;
      completeMutation.mutate(
        { workItemId: item.id, payload },
        {
          onSuccess: () => { completeCmd.handleSuccess(); closeCompose(); },
          onError: (e) => completeCmd.handleError(toAppError(e)),
        },
      );
      return;
    }
    const payload = completeCmd.submit((clientCommandId) => ({
      client_command_id: clientCommandId,
      completion_note: note.trim() || null,
    }));
    completeMutation.mutate(
      { workItemId: item.id, payload },
      {
        onSuccess: () => { completeCmd.handleSuccess(); closeCompose(); },
        onError: (e) => completeCmd.handleError(toAppError(e)),
      },
    );
  }

  function cancelComplete() {
    if (completeCmd.outcome === "uncertain") invalidate(item.id);
    completeCmd.abandon();
    closeCompose();
  }

  const blockUncertain = blockCmd.outcome === "uncertain";
  const completeUncertain = completeCmd.outcome === "uncertain";

  return (
    <>
      {mode === "blocking" ? (
        <div className="flex min-w-[220px] flex-col gap-1.5">
          <input
            autoFocus={!blockUncertain}
            value={blockUncertain ? (blockCmd.frozenPayload?.reason ?? "") : reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (required)"
            readOnly={blockUncertain}
            disabled={blockMutation.isPending}
            className="min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text read-only:bg-wl-surface-sunken read-only:text-wl-text-secondary"
          />
          {blockUncertain && (
            <span className="text-xs text-wl-text-secondary">
              No response yet -- Retry resends this exact reason.
            </span>
          )}
          {(validationError || blockCmd.error) && (
            <span className="text-xs text-danger-700">{validationError ?? blockCmd.error?.message}</span>
          )}
          <div className="flex gap-1.5">
            <Button variant="primary" disabled={blockMutation.isPending} onClick={confirmBlock}>
              {blockUncertain ? "Retry" : "Confirm"}
            </Button>
            <Button variant="secondary" onClick={cancelBlock} disabled={blockMutation.isPending}>
              Cancel
            </Button>
          </div>
        </div>
      ) : mode === "completing" ? (
        <div className="flex min-w-[220px] flex-col gap-1.5">
          <input
            autoFocus={!completeUncertain}
            value={completeUncertain ? (completeCmd.frozenPayload?.completion_note ?? "") : note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional)"
            readOnly={completeUncertain}
            disabled={completeMutation.isPending}
            className="min-h-9 rounded-md border border-wl-border bg-wl-surface-raised px-2 text-sm text-wl-text read-only:bg-wl-surface-sunken read-only:text-wl-text-secondary"
          />
          {completeUncertain && (
            <span className="text-xs text-wl-text-secondary">
              No response yet -- Retry resends this exact note.
            </span>
          )}
          {completeCmd.error && <span className="text-xs text-danger-700">{completeCmd.error.message}</span>}
          <div className="flex gap-1.5">
            <Button variant="primary" disabled={completeMutation.isPending} onClick={confirmComplete}>
              {completeUncertain ? "Retry" : "Confirm"}
            </Button>
            <Button variant="secondary" onClick={cancelComplete} disabled={completeMutation.isPending}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          {item.status === "open" && canOperate && (
            <Button disabled={startMutation.isPending} onClick={runStart}>
              {startCmd.outcome === "uncertain" ? "Retry" : "Start"}
            </Button>
          )}
          {(item.status === "open" || item.status === "in_progress") && (
            <Button variant="secondary" onClick={() => setMode("blocking")}>
              Block
            </Button>
          )}
          {item.status === "blocked" && (
            <Button disabled={unblockMutation.isPending} onClick={runUnblock}>
              {unblockCmd.outcome === "uncertain" ? "Retry" : "Resume"}
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
          {(startCmd.error || unblockCmd.error) && (
            <span className="text-xs text-danger-700">{errorMessage(startCmd.error ?? unblockCmd.error)}</span>
          )}
        </div>
      )}
    </>
  );
}
