"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { FarmWorkItemRead, ShiftHandoverRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useCreateShiftHandover } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-OPS-001 Shift Handover -- Pilot V1: a small, secondary banner
 * (never a KPI card) showing the most recent handover, plus a compact
 * "Leave a note" form. Never clones or closes the Work Items it
 * references -- open work stays open; this is a communication artifact
 * only (CLAUDE.md "Shift Handover"). */
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
  const [serverError, setServerError] = useState<string | null>(null);
  // UX-OPS-001B R1: minted once when composing starts (never inside
  // submit(), which runs again on every retry) and reused across a retry
  // of the same draft -- effective_time is captured at the same moment so
  // a failed-then-retried save reports honestly WHEN the note was
  // actually written, not when the retry happened to fire.
  const [draft, setDraft] = useState<{ clientCommandId: string; effectiveTime: string } | null>(null);
  const createMutation = useCreateShiftHandover(farmId);

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function startComposing() {
    setDraft({ clientCommandId: crypto.randomUUID(), effectiveTime: new Date().toISOString() });
    setComposing(true);
  }

  function submit() {
    if (!note.trim()) {
      setServerError("A note is required");
      return;
    }
    if (!draft) return;
    setServerError(null);
    createMutation.mutate(
      {
        client_command_id: draft.clientCommandId,
        effective_time: draft.effectiveTime,
        note: note.trim(),
        work_item_ids: Array.from(selectedIds),
      },
      {
        onSuccess: () => {
          setComposing(false);
          setNote("");
          setSelectedIds(new Set());
          setDraft(null);
        },
        onError: (e) => setServerError(errorMessage(e)),
      },
    );
  }

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
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="What should the next shift know?"
            className="min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 py-2 text-sm text-wl-text"
          />
          {openWorkItems.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-wl-text-secondary">Flag unresolved items (optional)</span>
              <div className="flex max-h-32 flex-col gap-1 overflow-y-auto rounded-md border border-wl-border bg-wl-surface-raised p-2">
                {openWorkItems.map((item) => (
                  <label key={item.id} className="flex items-center gap-2 text-sm text-wl-text">
                    <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggle(item.id)} className="h-4 w-4" />
                    {item.title} <span className="text-xs text-wl-text-secondary">({item.code})</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {serverError && <span className="text-xs text-danger-700">{serverError}</span>}
          <div className="flex gap-2">
            <Button variant="primary" disabled={createMutation.isPending} onClick={submit}>
              {createMutation.isPending ? "Saving…" : "Save handover"}
            </Button>
            <Button
              variant="secondary"
              disabled={createMutation.isPending}
              onClick={() => {
                setComposing(false);
                setServerError(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
