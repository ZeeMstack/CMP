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
 * commands/payloads/eligibility as before -- the only behavioral change is
 * command-identity stability: every command now mints its
 * `client_command_id` once per attempt (via the existing
 * `useFrozenSubmission` primitive, already used elsewhere in this codebase
 * for exactly this) and reuses it across a retry of the same payload,
 * rather than generating a fresh UUID on every click. */
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
  const [actionError, setActionError] = useState<string | null>(null);

  const startMutation = useStartWorkItem(farmId);
  const blockMutation = useBlockWorkItem(farmId);
  const unblockMutation = useUnblockWorkItem(farmId);
  const completeMutation = useCompleteWorkItem(farmId);

  const startCmd = useFrozenSubmission<FarmWorkItemStartIn>();
  const blockCmd = useFrozenSubmission<FarmWorkItemBlockIn>();
  const unblockCmd = useFrozenSubmission<FarmWorkItemUnblockIn>();
  const completeCmd = useFrozenSubmission<FarmWorkItemCompleteIn>();

  const isMine = currentUserId != null && item.assigned_to_user_id === currentUserId;
  const isAvailable = item.assigned_to_user_id == null;
  const canOperate = isMine || isAvailable;

  function reset() {
    setMode("idle");
    setReason("");
    setNote("");
    setActionError(null);
  }

  return (
    <>
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
                const payload = blockCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId, reason: reason.trim() }));
                blockMutation.mutate(
                  { workItemId: item.id, payload },
                  {
                    onSuccess: () => {
                      blockCmd.handleSuccess();
                      reset();
                    },
                    onError: (e) => {
                      blockCmd.handleError(toAppError(e));
                      setActionError(errorMessage(e));
                    },
                  },
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
              onClick={() => {
                const payload = completeCmd.submit((clientCommandId) => ({
                  client_command_id: clientCommandId,
                  completion_note: note.trim() || null,
                }));
                completeMutation.mutate(
                  { workItemId: item.id, payload },
                  {
                    onSuccess: () => {
                      completeCmd.handleSuccess();
                      reset();
                    },
                    onError: (e) => {
                      completeCmd.handleError(toAppError(e));
                      setActionError(errorMessage(e));
                    },
                  },
                );
              }}
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
              onClick={() => {
                const payload = startCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId }));
                startMutation.mutate(
                  { workItemId: item.id, payload },
                  {
                    onSuccess: () => startCmd.handleSuccess(),
                    onError: (e) => {
                      startCmd.handleError(toAppError(e));
                      setActionError(errorMessage(e));
                    },
                  },
                );
              }}
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
              onClick={() => {
                const payload = unblockCmd.submit((clientCommandId) => ({ client_command_id: clientCommandId }));
                unblockMutation.mutate(
                  { workItemId: item.id, payload },
                  {
                    onSuccess: () => unblockCmd.handleSuccess(),
                    onError: (e) => {
                      unblockCmd.handleError(toAppError(e));
                      setActionError(errorMessage(e));
                    },
                  },
                );
              }}
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
    </>
  );
}
