"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type {
  EquipmentReadinessCurrentState,
  EquipmentReadinessNoteIn,
  EquipmentReadinessReportDamageIn,
  EquipmentReadinessRecordCleaningIn,
  EquipmentReadinessStateRead,
} from "@/lib/api/client";
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

const STATE_TONE: Record<EquipmentReadinessCurrentState, StatusTone> = {
  unknown: "neutral",
  awaiting_cleaning: "attention",
  cleaning_completed: "attention",
  ready: "active",
  damaged: "critical",
  maintenance: "attention",
  retired: "closed",
};

/** PILOT-ASSET-001: only the commands valid from `current_state` are ever
 * shown -- the backend enforces this too (409 on an illegal transition),
 * but the UI never offers an illegal button. Mirrors the allowed-transitions
 * table in docs/domain/EQUIPMENT_READINESS_MODEL.md PART 6. */
type ReadinessAction =
  | "mark_awaiting_cleaning" | "record_cleaning" | "mark_ready" | "report_damage"
  | "send_to_maintenance" | "return_from_maintenance" | "retire";

const ACTIONS_BY_STATE: Record<EquipmentReadinessCurrentState, ReadinessAction[]> = {
  unknown: ["mark_awaiting_cleaning", "mark_ready", "report_damage", "send_to_maintenance", "retire"],
  awaiting_cleaning: ["record_cleaning", "report_damage", "send_to_maintenance", "retire"],
  cleaning_completed: ["mark_ready", "mark_awaiting_cleaning", "report_damage", "send_to_maintenance", "retire"],
  ready: ["mark_awaiting_cleaning", "report_damage", "send_to_maintenance", "retire"],
  damaged: ["send_to_maintenance", "retire"],
  maintenance: ["return_from_maintenance", "report_damage", "retire"],
  retired: [],
};

const ACTION_LABEL: Record<ReadinessAction, string> = {
  mark_awaiting_cleaning: "Mark Awaiting Cleaning",
  record_cleaning: "Record Cleaning",
  mark_ready: "Mark Ready",
  report_damage: "Report Damage",
  send_to_maintenance: "Send to Maintenance",
  return_from_maintenance: "Return from Maintenance",
  retire: "Retire",
};

function nowDateTimeLocal(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
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

  return (
    <div>
      <PageHeader
        title={isAsset ? "Asset Readiness" : "Carrier Readiness"}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: isAsset ? "Assets" : "Carriers", href: isAsset ? undefined : `/farms/${farmId}/carriers` },
              { label: "Readiness" },
            ]}
          />
        }
        actions={<StatusBadge label={humanizeEnumCode(state.current_state)} tone={STATE_TONE[state.current_state]} />}
      />

      <ReadinessContext state={state} />
      <ReadinessActions farmId={farmId} state={state} initialAction={requestedAction as ReadinessAction | null} />
      <ReadinessHistory
        loading={historyQuery.isLoading}
        error={historyQuery.error}
        entries={historyQuery.data ?? []}
        onRetry={() => historyQuery.refetch()}
      />
    </div>
  );
}

function ReadinessContext({ state }: { state: EquipmentReadinessStateRead }) {
  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-wl-text-secondary">State changed</dt>
          <dd className="text-sm text-wl-text">{new Date(state.state_changed_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Note</dt>
          <dd className="text-sm text-wl-text">{state.state_note ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Last cleaning event</dt>
          <dd className="text-sm text-wl-text">{state.last_cleaning_event_id ? "Recorded — see history below" : "None recorded"}</dd>
        </div>
      </dl>
    </section>
  );
}

function ReadinessActions({
  farmId, state, initialAction,
}: {
  farmId: string;
  state: EquipmentReadinessStateRead;
  initialAction: ReadinessAction | null;
}) {
  const available = ACTIONS_BY_STATE[state.current_state];
  const [active, setActive] = useState<ReadinessAction | null>(
    initialAction && available.includes(initialAction) ? initialAction : null,
  );

  const markAwaitingCleaning = useMarkAwaitingCleaning(farmId);
  const recordCleaning = useRecordCleaning(farmId);
  const markReady = useMarkEquipmentReady(farmId);
  const reportDamage = useReportEquipmentDamage(farmId);
  const sendToMaintenance = useSendToMaintenance(farmId);
  const returnFromMaintenance = useReturnFromMaintenance(farmId);
  const retire = useRetireEquipmentReadiness(farmId);

  if (state.current_state === "retired") {
    return (
      <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text-secondary">
        Retired — terminal. No further readiness actions are available.
      </section>
    );
  }

  function close() {
    setActive(null);
  }

  // Every command below except `record_cleaning`/`report_damage` shares the
  // exact same {client_command_id, note?} payload shape and
  // EquipmentReadinessStateRead return -- looked up by action name rather
  // than repeated per-branch chains (which would type as `string | false`,
  // not the `string | null | undefined` NoteForm's `serverError` expects).
  const plainNoteMutations = {
    mark_awaiting_cleaning: markAwaitingCleaning,
    mark_ready: markReady,
    send_to_maintenance: sendToMaintenance,
    return_from_maintenance: returnFromMaintenance,
    retire: retire,
  } as const;

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Actions</h2>
      {!active ? (
        <div className="flex flex-wrap gap-2">
          {available.map((action) => (
            <Button key={action} variant="secondary" onClick={() => setActive(action)}>
              {ACTION_LABEL[action]}
            </Button>
          ))}
        </div>
      ) : active === "record_cleaning" ? (
        <RecordCleaningForm
          isSubmitting={recordCleaning.isPending}
          serverError={recordCleaning.error?.message}
          onCancel={close}
          onSubmit={(payload) =>
            recordCleaning.mutate({ stateId: state.id, payload }, { onSuccess: close })
          }
        />
      ) : active === "report_damage" ? (
        <NoteForm
          required
          label="Damage description"
          confirmLabel={ACTION_LABEL.report_damage}
          isSubmitting={reportDamage.isPending}
          serverError={reportDamage.error?.message}
          onCancel={close}
          onSubmit={(note) =>
            reportDamage.mutate(
              { stateId: state.id, payload: { client_command_id: crypto.randomUUID(), note } as EquipmentReadinessReportDamageIn },
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
              confirmLabel={ACTION_LABEL[active]}
              isSubmitting={mutation.isPending}
              serverError={mutation.error?.message}
              onCancel={close}
              onSubmit={(note) => {
                const payload: EquipmentReadinessNoteIn = { client_command_id: crypto.randomUUID(), note: note || undefined };
                mutation.mutate({ stateId: state.id, payload }, { onSuccess: close });
              }}
            />
          );
        })()
      )}
    </section>
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

function RecordCleaningForm({
  isSubmitting, serverError, onCancel, onSubmit,
}: {
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
              client_command_id: crypto.randomUUID(),
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

function ReadinessHistory({
  loading, error, entries, onRetry,
}: {
  loading: boolean;
  error: unknown;
  entries: { id: string; action: string; effective_time: string }[];
  onRetry: () => void;
}) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">History</h2>
      {loading && <LoadingSkeleton rows={2} label="Loading history" />}
      {!loading && Boolean(error) && <ErrorState error={error} onRetry={onRetry} />}
      {!loading && !error && entries.length === 0 && <p className="text-sm text-wl-text-secondary">No history yet.</p>}
      {!loading && !error && entries.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="text-wl-text">{humanizeEnumCode(entry.action)}</span>
              <span className="text-xs text-wl-text-secondary">{new Date(entry.effective_time).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
