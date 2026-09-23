"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { PlacementSummary } from "@/components/PlacementSummary";
import { StatusBadge } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ContextStrip, ContextStripFact } from "@/components/layout/ContextStrip";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { STICKY_ACTION_BAR_SPACER_CLASS, StickyActionBar } from "@/components/layout/StickyActionBar";
import { Button } from "@/components/ui/Button";
import type {
  CropIssueOpenIn,
  GrowerInspectionCreate,
  GrowerInspectionRead,
  InspectionFindingIn,
  InspectionObservationValueIn,
} from "@/lib/api/client";
import { useFrozenSubmission } from "@/lib/commands/frozenSubmission";
import { AppError, friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { validateAffectedWithinInspected } from "@/lib/validation/growerInspection";
import {
  useBatchOperationalContext,
  useBatchProtocolStatus,
  useCropBatch,
  useObservationDefinitions,
  useOpenCropIssue,
  useRecordGrowerInspection,
} from "@/lib/query/hooks";

const FINDING_CATEGORIES = [
  "vigor", "uniformity", "roots", "leaf_condition", "pest_evidence", "disease_like_symptoms",
  "physical_damage", "deficiency_like_symptoms", "growth_deviation", "contamination_concern", "other",
] as const;
const FINDING_SEVERITIES = ["low", "medium", "high", "critical"] as const;
const OVERALL_ASSESSMENTS = ["normal", "attention_needed", "critical"] as const;

const inputClass =
  "min-h-10 w-full rounded-md border border-wl-border bg-wl-surface px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";
const labelClass = "text-xs font-medium text-wl-text-secondary";

function humanize(v: string) {
  return v
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

interface FindingRow {
  key: string;
  category: (typeof FINDING_CATEGORIES)[number];
  severity: (typeof FINDING_SEVERITIES)[number];
  affectedCount: string;
  notes: string;
  suspectedCause: string;
}

interface ObservationRow {
  raw: string;
}

/** PILOT-AGRO-001B Part 3: the "Inspect Crop" operator workspace.
 * CONTEXT -> WHAT IS DUE/WRONG -> RECORD ACTION -> NEXT STEP. Accepts
 * batchId (required) and optionally assignmentId from QR/Today-on-the-Farm/
 * Batch context -- when assignmentId is present it is the exact physical
 * placement this workspace targets, never silently widened to a Batch-wide
 * pick (FROZEN, mirrors PILOT-SCAN-001E's own placement-vs-batch rule). One
 * Inspection records MULTIPLE ObservationValues in ONE ObservationEvent
 * (never one Inspection per measurement) -- see `handleSubmit` below,
 * which builds one `GrowerInspectionCreate` for the whole form.
 *
 * UX-OPS-001C: a guided command layout -- context strip (Batch, Stage,
 * Placement, Protocol), inputs in the main area (Findings bounded), and a
 * sticky summary/blocker rail with the single Record Inspection action.
 * Command identity is now frozen per attempt (`useFrozenSubmission`): an
 * uncertain outcome (network/5xx) is retried with the SAME
 * `client_command_id` and byte-identical payload -- the backend replays it
 * rather than recording a duplicate Inspection -- and inputs are locked
 * until that attempt resolves; a definitive rejection unlocks editing and
 * the next submit mints a new id. */
export default function InspectCropPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const batchId = searchParams.get("batchId");
  const assignmentId = searchParams.get("assignmentId");

  const batchQuery = useCropBatch(farmId, batchId ?? "");
  const operationalQuery = useBatchOperationalContext(farmId, batchId ?? "");
  const statusQuery = useBatchProtocolStatus(farmId, batchId ?? undefined);
  const definitionsQuery = useObservationDefinitions();
  const recordInspection = useRecordGrowerInspection(farmId, batchId ?? "");

  const [inspectedCount, setInspectedCount] = useState("");
  const [overallAssessment, setOverallAssessment] = useState<(typeof OVERALL_ASSESSMENTS)[number]>("normal");
  const [notes, setNotes] = useState("");
  const [observationRows, setObservationRows] = useState<Record<string, ObservationRow>>({});
  const [findings, setFindings] = useState<FindingRow[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<GrowerInspectionRead | null>(null);
  const command = useFrozenSubmission<GrowerInspectionCreate & Record<string, unknown>>();

  const definitionsById = useMemo(
    () => new Map((definitionsQuery.data ?? []).map((d) => [d.id, d])),
    [definitionsQuery.data],
  );

  if (!batchId) {
    return (
      <div>
        <PageHeader title="Inspect Crop" />
        <EmptyState
          title="No Batch selected"
          description="Open Inspect Crop from a Batch page, Today on the Farm, or by scanning a Batch/Placement/Carrier QR code."
        />
      </div>
    );
  }

  if (batchQuery.isLoading) return <LoadingSkeleton rows={6} label="Loading batch" />;
  if (batchQuery.error) return <ErrorState error={batchQuery.error} onRetry={() => batchQuery.refetch()} />;
  const batch = batchQuery.data;
  if (!batch) return null;

  const status = statusQuery.data;
  const dueRequirements = status?.due_observation_requirements ?? [];

  function setObservationRaw(requirementDefinitionId: string, raw: string) {
    setObservationRows((prev) => ({ ...prev, [requirementDefinitionId]: { raw } }));
  }

  function addFinding() {
    setFindings((prev) => [
      ...prev,
      { key: crypto.randomUUID(), category: "vigor", severity: "low", affectedCount: "", notes: "", suspectedCause: "" },
    ]);
  }

  function updateFinding(key: string, patch: Partial<FindingRow>) {
    setFindings((prev) => prev.map((f) => (f.key === key ? { ...f, ...patch } : f)));
  }

  function removeFinding(key: string) {
    setFindings((prev) => prev.filter((f) => f.key !== key));
  }

  function handleSubmit() {
    if (!batchId) return;
    setFormError(null);
    const inspected = inspectedCount.trim() ? Number(inspectedCount) : null;
    if (inspectedCount.trim() && (!Number.isInteger(inspected) || (inspected as number) < 0)) {
      setFormError("Inspected count must be a whole number.");
      return;
    }

    const findingPayloads: InspectionFindingIn[] = [];
    for (const f of findings) {
      const affected = f.affectedCount.trim() ? Number(f.affectedCount) : null;
      if (f.affectedCount.trim() && !Number.isInteger(affected)) {
        setFormError(`${humanize(f.category)} finding: affected count must be a whole number.`);
        return;
      }
      const affectedError = validateAffectedWithinInspected(inspected, affected);
      if (affectedError) {
        setFormError(`${humanize(f.category)} finding: ${affectedError.charAt(0).toLowerCase()}${affectedError.slice(1)}`);
        return;
      }
      findingPayloads.push({
        category: f.category,
        severity: f.severity,
        affected_count: affected,
        notes: f.notes.trim() || null,
        suspected_cause: f.suspectedCause.trim() || null,
      });
    }

    const observationValues: InspectionObservationValueIn[] = [];
    for (const req of dueRequirements) {
      const raw = observationRows[req.requirement.observation_definition_id]?.raw?.trim();
      if (!raw) continue;
      const definition = definitionsById.get(req.requirement.observation_definition_id);
      const value: InspectionObservationValueIn = {
        observation_definition_id: req.requirement.observation_definition_id,
        batch_carrier_assignment_id: assignmentId,
      };
      if (definition?.value_type === "integer") {
        value.value_integer = Number(raw);
      } else if (definition?.value_type === "decimal" || definition?.value_type === "percentage") {
        value.value_decimal = Number(raw);
      } else if (definition?.value_type === "boolean") {
        value.value_boolean = raw === "true";
      } else {
        value.value_text = raw;
      }
      observationValues.push(value);
    }

    const payload = command.submit((clientCommandId) => ({
      client_command_id: clientCommandId,
      batch_id: batchId,
      batch_carrier_assignment_id: assignmentId,
      effective_time: null,
      inspected_count: inspected,
      overall_assessment: overallAssessment,
      notes: notes.trim() || null,
      findings: findingPayloads,
      observation_values: observationValues,
    }));
    send(payload);
  }

  function send(payload: GrowerInspectionCreate) {
    recordInspection.mutate(payload, {
      onSuccess: (result) => {
        command.handleSuccess();
        setSaved(result);
      },
      onError: (error) =>
        command.handleError(
          error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again."),
        ),
    });
  }

  function retry() {
    const payload = command.retry();
    if (payload) send(payload);
  }

  if (saved) {
    return (
      <InspectionSavedPanel
        farmId={farmId}
        batchId={batchId}
        inspection={saved}
        onDone={() => router.push(`/farms/${farmId}/crop-batches/${batchId}`)}
        onRecordAnother={() => {
          setSaved(null);
          setInspectedCount("");
          setNotes("");
          setObservationRows({});
          setFindings([]);
        }}
      />
    );
  }

  const operational = operationalQuery.data;
  const locked = command.outcome !== "editing";
  const requiredDue = dueRequirements.filter((r) => r.requirement.requirement_level === "required");
  const enteredCount = dueRequirements.filter(
    (r) => (observationRows[r.requirement.observation_definition_id]?.raw ?? "").trim() !== "",
  ).length;
  const blockers = [
    formError,
    command.error
      ? command.outcome === "uncertain"
        ? `${friendlyMutationErrorMessage(command.error)} The inspection may or may not have been recorded — Retry sends the exact same inspection again and can never record it twice.`
        : friendlyMutationErrorMessage(command.error)
      : null,
  ].filter((b): b is string => Boolean(b));

  return (
    <div className={STICKY_ACTION_BAR_SPACER_CLASS}>
      <PageHeader
        compact
        title="Inspect Crop"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Batches", href: `/farms/${farmId}/crop-batches` },
              { label: batch.code, href: `/farms/${farmId}/crop-batches/${batchId}` },
              { label: "Inspect Crop" },
            ]}
          />
        }
      />

      {/* CONTEXT */}
      <div className="mb-4">
        <ContextStrip>
          <ContextStripFact
            label="Batch"
            value={`${batch.code} — ${batch.crop.common_name}${batch.variety ? ` / ${batch.variety.name}` : ""}`}
          />
          <ContextStripFact label="Stage" value={batch.current_stage.name} />
          {operational && <ContextStripFact label="Placement" value={<PlacementSummary placement={operational.placement} />} />}
          {assignmentId && <ContextStripFact label="Scope" value="Exact placement (from scan/row)" />}
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-wl-text-secondary">Protocol</span>
            {status?.protocol ? (
              <StatusBadge
                label={`${status.protocol.name} v${status.protocol_version?.version_number}`}
                tone="active"
              />
            ) : (
              <StatusBadge label="No protocol assigned" tone="neutral" />
            )}
          </div>
        </ContextStrip>
      </div>

      <SplitWorkspace
        main={
          // A single disabled fieldset locks every input while an attempt is
          // in flight or uncertain, so what Retry resends can never drift
          // from what the screen shows.
          <fieldset disabled={locked} className="flex min-w-0 flex-col gap-4">
            <section className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Counts</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>Inspected count (optional)</span>
                  <input
                    value={inspectedCount}
                    onChange={(e) => setInspectedCount(e.target.value)}
                    className={inputClass}
                    inputMode="numeric"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>Overall assessment</span>
                  <select
                    value={overallAssessment}
                    onChange={(e) => setOverallAssessment(e.target.value as typeof overallAssessment)}
                    className={inputClass}
                  >
                    {OVERALL_ASSESSMENTS.map((a) => (
                      <option key={a} value={a}>
                        {humanize(a)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>

            <section className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">
                Protocol observations due at this stage
              </h2>
              {statusQuery.isLoading && <LoadingSkeleton rows={2} label="Loading protocol requirements" />}
              {statusQuery.error && <ErrorState error={statusQuery.error} onRetry={() => statusQuery.refetch()} />}
              {status && dueRequirements.length === 0 && (
                <p className="text-sm text-wl-text-secondary">
                  {status.protocol ? "No observations required at this stage." : "No growing protocol assigned."}
                </p>
              )}
              {dueRequirements.length > 0 && (
                <div className="flex flex-col gap-2">
                  {dueRequirements.map((r) => {
                    const definition = definitionsById.get(r.requirement.observation_definition_id);
                    const raw = observationRows[r.requirement.observation_definition_id]?.raw ?? "";
                    return (
                      <div
                        key={r.requirement.id}
                        className="grid grid-cols-1 items-center gap-2 rounded-lg border border-wl-border p-2.5 sm:grid-cols-[1fr_auto_auto]"
                      >
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>
                            {r.observation_definition_name}
                            {definition?.unit ? ` (${definition.unit})` : ""}
                            {r.requirement.requirement_level === "required" ? " · required" : " · recommended"}
                          </span>
                          {definition?.value_type === "boolean" ? (
                            <select
                              className={inputClass}
                              value={raw}
                              onChange={(e) => setObservationRaw(r.requirement.observation_definition_id, e.target.value)}
                            >
                              <option value="">Not observed</option>
                              <option value="true">Yes</option>
                              <option value="false">No</option>
                            </select>
                          ) : definition?.value_type === "text" ? (
                            <input
                              className={inputClass}
                              value={raw}
                              onChange={(e) => setObservationRaw(r.requirement.observation_definition_id, e.target.value)}
                            />
                          ) : (
                            <input
                              type="number"
                              className={inputClass}
                              value={raw}
                              onChange={(e) => setObservationRaw(r.requirement.observation_definition_id, e.target.value)}
                            />
                          )}
                        </label>
                        {r.is_overdue ? (
                          <StatusBadge label="Overdue" tone="critical" />
                        ) : r.is_due ? (
                          <StatusBadge label="Due" tone="attention" />
                        ) : (
                          <StatusBadge label="Not due" tone="neutral" />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Findings</h2>
                <Button variant="secondary" onClick={addFinding}>
                  + Add finding
                </Button>
              </div>
              {findings.length === 0 && <p className="text-sm text-wl-text-secondary">No findings recorded.</p>}
              {findings.length > 0 && (
                <BoundedDataRegion label="Findings">
                  <div className="flex flex-col gap-3 p-2">
                    {findings.map((f, index) => (
                      <div key={f.key} className="grid grid-cols-1 gap-2 rounded-lg border border-wl-border p-3 sm:grid-cols-2">
                        <p className="text-xs font-semibold text-wl-text sm:col-span-2">Finding {index + 1}</p>
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>Category</span>
                          <select
                            className={inputClass}
                            value={f.category}
                            onChange={(e) => updateFinding(f.key, { category: e.target.value as FindingRow["category"] })}
                          >
                            {FINDING_CATEGORIES.map((c) => (
                              <option key={c} value={c}>
                                {humanize(c)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>Severity</span>
                          <select
                            className={inputClass}
                            value={f.severity}
                            onChange={(e) => updateFinding(f.key, { severity: e.target.value as FindingRow["severity"] })}
                          >
                            {FINDING_SEVERITIES.map((sv) => (
                              <option key={sv} value={sv}>
                                {humanize(sv)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>Affected count (optional)</span>
                          <input
                            className={inputClass}
                            value={f.affectedCount}
                            onChange={(e) => updateFinding(f.key, { affectedCount: e.target.value })}
                            inputMode="numeric"
                          />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>Suspected cause (optional)</span>
                          <input
                            className={inputClass}
                            value={f.suspectedCause}
                            onChange={(e) => updateFinding(f.key, { suspectedCause: e.target.value })}
                          />
                        </label>
                        <label className="flex flex-col gap-1 sm:col-span-2">
                          <span className={labelClass}>Notes (optional)</span>
                          <textarea
                            className={`${inputClass} min-h-16`}
                            value={f.notes}
                            onChange={(e) => updateFinding(f.key, { notes: e.target.value })}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => removeFinding(f.key)}
                          className="self-start text-xs font-medium text-danger-700 hover:underline sm:col-span-2"
                        >
                          Remove finding
                        </button>
                      </div>
                    ))}
                  </div>
                </BoundedDataRegion>
              )}
            </section>

            <section className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <label className="flex flex-col gap-1">
                <span className={labelClass}>Notes (optional)</span>
                <textarea className={`${inputClass} min-h-20`} value={notes} onChange={(e) => setNotes(e.target.value)} />
              </label>
            </section>
          </fieldset>
        }
        rail={
          <section aria-label="Inspection summary" className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
            <h2 className="text-sm font-semibold text-wl-text">Summary</h2>
            <dl className="flex flex-col divide-y divide-wl-border text-sm">
              <div className="flex items-baseline justify-between gap-3 py-1.5">
                <dt className="text-wl-text-secondary">Assessment</dt>
                <dd className="font-semibold text-wl-text">{humanize(overallAssessment)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3 py-1.5">
                <dt className="text-wl-text-secondary">Observations entered</dt>
                <dd className="font-semibold tabular-nums text-wl-text">
                  {enteredCount} of {dueRequirements.length}
                  {requiredDue.length > 0 ? ` (${requiredDue.length} required)` : ""}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3 py-1.5">
                <dt className="text-wl-text-secondary">Findings</dt>
                <dd className="font-semibold tabular-nums text-wl-text">{findings.length}</dd>
              </div>
            </dl>
            <p className="text-xs text-wl-text-secondary">
              Recording an inspection never changes living quantity or opens a Crop Issue by itself.
            </p>
            <StickyActionBar
              blockers={
                blockers.length > 0 && (
                  <ul role="alert" className="flex flex-col gap-1 rounded-lg bg-wl-flag-bg px-3 py-2 text-xs font-medium text-wl-flag-fg">
                    {blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                )
              }
            >
              {command.outcome === "uncertain" ? (
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      // Refresh authoritative state before abandoning, so a
                      // recorded-but-unconfirmed inspection shows up in due
                      // status rather than being silently re-entered.
                      statusQuery.refetch();
                      command.abandon();
                    }}
                  >
                    Discard attempt
                  </Button>
                  <Button variant="primary" className="flex-1" onClick={retry}>
                    Retry
                  </Button>
                </div>
              ) : (
                <Button variant="primary" className="w-full" onClick={handleSubmit} disabled={command.outcome === "submitting"}>
                  {command.outcome === "submitting" ? "Recording…" : "Record Inspection"}
                </Button>
              )}
            </StickyActionBar>
          </section>
        }
      />
    </div>
  );
}

function InspectionSavedPanel({
  farmId,
  batchId,
  inspection,
  onDone,
  onRecordAnother,
}: {
  farmId: string;
  batchId: string;
  inspection: GrowerInspectionRead;
  onDone: () => void;
  onRecordAnother: () => void;
}) {
  const router = useRouter();
  const openIssue = useOpenCropIssue(farmId, batchId);
  const [openingIssue, setOpeningIssue] = useState(false);
  const [findingId, setFindingId] = useState<string>(inspection.findings[0]?.id ?? "");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<(typeof FINDING_CATEGORIES)[number]>(
    (inspection.findings[0]?.category as (typeof FINDING_CATEGORIES)[number]) ?? "vigor",
  );
  const [severity, setSeverity] = useState<(typeof FINDING_SEVERITIES)[number]>(
    (inspection.findings[0]?.severity as (typeof FINDING_SEVERITIES)[number]) ?? "low",
  );
  const [suspectedCause, setSuspectedCause] = useState("");
  // UX-OPS-001C: frozen per attempt -- an uncertain Open Issue retry reuses
  // the same `client_command_id` (the backend replays it) instead of
  // minting a new one per click, which could open a duplicate Issue.
  const issueCommand = useFrozenSubmission<CropIssueOpenIn & Record<string, unknown>>();

  function sendOpenIssue(payload: CropIssueOpenIn) {
    openIssue.mutate(payload, {
      onSuccess: (issue) => {
        issueCommand.handleSuccess();
        router.push(`/farms/${farmId}/crop-issues/${issue.id}`);
      },
      onError: (error) =>
        issueCommand.handleError(
          error instanceof AppError ? error : new AppError("server_error", "Something went wrong. Please try again."),
        ),
    });
  }

  function handleOpenIssue() {
    if (!description.trim()) return;
    if (issueCommand.outcome === "uncertain") {
      const payload = issueCommand.retry();
      if (payload) sendOpenIssue(payload);
      return;
    }
    sendOpenIssue(
      issueCommand.submit((clientCommandId) => ({
        client_command_id: clientCommandId,
        originating_grower_inspection_id: inspection.id,
        originating_finding_id: findingId || null,
        category,
        severity,
        description: description.trim(),
        suspected_cause: suspectedCause.trim() || null,
      })),
    );
  }
  const issueLocked = issueCommand.outcome !== "editing";

  return (
    <div>
      <PageHeader compact title="Inspection recorded" />
      <div role="status" className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
        <p className="text-sm text-wl-text">
          Inspection saved with {inspection.findings.length} finding{inspection.findings.length === 1 ? "" : "s"}.
        </p>
        {/* Truthful receipt: only what the server returned for THIS command. */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-wl-text-secondary">Assessment</dt>
            <dd className="font-medium text-wl-text">{humanize(inspection.overall_assessment)}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Inspected</dt>
            <dd className="font-medium tabular-nums text-wl-text">{inspection.inspected_count ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Recorded at</dt>
            <dd className="font-medium text-wl-text">{new Date(inspection.effective_time).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Findings</dt>
            <dd className="font-medium tabular-nums text-wl-text">{inspection.findings.length}</dd>
          </div>
        </dl>

        {!openingIssue ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={onDone}>
              Done
            </Button>
            <Button variant="secondary" onClick={onRecordAnother}>
              Record another inspection
            </Button>
            {inspection.findings.length > 0 && (
              <Button variant="secondary" onClick={() => setOpeningIssue(true)}>
                Open Crop Issue
              </Button>
            )}
            <Link
              href={`/farms/${farmId}/crop-batches/${batchId}`}
              className="inline-flex min-h-9 items-center rounded-lg border border-wl-border-strong px-4 text-sm font-medium text-wl-text hover:bg-wl-surface-hover"
            >
              View Batch
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-3 rounded-lg border border-wl-border p-3">
            <p className="text-sm font-medium text-wl-text">Open Crop Issue</p>
            {inspection.findings.length > 1 && (
              <label className="flex flex-col gap-1">
                <span className={labelClass}>From finding</span>
                <select
                  className={inputClass}
                  disabled={issueLocked}
                  value={findingId}
                  onChange={(e) => {
                    setFindingId(e.target.value);
                    const f = inspection.findings.find((x) => x.id === e.target.value);
                    if (f) {
                      setCategory(f.category as (typeof FINDING_CATEGORIES)[number]);
                      setSeverity(f.severity as (typeof FINDING_SEVERITIES)[number]);
                    }
                  }}
                >
                  {inspection.findings.map((f) => (
                    <option key={f.id} value={f.id}>
                      {humanize(f.category)} ({humanize(f.severity)})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Description</span>
              <textarea
                className={`${inputClass} min-h-16`}
                disabled={issueLocked}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Suspected cause (optional)</span>
              <input
                className={inputClass}
                disabled={issueLocked}
                value={suspectedCause}
                onChange={(e) => setSuspectedCause(e.target.value)}
              />
            </label>
            {issueCommand.error && (
              <p role="alert" className="text-xs text-danger-700">
                {friendlyMutationErrorMessage(issueCommand.error)}
                {issueCommand.outcome === "uncertain" &&
                  " The Issue may or may not have been opened — Retry sends the exact same request and can never open it twice."}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  issueCommand.abandon();
                  setOpeningIssue(false);
                }}
                disabled={issueCommand.outcome === "submitting"}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleOpenIssue}
                disabled={issueCommand.outcome === "submitting" || !description.trim()}
              >
                {issueCommand.outcome === "submitting"
                  ? "Opening…"
                  : issueCommand.outcome === "uncertain"
                    ? "Retry"
                    : "Open Issue"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
