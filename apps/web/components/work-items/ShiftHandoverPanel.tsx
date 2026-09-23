"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useFrozenSubmission } from "@/lib/commands/frozenSubmission";
import type { FarmWorkItemRead, ShiftHandoverCreate, ShiftHandoverRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateShiftHandover, useInvalidateShiftHandovers } from "@/lib/query/hooks";

function toAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** PILOT-OPS-001 Shift Handover -- Pilot V1: a small, secondary banner
 * (never a KPI card) showing the most recent handover, plus a compact
 * "Leave a note" form. Never clones or closes the Work Items it
 * references -- open work stays open; this is a communication artifact
 * only (CLAUDE.md "Shift Handover").
 *
 * R2: command identity/payload freezing is owned entirely by
 * `useFrozenSubmission` -- `effective_time` is still captured once, at
 * `startComposing()` (never inside `submit()`, which can run again on
 * retry), but the note/selected-Work-Item-ids the operator had typed at
 * the moment of the FIRST Save are frozen together with it and
 * `client_command_id` as one payload. A retry after an uncertain outcome
 * (network/server error) resends that exact frozen payload -- note,
 * effective_time, and selected ids all included, never just the id/time
 * -- and the textarea/checklist become read-only while uncertain so nothing
 * can drift underneath an in-flight retry. Cancel always abandons the
 * attempt; if it was uncertain, an authoritative refetch of the latest
 * handover runs first. */
export function ShiftHandoverPanel({
  farmId,
  latest,
  openWorkItems,
}: {
  farmId: string;
  latest: ShiftHandoverRead | null | undefined;
  openWorkItems: FarmWorkItemRead[];
}) {
  const [composing, setComposing] = useState(false);
  const [note, setNote] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [validationError, setValidationError] = useState<string | null>(null);
  // Captured once when composing starts, never regenerated on retry --
  // see docstring above.
  const [effectiveTime, setEffectiveTime] = useState<string | null>(null);

  const createMutation = useCreateShiftHandover(farmId);
  const invalidateHandovers = useInvalidateShiftHandovers(farmId);
  const cmd = useFrozenSubmission<ShiftHandoverCreate>();

  const uncertain = cmd.outcome === "uncertain";

  function toggle(id: string) {
    if (uncertain) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function startComposing() {
    setEffectiveTime(new Date().toISOString());
    setComposing(true);
  }

  function closeCompose() {
    setComposing(false);
    setNote("");
    setSelectedIds(new Set());
    setValidationError(null);
    setEffectiveTime(null);
  }

  function submit() {
    if (uncertain) {
      const payload = cmd.retry();
      if (!payload) return;
      createMutation.mutate(payload, {
        onSuccess: () => { cmd.handleSuccess(); closeCompose(); },
        onError: (e) => cmd.handleError(toAppError(e)),
      });
      return;
    }
    if (!note.trim()) {
      setValidationError("A note is required");
      return;
    }
    if (!effectiveTime) return;
    setValidationError(null);
    const payload = cmd.submit((clientCommandId) => ({
      client_command_id: clientCommandId,
      effective_time: effectiveTime,
      note: note.trim(),
      work_item_ids: Array.from(selectedIds),
    }));
    createMutation.mutate(payload, {
      onSuccess: () => { cmd.handleSuccess(); closeCompose(); },
      onError: (e) => cmd.handleError(toAppError(e)),
    });
  }

  function cancel() {
    if (uncertain) invalidateHandovers();
    cmd.abandon();
    closeCompose();
  }

  const frozen = cmd.frozenPayload;
  const displayedNote = uncertain ? (frozen?.note ?? "") : note;
  const displayedIds = uncertain ? new Set(frozen?.work_item_ids ?? []) : selectedIds;

  return (
    <section className="mb-6 rounded-xl border border-wl-border bg-wl-surface-sunken p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-secondary">Latest shift handover</p>
          {latest ? (
            <>
              <p className="mt-0.5 text-sm text-wl-text">{latest.note}</p>
              <p className="mt-0.5 text-xs text-wl-text-secondary">
                {new Date(latest.effective_time).toLocaleString(undefined, {
                  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                })}
                {latest.work_item_ids.length > 0 && ` · ${latest.work_item_ids.length} item(s) flagged`}
              </p>
            </>
          ) : (
            <p className="mt-0.5 text-sm text-wl-text-secondary">No handover recorded yet.</p>
          )}
        </div>
        {!composing && (
          <Button variant="secondary" onClick={startComposing}>
            Leave a note
          </Button>
        )}
      </div>

      {composing && (
        <div className="mt-3 flex flex-col gap-2 border-t border-wl-border pt-3">
          <textarea
            autoFocus={!uncertain}
            value={displayedNote}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="What should the next shift know?"
            readOnly={uncertain}
            disabled={createMutation.isPending}
            className="min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 py-2 text-sm text-wl-text read-only:bg-wl-surface-sunken read-only:text-wl-text-secondary"
          />
          {openWorkItems.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-wl-text-secondary">Flag unresolved items (optional)</span>
              <div className="flex max-h-32 flex-col gap-1 overflow-y-auto rounded-md border border-wl-border bg-wl-surface-raised p-2">
                {openWorkItems.map((item) => (
                  <label key={item.id} className="flex items-center gap-2 text-sm text-wl-text">
                    <input
                      type="checkbox"
                      checked={displayedIds.has(item.id)}
                      onChange={() => toggle(item.id)}
                      disabled={uncertain}
                      className="h-4 w-4"
                    />
                    {item.title} <span className="text-xs text-wl-text-secondary">({item.code})</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {uncertain && (
            <span className="text-xs text-wl-text-secondary">
              No response yet -- Retry resends this exact note and flagged items.
            </span>
          )}
          {(validationError || cmd.error) && (
            <span className="text-xs text-danger-700">{validationError ?? cmd.error?.message}</span>
          )}
          <div className="flex gap-2">
            <Button variant="primary" disabled={createMutation.isPending} onClick={submit}>
              {createMutation.isPending ? "Saving…" : uncertain ? "Retry" : "Save handover"}
            </Button>
            <Button variant="secondary" disabled={createMutation.isPending} onClick={cancel}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
