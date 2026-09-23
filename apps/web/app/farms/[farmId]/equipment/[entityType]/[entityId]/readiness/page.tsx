"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { READINESS_STATE_TONE } from "@/components/equipment/ReadinessInspector";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type {
  EquipmentReadinessNoteIn,
  EquipmentReadinessReportDamageIn,
  EquipmentReadinessRecordCleaningIn,
  EquipmentReadinessStateRead,
} from "@/lib/api/client";
import {
  computeAvailableReadinessActions,
  primaryReadinessAction,
  READINESS_ACTION_LABEL,
  type ReadinessAction,
} from "@/lib/format/equipmentReadinessActions";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useAssetReadiness,
  useCarrierReadiness,
  useEquipmentReadinessHistory,
  useMarkAwaitingCleaning,
  useMarkEquipmentReady,
  useRecordCleaning,
  useReportEquipmentDamage,
  useReturnFromMaintenance,
  useRetireEquipmentReadiness,
  useSendToMaintenance,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "text-xs font-medium text-wl-text-secondary";
const errorClass = "text-xs text-danger-700";

function nowDateTimeLocal(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** The current blocker/reason a floor operator needs to see alongside the
 * state badge -- never fabricated, only ever derived from the server-owned
 * facts this read already carries (ticket §7.5 "current blocker or
 * reason"). */
function currentBlocker(state: EquipmentReadinessStateRead): string | null {
  if (state.current_state === "retired") return "Retired — terminal. No further readiness actions are available.";
  if (state.current_state === "cleaning_completed" && state.latest_cleaning_result === "needs_rework") {
    return "Last cleaning result was Needs Rework — this must be re-cleaned before it can be marked Ready.";
  }
  if (state.entity_type === "carrier" && state.is_in_use) {
    return "This Carrier has an active Batch assignment — it cannot be marked Ready while in use.";
  }
  if (state.current_state === "damaged") return "Reported damaged.";
  if (state.current_state === "maintenance") return "In maintenance.";
  return state.state_note;
}

export default function EquipmentReadinessPage() {
  const { farmId, entityType, entityId } = useParams<{ farmId: string; entityType: string; entityId: string }>();
  const searchParams = useSearchParams();
  const requestedAction = searchParams.get("action");

  const isAsset = entityType === "asset";
  const assetQuery = useAssetReadiness(farmId, isAsset ? entityId : undefined);
  const carrierQuery = useCarrierReadiness(farmId, !isAsset ? entityId : undefined);
  const query = isAsset ? assetQuery : carrierQuery;
  const historyQuery = useEquipmentReadinessHistory(farmId, query.data?.id);

  if (entityType !== "asset" && entityType !== "carrier") {
    return <ErrorState error={new Error("Unknown equipment type in URL.")} />;
  }
  if (query.isLoading) return <LoadingSkeleton rows={5} label="Loading readiness" />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const state = query.data;
  if (!state) return null;

  const blocker = currentBlocker(state);

  return (
    <div>
      <PageHeader
        title={state.entity_code}
        description={state.equipment_type_name}
        compact
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: isAsset ? "Assets" : "Carriers", href: isAsset ? undefined : `/farms/${farmId}/carriers` },
              { label: "Readiness" },
            ]}
          />
        }
        actions={<StatusBadge label={humanizeEnumCode(state.current_state)} tone={READINESS_STATE_TONE[state.current_state]} />}
      />

      {blocker && (
        <div className="mb-4 rounded-lg border border-wl-border-strong bg-wl-flag-bg px-3.5 py-2.5 text-sm text-wl-flag-fg">
          {blocker}
        </div>
      )}

      <ReadinessActions farmId={farmId} state={state} initialAction={requestedAction as ReadinessAction | null} />

      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-wl-text-secondary">
          History
        </summary>
        <div className="mt-2">
          <ReadinessHistory
            loading={historyQuery.isLoading}
            error={historyQuery.error}
            entries={historyQuery.data ?? []}
            onRetry={() => historyQuery.refetch()}
          />
        </div>
      </details>
    </div>
  );
}

function ReadinessActions({
  farmId, state, initialAction,
}: {
  farmId: string;
  state: EquipmentReadinessStateRead;
  initialAction: ReadinessAction | null;
}) {
  const available = computeAvailableReadinessActions(state);
  const primary = primaryReadinessAction(state);
  const secondary = available.filter((a) => a !== primary);

  const [active, setActive] = useState<ReadinessAction | null>(
    initialAction && available.includes(initialAction) ? initialAction : null,
  );
  // UX-OPS-001B §7.5/§9: generated once per active command ATTEMPT and
  // reused across a retry of the same payload -- only `openAction` (a
  // genuinely new command selection) mints a new one; a failed submit's
  // own retry click never does.
  const [clientCommandId, setClientCommandId] = useState<string>(() => crypto.randomUUID());

  const markAwaitingCleaning = useMarkAwaitingCleaning(farmId);
  const recordCleaning = useRecordCleaning(farmId);
  const markReady = useMarkEquipmentReady(farmId);
  const reportDamage = useReportEquipmentDamage(farmId);
  const sendToMaintenance = useSendToMaintenance(farmId);
  const returnFromMaintenance = useReturnFromMaintenance(farmId);
  const retire = useRetireEquipmentReadiness(farmId);

  if (state.current_state === "retired") return null;

  function openAction(action: ReadinessAction) {
    setClientCommandId(crypto.randomUUID());
    setActive(action);
  }

  function close() {
    setActive(null);
  }

  const plainNoteMutations = {
    mark_awaiting_cleaning: markAwaitingCleaning,
    mark_ready: markReady,
    send_to_maintenance: sendToMaintenance,
    return_from_maintenance: returnFromMaintenance,
    retire: retire,
  } as const;

  if (available.length === 0) return null;

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      {!active ? (
        <div className="flex flex-wrap items-center gap-2">
          {primary && (
            <Button variant="primary" onClick={() => openAction(primary)}>
              {READINESS_ACTION_LABEL[primary]}
            </Button>
          )}
          {secondary.length > 0 && (
            <div className="flex flex-wrap gap-2 border-l border-wl-border pl-2">
              {secondary.map((action) => (
                <Button key={action} variant="secondary" onClick={() => openAction(action)}>
                  {READINESS_ACTION_LABEL[action]}
                </Button>
              ))}
            </div>
          )}
        </div>
      ) : active === "record_cleaning" ? (
        <RecordCleaningForm
          clientCommandId={clientCommandId}
          isSubmitting={recordCleaning.isPending}
          serverError={recordCleaning.error?.message}
          onCancel={close}
          onSubmit={(payload) => recordCleaning.mutate({ stateId: state.id, payload }, { onSuccess: close })}
        />
      ) : active === "report_damage" ? (
        <NoteForm
          required
          label="Damage description"
          confirmLabel={READINESS_ACTION_LABEL.report_damage}
          isSubmitting={reportDamage.isPending}
          serverError={reportDamage.error?.message}
          onCancel={close}
          onSubmit={(note) =>
            reportDamage.mutate(
              { stateId: state.id, payload: { client_command_id: clientCommandId, note } as EquipmentReadinessReportDamageIn },
              { onSuccess: close },
            )
          }
        />
      ) : (
        (() => {
          const mutation = plainNoteMutations[active];
          return (
            <NoteForm
              required={false}
              label="Note (optional)"
              confirmLabel={READINESS_ACTION_LABEL[active]}
              isSubmitting={mutation.isPending}
              serverError={mutation.error?.message}
              onCancel={close}
              onSubmit={(note) => {
                const payload: EquipmentReadinessNoteIn = { client_command_id: clientCommandId, note: note || undefined };
                mutation.mutate({ stateId: state.id, payload }, { onSuccess: close });
              }}
            />
          );
        })()
      )}
    </section>
  );
}

function RecordCleaningForm({
  clientCommandId, isSubmitting, serverError, onCancel, onSubmit,
}: {
  clientCommandId: string;
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (payload: EquipmentReadinessRecordCleaningIn) => void;
}) {
  const [effectiveAt, setEffectiveAt] = useState(nowDateTimeLocal());
  const [method, setMethod] = useState("");
  const [result, setResult] = useState<"completed" | "needs_rework">("completed");
  const [notes, setNotes] = useState("");

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Effective at</span>
          <input type="datetime-local" className={inputClass} value={effectiveAt} onChange={(e) => setEffectiveAt(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Method (optional)</span>
          <input type="text" className={inputClass} value={method} onChange={(e) => setMethod(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Result</span>
          <select className={inputClass} value={result} onChange={(e) => setResult(e.target.value as typeof result)}>
            <option value="completed">Completed</option>
            <option value="needs_rework">Needs Rework</option>
          </select>
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Notes (optional)</span>
        <textarea className={`${inputClass} min-h-16`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {result === "needs_rework" && (
        <p className="text-xs text-wl-text-secondary">
          A Needs Rework result still moves this item to Cleaning Completed for visibility — it does not return it to
          Awaiting Cleaning automatically, and it will block Mark Ready until re-cleaned.
        </p>
      )}
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={isSubmitting || !effectiveAt}
          onClick={() =>
            onSubmit({
              client_command_id: clientCommandId,
              effective_at: new Date(effectiveAt).toISOString(),
              method: method.trim() || undefined,
              result,
              notes: notes.trim() || undefined,
            })
          }
        >
          {isSubmitting ? "Saving…" : "Record Cleaning"}
        </Button>
      </div>
    </div>
  );
}

/** A single-field confirm panel (optional or required note) -- mirrors
 * crop-issues/[issueId]/page.tsx's `DiagnosisPanel`/`ResolveClosePanel`
 * shape rather than a full React Hook Form for one textarea. */
function NoteForm({
  required, label, confirmLabel, isSubmitting, serverError, onCancel, onSubmit,
}: {
  required: boolean;
  label: string;
  confirmLabel: string;
  isSubmitting: boolean;
  serverError?: string | null;
  onCancel: () => void;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1">
        <span className={labelClass}>{label}</span>
        <textarea className={`${inputClass} min-h-16`} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {serverError && <p role="alert" className={errorClass}>{serverError}</p>}
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={isSubmitting || (required && !note.trim())}
          onClick={() => onSubmit(note.trim())}
        >
          {isSubmitting ? "Saving…" : confirmLabel}
        </Button>
      </div>
    </div>
  );
}

function ReadinessHistory({
  loading, error, entries, onRetry,
}: {
  loading: boolean;
  error: unknown;
  entries: { id: string; action: string; effective_time: string }[];
  onRetry: () => void;
}) {
  if (loading) return <LoadingSkeleton rows={2} label="Loading history" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (entries.length === 0) return <p className="text-sm text-wl-text-secondary">No history yet.</p>;
  return (
    <BoundedDataRegion label="Readiness history">
      <ul className="divide-y divide-wl-border">
        {entries.map((entry) => (
          <li key={entry.id} className="flex items-center justify-between gap-3 px-3.5 py-2 text-sm">
            <span className="text-wl-text">{humanizeEnumCode(entry.action)}</span>
            <span className="text-xs text-wl-text-secondary">{new Date(entry.effective_time).toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </BoundedDataRegion>
  );
}
