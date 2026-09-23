"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { Button } from "@/components/ui/Button";
import { CreateWorkItemForm } from "@/components/work-items/CreateWorkItemForm";
import { WorkItemRow } from "@/components/work-items/WorkItemRow";
import type {
  CropIssueCloseIn,
  CropIssueConfirmDiagnosisIn,
  CropIssueFollowUpIn,
  CropIssueRead,
  CropIssueResolveIn,
  FarmWorkItemRead,
} from "@/lib/api/client";
import { useFrozenSubmission } from "@/lib/commands/frozenSubmission";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useConfirmCropIssueDiagnosis,
  useCropBatch,
  useCropIssue,
  useCropIssueFollowUps,
  useCloseCropIssue,
  useGrowerInspection,
  useRecordCropIssueFollowUp,
  useResolveCropIssue,
} from "@/lib/query/hooks";

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "text-xs font-medium text-wl-text-secondary";

const STATUS_TONE: Record<string, StatusTone> = { open: "attention", resolved: "active", closed: "closed" };
const FOLLOW_UP_OUTCOMES = ["improved", "unchanged", "worsened", "resolved"] as const;

type IssueAction = "diagnose" | "follow_up" | "resolve" | "close";

/** PILOT-AGRO-001B Part 4: the Crop Issue workspace -- Batch, placement
 * snapshot, originating Inspection, suspected cause vs. confirmed
 * diagnosis (kept visually distinct, never auto-copied), status, corrective
 * work, and follow-up history. Actions are shown deliberately per status
 * (OPEN -> RESOLVED -> CLOSED, never a direct OPEN -> CLOSED, never one
 * generic "Update Issue" form) -- this codebase has no frontend permission
 * hook anywhere (confirmed against `AppShell.tsx`'s single `tenant_admin`
 * nav-only exception), so an unauthorized click is caught by the backend's
 * own 403 and surfaced as a friendly error, exactly like every other
 * command in this app.
 *
 * UX-OPS-001C: context, diagnosis, corrective work, and follow-up history
 * in the main area; a sticky Status rail offers exactly one primary action
 * for the persisted status (Open -> Resolve, Resolved -> Close, Closed ->
 * none) plus the Open-only secondary actions (Confirm Diagnosis, Add
 * Follow-up), each opening its own compact command form in the rail. Every
 * command's `client_command_id` is now frozen per attempt: an uncertain
 * (network/5xx) outcome is retried with the same id and exact payload --
 * the backend replays it -- instead of a fresh id per click, which could
 * duplicate a follow-up. */
export default function CropIssueWorkspacePage() {
  const { farmId, issueId } = useParams<{ farmId: string; issueId: string }>();
  const issueQuery = useCropIssue(farmId, issueId);
  const followUpsQuery = useCropIssueFollowUps(farmId, issueId);
  const [activeAction, setActiveAction] = useState<IssueAction | null>(null);
  const [lastOutcomeResolved, setLastOutcomeResolved] = useState(false);

  if (issueQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading crop issue" />;
  if (issueQuery.error) return <ErrorState error={issueQuery.error} onRetry={() => issueQuery.refetch()} />;
  const issue = issueQuery.data;
  if (!issue) return null;

  const followUps = followUpsQuery.data ?? [];

  return (
    <div>
      <PageHeader
        compact
        title={issue.code}
        description={issue.description}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: "Crop Issue" },
            ]}
          />
        }
        actions={<StatusBadge label={humanizeEnumCode(issue.status)} tone={STATUS_TONE[issue.status]} />}
      />

      <SplitWorkspace
        main={
          <div className="flex flex-col gap-4">
            <IssueContext farmId={farmId} issue={issue} />
            <DiagnosisFacts issue={issue} />
            <CorrectiveWorkPanel farmId={farmId} issue={issue} />
            <section>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Follow-up history</h2>
              {followUpsQuery.isLoading && <LoadingSkeleton rows={2} label="Loading follow-ups" />}
              {followUpsQuery.isError && (
                <ErrorState error={followUpsQuery.error} onRetry={() => followUpsQuery.refetch()} />
              )}
              {followUpsQuery.isSuccess && followUps.length === 0 && (
                <p className="text-sm text-wl-text-secondary">No follow-up recorded yet.</p>
              )}
              {followUps.length > 0 && (
                <BoundedDataRegion label="Follow-up history">
                  <ul className="divide-y divide-wl-border bg-wl-surface-raised">
                    {followUps.map((f) => (
                      <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
                        <span className="font-medium text-wl-text">{humanizeEnumCode(f.outcome)}</span>
                        <span className="text-wl-text-secondary">{f.notes ?? "—"}</span>
                        <span className="text-xs text-wl-text-secondary">{new Date(f.recorded_at).toLocaleString()}</span>
                      </li>
                    ))}
                  </ul>
                </BoundedDataRegion>
              )}
            </section>
          </div>
        }
        rail={
          <IssueStatusRail
            farmId={farmId}
            issue={issue}
            activeAction={activeAction}
            onOpenAction={setActiveAction}
            // Every close (success, or Cancel of a never-sent draft)
            // re-reads authoritative Issue/follow-up state. An uncertain
            // attempt cannot close at all -- its Cancel is disabled.
            onCloseAction={() => {
              setActiveAction(null);
              issueQuery.refetch();
              followUpsQuery.refetch();
            }}
            lastOutcomeResolved={lastOutcomeResolved}
            onFollowUpRecorded={(outcome) => setLastOutcomeResolved(outcome === "resolved")}
          />
        }
      />
    </div>
  );
}

function toAppError(error: unknown): AppError {
  return error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again.");
}

/** One frozen command attempt for one Issue action: the first `run` mints a
 * `client_command_id`; while the outcome is uncertain, `run` resends the
 * byte-identical frozen payload (never re-derived from the live fields);
 * success or a definitive rejection releases it so the next attempt is a
 * genuinely new command. `cancel` is only offered while nothing is frozen
 * (see `CommandButtons`) -- an uncertain attempt is never abandoned. */
function useIssueCommand<T extends Record<string, unknown>>(
  send: (payload: T, handlers: { onSuccess: () => void; onError: (error: unknown) => void }) => void,
  onDone: () => void,
) {
  const frozen = useFrozenSubmission<T>();
  function dispatch(payload: T) {
    send(payload, {
      onSuccess: () => {
        frozen.handleSuccess();
        onDone();
      },
      onError: (error) => frozen.handleError(toAppError(error)),
    });
  }
  return {
    outcome: frozen.outcome,
    error: frozen.error,
    locked: frozen.outcome !== "editing",
    run(build: (clientCommandId: string) => T) {
      if (frozen.outcome === "uncertain") {
        const payload = frozen.retry();
        if (payload) dispatch(payload);
        return;
      }
      dispatch(frozen.submit(build));
    },
    cancel: frozen.abandon,
  };
}

function IssueContext({ farmId, issue }: { farmId: string; issue: CropIssueRead }) {
  const batchQuery = useCropBatch(farmId, issue.batch_id);
  const inspectionQuery = useGrowerInspection(farmId, issue.batch_id, issue.originating_grower_inspection_id);
  const batch = batchQuery.data;
  const inspection = inspectionQuery.data;
  const originatingFinding = inspection?.findings.find((f) => f.id === issue.originating_finding_id);

  return (
    <section className="rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-wl-text-secondary">Batch</dt>
          <dd className="text-sm text-wl-text">{batch ? batch.code : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Category / Severity</dt>
          <dd className="text-sm text-wl-text">
            {humanizeEnumCode(issue.category)} · {humanizeEnumCode(issue.severity)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Originating inspection</dt>
          <dd className="text-sm text-wl-text">
            {inspection ? new Date(inspection.effective_time).toLocaleString() : "—"}
            {originatingFinding && ` · ${humanizeEnumCode(originatingFinding.category)}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Affected / inspected</dt>
          <dd className="text-sm text-wl-text">
            {originatingFinding?.affected_count ?? "—"} / {inspection?.inspected_count ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Opened</dt>
          <dd className="text-sm text-wl-text">{new Date(issue.opened_at).toLocaleString()}</dd>
        </div>
        {issue.follow_up_due_at && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Follow-up due</dt>
            <dd className="text-sm text-wl-text">{new Date(issue.follow_up_due_at).toLocaleString()}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

/** Suspected cause vs. confirmed diagnosis -- two permanently distinct
 * facts, shown side by side, never auto-copied. Read-only here; the
 * Confirm Diagnosis command lives in the Status rail. */
function DiagnosisFacts({ issue }: { issue: CropIssueRead }) {
  return (
    <section className="grid grid-cols-1 gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
      <div>
        <h2 className="mb-1 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Suspected cause</h2>
        <p className="text-sm text-wl-text">{issue.suspected_cause ?? "Not recorded"}</p>
      </div>
      <div>
        <h2 className="mb-1 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Confirmed diagnosis</h2>
        <p className={`text-sm ${issue.confirmed_diagnosis ? "text-wl-text" : "text-wl-text-secondary"}`}>
          {issue.confirmed_diagnosis ?? "Not confirmed"}
        </p>
      </div>
    </section>
  );
}

function IssueStatusRail({
  farmId,
  issue,
  activeAction,
  onOpenAction,
  onCloseAction,
  lastOutcomeResolved,
  onFollowUpRecorded,
}: {
  farmId: string;
  issue: CropIssueRead;
  activeAction: IssueAction | null;
  onOpenAction: (action: IssueAction) => void;
  onCloseAction: () => void;
  lastOutcomeResolved: boolean;
  onFollowUpRecorded: (outcome: (typeof FOLLOW_UP_OUTCOMES)[number]) => void;
}) {
  // Valid actions come only from the persisted status (plus whether a
  // diagnosis is already confirmed) -- never a direct Open -> Close.
  const primary: { action: IssueAction; label: string } | null =
    issue.status === "open"
      ? { action: "resolve", label: "Resolve Issue" }
      : issue.status === "resolved"
        ? { action: "close", label: "Close Issue" }
        : null;
  const secondary: { action: IssueAction; label: string }[] =
    issue.status === "open"
      ? [
          ...(issue.confirmed_diagnosis ? [] : [{ action: "diagnose" as const, label: "Confirm Diagnosis" }]),
          { action: "follow_up" as const, label: "Add Follow-up" },
        ]
      : [];

  return (
    <section aria-label="Issue status" className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-wl-text">Status</h2>
        <StatusBadge label={humanizeEnumCode(issue.status)} tone={STATUS_TONE[issue.status]} />
      </div>
      {(issue.has_open_work_item || issue.is_follow_up_overdue) && (
        <ul className="flex flex-col gap-1 text-xs">
          {issue.has_open_work_item && <li className="text-wl-text-secondary">This issue has an open corrective Work Item.</li>}
          {issue.is_follow_up_overdue && <li className="text-wl-flag-fg">Follow-up is overdue.</li>}
        </ul>
      )}
      {issue.status === "resolved" && (
        <p className="text-sm text-wl-text-secondary">
          Resolved {issue.resolved_at ? new Date(issue.resolved_at).toLocaleString() : ""}
          {issue.resolution_note && ` — ${issue.resolution_note}`}
        </p>
      )}
      {issue.status === "closed" && (
        <p className="text-sm text-wl-text-secondary">
          Closed {issue.closed_at ? new Date(issue.closed_at).toLocaleString() : ""}
          {issue.close_note && ` — ${issue.close_note}`}
        </p>
      )}
      {lastOutcomeResolved && issue.status === "open" && activeAction === null && (
        <p className="text-xs text-wl-text-secondary">
          Follow-up outcome was Resolved. That records the outcome only — resolve the Issue itself separately.
        </p>
      )}

      {activeAction === "diagnose" && (
        <DiagnoseForm farmId={farmId} issue={issue} onDone={onCloseAction} onCancel={onCloseAction} />
      )}
      {activeAction === "follow_up" && (
        <FollowUpForm
          farmId={farmId}
          issue={issue}
          onDone={(outcome) => {
            onFollowUpRecorded(outcome);
            onCloseAction();
          }}
          onCancel={onCloseAction}
        />
      )}
      {activeAction === "resolve" && <ResolveForm farmId={farmId} issue={issue} onDone={onCloseAction} onCancel={onCloseAction} />}
      {activeAction === "close" && <CloseForm farmId={farmId} issue={issue} onDone={onCloseAction} onCancel={onCloseAction} />}

      {activeAction === null && (primary || secondary.length > 0) && (
        <div className="flex flex-col gap-2">
          {primary && (
            <Button variant="primary" className="w-full" onClick={() => onOpenAction(primary.action)}>
              {primary.label}
            </Button>
          )}
          {secondary.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {secondary.map((s) => (
                <Button key={s.action} variant="secondary" onClick={() => onOpenAction(s.action)}>
                  {s.label}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function CommandError({ command }: { command: { outcome: string; error: AppError | null } }) {
  if (!command.error) return null;
  return (
    <p role="alert" className="text-xs text-danger-700">
      {friendlyMutationErrorMessage(command.error)}
      {command.outcome === "uncertain" &&
        " The outcome is unconfirmed — Retry sends the exact same request and can never apply it twice."}
    </p>
  );
}

function CommandButtons({
  command,
  label,
  pendingLabel,
  disabled,
  onSubmit,
  onCancel,
}: {
  command: { outcome: string; cancel: () => void };
  label: string;
  pendingLabel: string;
  disabled?: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const submitting = command.outcome === "submitting";
  return (
    <div className="flex gap-2">
      <Button
        variant="secondary"
        // UX-OPS-001C/R1: Cancel is only possible while nothing is frozen.
        // An in-flight or uncertain attempt can never be abandoned here --
        // no read proves whether it applied -- so only Retry stays usable.
        disabled={command.outcome !== "editing"}
        onClick={() => {
          command.cancel();
          onCancel();
        }}
      >
        Cancel
      </Button>
      <Button variant="primary" className="flex-1" disabled={submitting || disabled} onClick={onSubmit}>
        {submitting ? pendingLabel : command.outcome === "uncertain" ? "Retry" : label}
      </Button>
    </div>
  );
}

function DiagnoseForm({ farmId, issue, onDone, onCancel }: { farmId: string; issue: CropIssueRead; onDone: () => void; onCancel: () => void }) {
  const mutation = useConfirmCropIssueDiagnosis(farmId);
  const [diagnosis, setDiagnosis] = useState("");
  const command = useIssueCommand<CropIssueConfirmDiagnosisIn & Record<string, unknown>>(
    (payload, handlers) => mutation.mutate({ cropIssueId: issue.id, payload }, handlers),
    onDone,
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border p-3">
      <p className="text-sm font-medium text-wl-text">Confirm Diagnosis</p>
      <p className="text-xs text-wl-text-secondary">
        Never auto-copied from suspected cause — enter the confirmed diagnosis explicitly.
      </p>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Confirmed diagnosis</span>
        <textarea
          className={`${inputClass} min-h-16`}
          disabled={command.locked}
          value={diagnosis}
          onChange={(e) => setDiagnosis(e.target.value)}
        />
      </label>
      <CommandError command={command} />
      <CommandButtons
        command={command}
        label="Confirm"
        pendingLabel="Saving…"
        disabled={!diagnosis.trim()}
        onCancel={onCancel}
        onSubmit={() =>
          command.run((clientCommandId) => ({ client_command_id: clientCommandId, confirmed_diagnosis: diagnosis.trim() }))
        }
      />
    </div>
  );
}

function FollowUpForm({
  farmId,
  issue,
  onDone,
  onCancel,
}: {
  farmId: string;
  issue: CropIssueRead;
  onDone: (outcome: (typeof FOLLOW_UP_OUTCOMES)[number]) => void;
  onCancel: () => void;
}) {
  const mutation = useRecordCropIssueFollowUp(farmId, issue.id);
  const [outcome, setOutcome] = useState<(typeof FOLLOW_UP_OUTCOMES)[number]>("unchanged");
  const [notes, setNotes] = useState("");
  const command = useIssueCommand<CropIssueFollowUpIn & Record<string, unknown>>(
    (payload, handlers) => mutation.mutate(payload, handlers),
    () => onDone(outcome),
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border p-3">
      <p className="text-sm font-medium text-wl-text">Add Follow-up</p>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Outcome</span>
        <select
          className={inputClass}
          disabled={command.locked}
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as typeof outcome)}
        >
          {FOLLOW_UP_OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {humanizeEnumCode(o)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Notes (optional)</span>
        <textarea
          className={`${inputClass} min-h-16`}
          disabled={command.locked}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {outcome === "resolved" && (
        <p className="text-xs text-wl-text-secondary">
          This records the outcome only — it does not resolve the Issue itself. You can resolve it separately.
        </p>
      )}
      <CommandError command={command} />
      <CommandButtons
        command={command}
        label="Save Follow-up"
        pendingLabel="Saving…"
        onCancel={onCancel}
        onSubmit={() =>
          command.run((clientCommandId) => ({
            client_command_id: clientCommandId,
            follow_up_grower_inspection_id: null,
            affected_count: null,
            notes: notes.trim() || null,
            outcome,
          }))
        }
      />
    </div>
  );
}

function ResolveForm({ farmId, issue, onDone, onCancel }: { farmId: string; issue: CropIssueRead; onDone: () => void; onCancel: () => void }) {
  const mutation = useResolveCropIssue(farmId);
  const [resolutionNote, setResolutionNote] = useState("");
  const command = useIssueCommand<CropIssueResolveIn & Record<string, unknown>>(
    (payload, handlers) => mutation.mutate({ cropIssueId: issue.id, payload }, handlers),
    onDone,
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border p-3">
      <p className="text-sm font-medium text-wl-text">Resolve Issue</p>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Resolution note</span>
        <textarea
          className={`${inputClass} min-h-16`}
          disabled={command.locked}
          value={resolutionNote}
          onChange={(e) => setResolutionNote(e.target.value)}
        />
      </label>
      <CommandError command={command} />
      <CommandButtons
        command={command}
        label="Confirm Resolve"
        pendingLabel="Resolving…"
        disabled={!resolutionNote.trim()}
        onCancel={onCancel}
        onSubmit={() =>
          command.run((clientCommandId) => ({ client_command_id: clientCommandId, resolution_note: resolutionNote.trim() }))
        }
      />
    </div>
  );
}

function CloseForm({ farmId, issue, onDone, onCancel }: { farmId: string; issue: CropIssueRead; onDone: () => void; onCancel: () => void }) {
  const mutation = useCloseCropIssue(farmId);
  const [closeNote, setCloseNote] = useState("");
  const command = useIssueCommand<CropIssueCloseIn & Record<string, unknown>>(
    (payload, handlers) => mutation.mutate({ cropIssueId: issue.id, payload }, handlers),
    onDone,
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-wl-border p-3">
      <p className="text-sm font-medium text-wl-text">Close Issue</p>
      <label className="flex flex-col gap-1">
        <span className={labelClass}>Close note (optional)</span>
        <textarea
          className={`${inputClass} min-h-16`}
          disabled={command.locked}
          value={closeNote}
          onChange={(e) => setCloseNote(e.target.value)}
        />
      </label>
      <CommandError command={command} />
      <CommandButtons
        command={command}
        label="Confirm Close"
        pendingLabel="Closing…"
        onCancel={onCancel}
        onSubmit={() =>
          command.run((clientCommandId) => ({ client_command_id: clientCommandId, close_note: closeNote.trim() || null }))
        }
      />
    </div>
  );
}

function CorrectiveWorkPanel({ farmId, issue }: { farmId: string; issue: CropIssueRead }) {
  const [assigning, setAssigning] = useState(false);
  const [created, setCreated] = useState<FarmWorkItemRead | null>(null);
  const batchQuery = useCropBatch(farmId, issue.batch_id);

  return (
    <section>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Corrective work</h2>
      {created ? (
        <div className={`${"overflow-x-auto rounded-xl border border-wl-border bg-wl-surface-raised"}`}>
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-wl-border">
              <WorkItemRow item={created} farmId={farmId} />
            </tbody>
          </table>
        </div>
      ) : !assigning ? (
        <Button variant="secondary" onClick={() => setAssigning(true)}>
          Assign Corrective Work
        </Button>
      ) : (
        <CreateWorkItemForm
          farmId={farmId}
          lockedCropIssue={{ id: issue.id, code: issue.code, batchId: issue.batch_id, batchLabel: batchQuery.data?.code }}
          onCancel={() => setAssigning(false)}
          onSuccess={(item) => setCreated(item)}
        />
      )}
    </section>
  );
}
