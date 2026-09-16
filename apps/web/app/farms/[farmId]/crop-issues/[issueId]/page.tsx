"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { CreateWorkItemForm } from "@/components/work-items/CreateWorkItemForm";
import { WorkItemRow } from "@/components/work-items/WorkItemRow";
import type { FarmWorkItemRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";
import {
  useConfirmCropIssueDiagnosis,
  useCreateWorkItem,
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

/** PILOT-AGRO-001B Part 4: the Crop Issue workspace -- Batch, placement
 * snapshot, originating Inspection, suspected cause vs. confirmed
 * diagnosis (kept visually distinct, never auto-copied), status, corrective
 * work, and follow-up history. Actions are shown deliberately per status
 * (OPEN -> RESOLVED -> CLOSED, never a direct OPEN -> CLOSED, never one
 * generic "Update Issue" form) -- this codebase has no frontend permission
 * hook anywhere (confirmed against `AppShell.tsx`'s single `tenant_admin`
 * nav-only exception), so an unauthorized click is caught by the backend's
 * own 403 and surfaced as a friendly error, exactly like every other
 * command in this app. */
export default function CropIssueWorkspacePage() {
  const { farmId, issueId } = useParams<{ farmId: string; issueId: string }>();
  const issueQuery = useCropIssue(farmId, issueId);
  const followUpsQuery = useCropIssueFollowUps(farmId, issueId);

  if (issueQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading crop issue" />;
  if (issueQuery.error) return <ErrorState error={issueQuery.error} onRetry={() => issueQuery.refetch()} />;
  const issue = issueQuery.data;
  if (!issue) return null;

  return (
    <div>
      <PageHeader
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

      <IssueContext farmId={farmId} issue={issue} />
      <DiagnosisPanel farmId={farmId} issue={issue} />
      <CorrectiveWorkPanel farmId={farmId} issue={issue} />
      <FollowUpPanel farmId={farmId} issue={issue} followUps={followUpsQuery.data ?? []} loading={followUpsQuery.isLoading} error={followUpsQuery.error} />
      <ResolveClosePanel farmId={farmId} issue={issue} />
    </div>
  );
}

function IssueContext({ farmId, issue }: { farmId: string; issue: NonNullable<ReturnType<typeof useCropIssue>["data"]> }) {
  const batchQuery = useCropBatch(farmId, issue.batch_id);
  const inspectionQuery = useGrowerInspection(farmId, issue.batch_id, issue.originating_grower_inspection_id);
  const batch = batchQuery.data;
  const inspection = inspectionQuery.data;
  const originatingFinding = inspection?.findings.find((f) => f.id === issue.originating_finding_id);

  return (
    <section className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
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
      {issue.has_open_work_item && (
        <p className="mt-3 text-xs text-wl-text-secondary">This issue has an open corrective Work Item.</p>
      )}
      {issue.is_follow_up_overdue && (
        <p className="mt-1 text-xs text-wl-flag-fg">Follow-up is overdue.</p>
      )}
    </section>
  );
}

function DiagnosisPanel({ farmId, issue }: { farmId: string; issue: NonNullable<ReturnType<typeof useCropIssue>["data"]> }) {
  const confirmDiagnosis = useConfirmCropIssueDiagnosis(farmId);
  const [confirming, setConfirming] = useState(false);
  const [diagnosis, setDiagnosis] = useState("");

  return (
    <section className="mb-6 grid grid-cols-1 gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4 sm:grid-cols-2">
      <div>
        <h2 className="mb-1 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Suspected cause</h2>
        <p className="text-sm text-wl-text">{issue.suspected_cause ?? "Not recorded"}</p>
      </div>
      <div>
        <h2 className="mb-1 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Confirmed diagnosis</h2>
        {issue.confirmed_diagnosis ? (
          <p className="text-sm text-wl-text">{issue.confirmed_diagnosis}</p>
        ) : issue.status === "open" && !confirming ? (
          <Button variant="secondary" onClick={() => setConfirming(true)}>
            Confirm Diagnosis
          </Button>
        ) : issue.status === "open" && confirming ? (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-wl-text-secondary">
              Never auto-copied from suspected cause — enter the confirmed diagnosis explicitly.
            </p>
            <textarea className={`${inputClass} min-h-16`} value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} />
            {confirmDiagnosis.error && <ErrorState error={confirmDiagnosis.error} />}
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setConfirming(false)} disabled={confirmDiagnosis.isPending}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={confirmDiagnosis.isPending || !diagnosis.trim()}
                onClick={() =>
                  confirmDiagnosis.mutate(
                    { cropIssueId: issue.id, payload: { client_command_id: crypto.randomUUID(), confirmed_diagnosis: diagnosis.trim() } },
                    { onSuccess: () => setConfirming(false) },
                  )
                }
              >
                {confirmDiagnosis.isPending ? "Saving…" : "Confirm"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-wl-text-secondary">Not confirmed</p>
        )}
      </div>
    </section>
  );
}

function CorrectiveWorkPanel({ farmId, issue }: { farmId: string; issue: NonNullable<ReturnType<typeof useCropIssue>["data"]> }) {
  const [assigning, setAssigning] = useState(false);
  const [created, setCreated] = useState<FarmWorkItemRead | null>(null);
  const createWorkItem = useCreateWorkItem(farmId);
  const batchQuery = useCropBatch(farmId, issue.batch_id);

  return (
    <section className="mb-6">
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
          lockedCropIssue={{ id: issue.id, code: issue.code, batchId: issue.batch_id, batchLabel: batchQuery.data?.code }}
          isSubmitting={createWorkItem.isPending}
          serverError={createWorkItem.error ? createWorkItem.error.message : null}
          onCancel={() => setAssigning(false)}
          onSubmit={(payload) => createWorkItem.mutate(payload, { onSuccess: (item) => setCreated(item) })}
        />
      )}
    </section>
  );
}

function FollowUpPanel({
  farmId,
  issue,
  followUps,
  loading,
  error,
}: {
  farmId: string;
  issue: NonNullable<ReturnType<typeof useCropIssue>["data"]>;
  followUps: NonNullable<ReturnType<typeof useCropIssueFollowUps>["data"]>;
  loading: boolean;
  error: unknown;
}) {
  const recordFollowUp = useRecordCropIssueFollowUp(farmId, issue.id);
  const resolveIssue = useResolveCropIssue(farmId);
  const [adding, setAdding] = useState(false);
  const [outcome, setOutcome] = useState<(typeof FOLLOW_UP_OUTCOMES)[number]>("unchanged");
  const [notes, setNotes] = useState("");
  const [lastOutcomeResolved, setLastOutcomeResolved] = useState(false);
  const [resolutionNote, setResolutionNote] = useState("");
  const [resolving, setResolving] = useState(false);

  return (
    <section className="mb-6">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Follow-up</h2>
        {issue.status === "open" && !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Add Follow-up
          </Button>
        )}
      </div>

      {adding && (
        <div className="mb-3 flex flex-col gap-2 rounded-lg border border-wl-border p-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Outcome</span>
            <select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value as typeof outcome)}>
              {FOLLOW_UP_OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {humanizeEnumCode(o)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Notes (optional)</span>
            <textarea className={`${inputClass} min-h-16`} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {outcome === "resolved" && (
            <p className="text-xs text-wl-text-secondary">
              This records the outcome only — it does not resolve the Issue itself. You can resolve it separately below.
            </p>
          )}
          {recordFollowUp.error && <ErrorState error={recordFollowUp.error} />}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setAdding(false)} disabled={recordFollowUp.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={recordFollowUp.isPending}
              onClick={() =>
                recordFollowUp.mutate(
                  { client_command_id: crypto.randomUUID(), follow_up_grower_inspection_id: null, affected_count: null, notes: notes.trim() || null, outcome },
                  {
                    onSuccess: () => {
                      setAdding(false);
                      setNotes("");
                      setLastOutcomeResolved(outcome === "resolved");
                    },
                  },
                )
              }
            >
              {recordFollowUp.isPending ? "Saving…" : "Save Follow-up"}
            </Button>
          </div>
        </div>
      )}

      {lastOutcomeResolved && issue.status === "open" && (
        <p className="mb-3 text-xs text-wl-text-secondary">
          Follow-up outcome was Resolved.{" "}
          <button type="button" className="font-medium text-wl-brand hover:underline" onClick={() => setResolving(true)}>
            Resolve this Issue?
          </button>
        </p>
      )}

      {loading && <LoadingSkeleton rows={2} label="Loading follow-ups" />}
      {Boolean(error) && <ErrorState error={error} />}
      {!loading && followUps.length === 0 && <p className="text-sm text-wl-text-secondary">No follow-up recorded yet.</p>}
      {followUps.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {followUps.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
              <span className="font-medium text-wl-text">{humanizeEnumCode(f.outcome)}</span>
              <span className="text-wl-text-secondary">{f.notes ?? "—"}</span>
              <span className="text-xs text-wl-text-secondary">{new Date(f.recorded_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      {resolving && (
        <div className="mt-3 flex flex-col gap-2 rounded-lg border border-wl-border p-3">
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Resolution note</span>
            <textarea className={`${inputClass} min-h-16`} value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} />
          </label>
          {resolveIssue.error && <ErrorState error={resolveIssue.error} />}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setResolving(false)} disabled={resolveIssue.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={resolveIssue.isPending || !resolutionNote.trim()}
              onClick={() =>
                resolveIssue.mutate(
                  { cropIssueId: issue.id, payload: { client_command_id: crypto.randomUUID(), resolution_note: resolutionNote.trim() } },
                  { onSuccess: () => setResolving(false) },
                )
              }
            >
              {resolveIssue.isPending ? "Resolving…" : "Resolve Issue"}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function ResolveClosePanel({ farmId, issue }: { farmId: string; issue: NonNullable<ReturnType<typeof useCropIssue>["data"]> }) {
  const resolveIssue = useResolveCropIssue(farmId);
  const closeIssue = useCloseCropIssue(farmId);
  const [resolving, setResolving] = useState(false);
  const [closing, setClosing] = useState(false);
  const [resolutionNote, setResolutionNote] = useState("");
  const [closeNote, setCloseNote] = useState("");

  if (issue.status === "closed") {
    return (
      <section className="rounded-lg border border-wl-border bg-wl-surface-raised p-4 text-sm text-wl-text-secondary">
        Closed {issue.closed_at ? new Date(issue.closed_at).toLocaleString() : ""}
        {issue.close_note && ` — ${issue.close_note}`}
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-wl-border bg-wl-surface-raised p-4">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Resolve / Close</h2>
      {issue.status === "open" && (
        <>
          {!resolving ? (
            <Button variant="secondary" onClick={() => setResolving(true)}>
              Resolve Issue
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Resolution note</span>
                <textarea className={`${inputClass} min-h-16`} value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} />
              </label>
              {resolveIssue.error && <ErrorState error={resolveIssue.error} />}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setResolving(false)} disabled={resolveIssue.isPending}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={resolveIssue.isPending || !resolutionNote.trim()}
                  onClick={() =>
                    resolveIssue.mutate(
                      { cropIssueId: issue.id, payload: { client_command_id: crypto.randomUUID(), resolution_note: resolutionNote.trim() } },
                      { onSuccess: () => setResolving(false) },
                    )
                  }
                >
                  {resolveIssue.isPending ? "Resolving…" : "Confirm Resolve"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
      {issue.status === "resolved" && (
        <>
          <p className="mb-2 text-sm text-wl-text-secondary">
            Resolved {issue.resolved_at ? new Date(issue.resolved_at).toLocaleString() : ""}
            {issue.resolution_note && ` — ${issue.resolution_note}`}
          </p>
          {!closing ? (
            <Button variant="secondary" onClick={() => setClosing(true)}>
              Close Issue
            </Button>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Close note (optional)</span>
                <textarea className={`${inputClass} min-h-16`} value={closeNote} onChange={(e) => setCloseNote(e.target.value)} />
              </label>
              {closeIssue.error && <ErrorState error={closeIssue.error} />}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setClosing(false)} disabled={closeIssue.isPending}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={closeIssue.isPending}
                  onClick={() =>
                    closeIssue.mutate(
                      { cropIssueId: issue.id, payload: { client_command_id: crypto.randomUUID(), close_note: closeNote.trim() || null } },
                      { onSuccess: () => setClosing(false) },
                    )
                  }
                >
                  {closeIssue.isPending ? "Closing…" : "Confirm Close"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
