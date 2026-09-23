"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { BoundedDataRegion } from "@/components/layout/BoundedDataRegion";
import { ContextStrip, ContextStripFact } from "@/components/layout/ContextStrip";
import { SplitWorkspace } from "@/components/layout/SplitWorkspace";
import { StickyActionBar } from "@/components/layout/StickyActionBar";
import { Button } from "@/components/ui/Button";
import type {
  CropIssueOpenIn,
  GrowerInspectionCreate,
  GrowerInspectionRead,
  InspectionFindingIn,
  InspectionObservationValueIn,
  ObservationTargetRead,
} from "@/lib/api/client";
import { UNCERTAIN_OUTCOME_COPY, toCommandError, useFrozenSubmission } from "@/lib/commands/frozenSubmission";
import { friendlyMutationErrorMessage } from "@/lib/errors/adapter";
import { validateAffectedWithinInspected } from "@/lib/validation/growerInspection";
import {
  useBatchObservationTargets,
  useBatchProtocolStatus,
  useCropBatch,
  useLocationPath,
  useObservationDefinitions,
  useObservationHistory,
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
const blockerListClass =
  "flex flex-col gap-1 rounded-lg bg-wl-flag-bg px-3 py-2 text-xs font-medium text-wl-flag-fg";

function humanize(v: string) {
  return v
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function targetLabel(target: ObservationTargetRead): string {
  return target.location_label ? `${target.carrier.code} — ${target.location_label}` : target.carrier.code;
}

interface FindingRow {
  key: string;
  category: (typeof FINDING_CATEGORIES)[number];
  severity: (typeof FINDING_SEVERITIES)[number];
  affectedCount: string;
  notes: string;
  suspectedCause: string;
}

/** Everything the Review step shows and `Record Inspection` sends, minus the
 * `client_command_id` -- which is minted only when Record is pressed. */
type InspectionDraft = Omit<GrowerInspectionCreate, "client_command_id">;

type TargetState =
  | { kind: "unselected" }
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "missing"; assignmentId: string }
  | { kind: "resolved"; target: ObservationTargetRead };

/** PILOT-AGRO-001B Part 3: the "Inspect Crop" operator workspace. One
 * Inspection records MULTIPLE ObservationValues in ONE ObservationEvent
 * (never one Inspection per measurement), and -- since UX-OPS-001C/R1
 * (N05) -- the backend commits the Inspection, its Findings, and that
 * Observation atomically.
 *
 * UX-OPS-001C/R1:
 * - Exact target: an inspection is always of ONE exact placement (Batch
 *   Carrier Assignment). `?assignmentId=` is resolved against the Batch's
 *   own authoritative observation targets and shown as carrier code +
 *   location; recording is blocked while it is loading, missing/stale, or
 *   not an active placement of THIS Batch. Opened without one, the operator
 *   must choose an exact placement first -- never a Batch-level inspection
 *   labelled as exact. Changing the placement clears the draft.
 * - Configure -> Review -> Receipt. `Review Inspection` never mints an id;
 *   the payload is frozen only when `Record Inspection` is pressed.
 * - Frozen command: an uncertain outcome (network/5xx) locks the draft and
 *   offers only a byte-identical Retry -- there is no Discard/Cancel,
 *   because no read here proves whether the command applied. A definitive
 *   rejection releases it (next Record mints a new id); success clears it. */
export default function InspectCropPage() {
  const searchParams = useSearchParams();
  const urlBatchId = searchParams.get("batchId");
  const urlAssignmentId = searchParams.get("assignmentId");
  // UX-OPS-001C/R2: the scope (Batch + exact assignment) a workspace was
  // opened for is fixed for that workspace's whole life -- each scope gets
  // its own keyed `InspectCropWorkspace`, so its draft, Review, frozen
  // command, and receipt can never mix with another scope. A same-route
  // query change (A -> B) remounts a fresh workspace for B only while the
  // current one is `pinned` = nothing in flight/unresolved and no receipt
  // on screen. An in-flight or uncertain attempt is never abandoned
  // because the URL changed: it keeps its original target and its
  // byte-identical Retry, and B is applied once it resolves.
  const [applied, setApplied] = useState({ batchId: urlBatchId, assignmentId: urlAssignmentId });
  const [pinned, setPinned] = useState(false);
  if (!pinned && (applied.batchId !== urlBatchId || applied.assignmentId !== urlAssignmentId)) {
    setApplied({ batchId: urlBatchId, assignmentId: urlAssignmentId });
  }
  return (
    <InspectCropWorkspace
      key={`${applied.batchId ?? ""}|${applied.assignmentId ?? ""}`}
      batchId={applied.batchId}
      urlAssignmentId={applied.assignmentId}
      onPinnedChange={setPinned}
    />
  );
}

function InspectCropWorkspace({
  batchId,
  urlAssignmentId,
  onPinnedChange,
}: {
  batchId: string | null;
  urlAssignmentId: string | null;
  onPinnedChange: (pinned: boolean) => void;
}) {
  const { farmId } = useParams<{ farmId: string }>();
  const router = useRouter();

  const batchQuery = useCropBatch(farmId, batchId ?? "");
  const statusQuery = useBatchProtocolStatus(farmId, batchId ?? undefined);
  const definitionsQuery = useObservationDefinitions();
  const targetsQuery = useBatchObservationTargets(farmId, batchId);
  const recordInspection = useRecordGrowerInspection(farmId, batchId ?? "");

  const [chosenAssignmentId, setChosenAssignmentId] = useState<string | null>(null);
  const [step, setStep] = useState<"configure" | "review">("configure");
  const [inspectedCount, setInspectedCount] = useState("");
  const [overallAssessment, setOverallAssessment] = useState<(typeof OVERALL_ASSESSMENTS)[number]>("normal");
  const [notes, setNotes] = useState("");
  const [observationRows, setObservationRows] = useState<Record<string, string>>({});
  const [findings, setFindings] = useState<FindingRow[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  // The Review draft carries the exact target it was built for -- Review and
  // the receipt render THIS, never whichever target happens to be live.
  const [draft, setDraft] = useState<{ payload: InspectionDraft; target: ObservationTargetRead } | null>(null);
  const [saved, setSaved] = useState<{ inspection: GrowerInspectionRead; target: ObservationTargetRead | null } | null>(
    null,
  );
  const command = useFrozenSubmission<GrowerInspectionCreate & Record<string, unknown>>();
  const locked = command.outcome !== "editing";
  const pinned = locked || saved !== null;
  const pinnedCallbackRef = useRef(onPinnedChange);
  useEffect(() => {
    pinnedCallbackRef.current = onPinnedChange;
  });
  useEffect(() => {
    pinnedCallbackRef.current(pinned);
  }, [pinned]);
  useEffect(() => () => pinnedCallbackRef.current(false), []);

  const definitionsById = useMemo(
    () => new Map((definitionsQuery.data ?? []).map((d) => [d.id, d])),
    [definitionsQuery.data],
  );

  const targetAssignmentId = chosenAssignmentId ?? urlAssignmentId;
  const targets = targetsQuery.data ?? [];
  const targetState: TargetState = !targetAssignmentId
    ? { kind: "unselected" }
    : targetsQuery.isLoading
      ? { kind: "loading" }
      : targetsQuery.isError
        ? { kind: "error" }
        : (() => {
            const target = targets.find((t) => t.id === targetAssignmentId);
            return target ? { kind: "resolved", target } : { kind: "missing", assignmentId: targetAssignmentId };
          })();
  const resolvedTarget = targetState.kind === "resolved" ? targetState.target : null;

  if (!batchId) {
    return (
      <div>
        <PageHeader compact title="Inspect Crop" />
        <EmptyState
          title="No Batch selected"
          description="Open Inspect Crop from a Plate, Grow Bag, or placement QR code so the exact placement is known."
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

  function resetDraft() {
    setStep("configure");
    setInspectedCount("");
    setOverallAssessment("normal");
    setNotes("");
    setObservationRows({});
    setFindings([]);
    setFormError(null);
    setDraft(null);
  }

  /** Changing scope is a different inspection: clear the draft and any
   * released attempt (only reachable while nothing is frozen). */
  function chooseTarget(assignmentId: string) {
    if (locked) return;
    command.abandon();
    resetDraft();
    setChosenAssignmentId(assignmentId || null);
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

  /** Validates the Configure inputs and builds the Review draft. Never mints
   * a `client_command_id`. */
  function goToReview() {
    if (!batchId || !resolvedTarget) return;
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
      const raw = observationRows[req.requirement.observation_definition_id]?.trim();
      if (!raw) continue;
      const definition = definitionsById.get(req.requirement.observation_definition_id);
      const value: InspectionObservationValueIn = {
        observation_definition_id: req.requirement.observation_definition_id,
        // The exact placement for every definition that can take one; a
        // crop_batch-scoped definition must carry none (backend rule).
        batch_carrier_assignment_id: definition?.target_scope === "crop_batch" ? null : resolvedTarget.id,
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

    setDraft({
      target: resolvedTarget,
      payload: {
        batch_id: batchId,
        batch_carrier_assignment_id: resolvedTarget.id,
        effective_time: null,
        inspected_count: inspected,
        overall_assessment: overallAssessment,
        notes: notes.trim() || null,
        findings: findingPayloads,
        observation_values: observationValues,
      },
    });
    setStep("review");
  }

  /** `target` is the frozen command's own target (the draft's), never the
   * live `resolvedTarget` at settle time. */
  function send(payload: GrowerInspectionCreate, target: ObservationTargetRead) {
    recordInspection.mutateAsync(payload).then(
      (result) => {
        command.handleSuccess();
        setSaved({ inspection: result, target });
      },
      (error) => command.handleError(toCommandError(error)),
    );
  }

  function recordInspectionCommand() {
    if (!draft) return;
    if (command.outcome === "uncertain") {
      const frozen = command.retry();
      if (frozen) send(frozen, draft.target);
      return;
    }
    // Frozen HERE -- the first actual submission -- never on Review/Back.
    send(command.submit((clientCommandId) => ({ ...draft.payload, client_command_id: clientCommandId })), draft.target);
  }

  if (saved) {
    return (
      <InspectionReceipt
        farmId={farmId}
        batchId={batchId}
        batchCode={batch.code}
        inspection={saved.inspection}
        target={saved.target}
        onDone={() => router.push(`/farms/${farmId}/crop-batches/${batchId}`)}
        onRecordAnother={() => {
          setSaved(null);
          resetDraft();
        }}
      />
    );
  }

  const targetBlocker =
    targetState.kind === "unselected"
      ? "Choose the exact placement being inspected."
      : targetState.kind === "loading"
        ? "Resolving the placement…"
        : targetState.kind === "error"
          ? "The placement could not be resolved. Use Retry to load it again before inspecting."
          : targetState.kind === "missing"
            ? "That placement is not an active placement of this Batch (it may have moved, been released, or belong to another Batch). Choose an exact placement."
            : null;
  const errorLines = [
    formError,
    command.error
      ? `${friendlyMutationErrorMessage(command.error)}${command.outcome === "uncertain" ? ` ${UNCERTAIN_OUTCOME_COPY}` : ""}`
      : null,
  ].filter((b): b is string => Boolean(b));
  const showTargetPicker = !urlAssignmentId || targetState.kind === "missing" || chosenAssignmentId !== null;
  const requiredDue = dueRequirements.filter((r) => r.requirement.requirement_level === "required");
  const enteredCount = dueRequirements.filter((r) => (observationRows[r.requirement.observation_definition_id] ?? "").trim() !== "").length;

  const header = (
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
  );

  const context = (
    <div className="mb-4">
      <ContextStrip>
        <ContextStripFact
          label="Batch"
          value={`${batch.code} — ${batch.crop.common_name}${batch.variety ? ` / ${batch.variety.name}` : ""}`}
        />
        <ContextStripFact label="Stage" value={batch.current_stage.name} />
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-wl-text-secondary">Exact placement</span>
          {resolvedTarget ? (
            <span className="text-sm font-medium text-wl-text" data-testid="inspection-target">
              {resolvedTarget.carrier.code}
              {resolvedTarget.location_label ? ` — ${resolvedTarget.location_label}` : " — no current location on record"}
            </span>
          ) : (
            <span className="text-sm font-medium text-wl-flag-fg">
              {targetState.kind === "loading" ? "Resolving…" : "Not selected"}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-wl-text-secondary">Protocol</span>
          {status?.protocol ? (
            <StatusBadge label={`${status.protocol.name} v${status.protocol_version?.version_number}`} tone="active" />
          ) : (
            <StatusBadge label={statusQuery.isLoading ? "Loading…" : "No protocol assigned"} tone="neutral" />
          )}
        </div>
      </ContextStrip>
    </div>
  );

  if (step === "review" && draft) {
    const reviewTarget = draft.target;
    const reviewPayload = draft.payload;
    const reviewContext = (
      <div className="mb-4">
        <ContextStrip>
          <ContextStripFact
            label="Batch"
            value={`${batch.code} — ${batch.crop.common_name}${batch.variety ? ` / ${batch.variety.name}` : ""}`}
          />
          <ContextStripFact label="Stage" value={batch.current_stage.name} />
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-wl-text-secondary">Exact placement</span>
            <span className="text-sm font-medium text-wl-text" data-testid="inspection-target">
              {reviewTarget.carrier.code}
              {reviewTarget.location_label ? ` — ${reviewTarget.location_label}` : " — no current location on record"}
            </span>
          </div>
        </ContextStrip>
      </div>
    );
    return (
      <div>
        {header}
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-wl-brand">Step 2 of 2 · Review</p>
        {reviewContext}
        <SplitWorkspace
          main={
            <div className="flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <h2 className="font-serif text-base font-semibold text-wl-text">Review before recording</h2>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-wl-text-secondary">Batch</dt>
                  <dd className="font-medium text-wl-text">{batch.code}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Carrier</dt>
                  <dd className="font-medium text-wl-text">{reviewTarget.carrier.code}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Location</dt>
                  <dd className="font-medium text-wl-text">{reviewTarget.location_label ?? "No current location on record"}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Inspected count</dt>
                  <dd className="font-medium tabular-nums text-wl-text">{reviewPayload.inspected_count ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Assessment</dt>
                  <dd className="font-medium text-wl-text">{humanize(reviewPayload.overall_assessment)}</dd>
                </div>
                <div>
                  <dt className="text-wl-text-secondary">Occurs at</dt>
                  <dd className="font-medium text-wl-text">Now (server time on record)</dd>
                </div>
              </dl>

              <section>
                <h3 className="mb-1 text-sm font-semibold text-wl-text">Observations ({reviewPayload.observation_values?.length ?? 0})</h3>
                {(reviewPayload.observation_values ?? []).length === 0 ? (
                  <p className="text-sm text-wl-text-secondary">None entered.</p>
                ) : (
                  <ul className="divide-y divide-wl-border text-sm">
                    {(reviewPayload.observation_values ?? []).map((v) => {
                      const req = dueRequirements.find((r) => r.requirement.observation_definition_id === v.observation_definition_id);
                      const value = v.value_integer ?? v.value_decimal ?? (v.value_boolean == null ? v.value_text : v.value_boolean ? "Yes" : "No");
                      return (
                        <li key={v.observation_definition_id} className="flex justify-between gap-3 py-1.5">
                          <span className="text-wl-text">{req?.observation_definition_name ?? "Observation"}</span>
                          <span className="font-medium text-wl-text">
                            {String(value)}
                            {definitionsById.get(v.observation_definition_id)?.unit ? ` ${definitionsById.get(v.observation_definition_id)?.unit}` : ""}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="mb-1 text-sm font-semibold text-wl-text">Findings ({reviewPayload.findings?.length ?? 0})</h3>
                {(reviewPayload.findings ?? []).length === 0 ? (
                  <p className="text-sm text-wl-text-secondary">No findings.</p>
                ) : (
                  <BoundedDataRegion label="Findings to record">
                    <ul className="divide-y divide-wl-border px-3 text-sm">
                      {(reviewPayload.findings ?? []).map((f, i) => (
                        <li key={i} className="flex flex-col gap-0.5 py-2">
                          <span className="font-medium text-wl-text">
                            {humanize(f.category)} · {humanize(f.severity)} · Affected {f.affected_count ?? "—"}
                          </span>
                          {f.suspected_cause && <span className="text-xs text-wl-text-secondary">Suspected cause: {f.suspected_cause}</span>}
                          {f.notes && <span className="text-xs text-wl-text-secondary">{f.notes}</span>}
                        </li>
                      ))}
                    </ul>
                  </BoundedDataRegion>
                )}
              </section>

              <section>
                <h3 className="mb-1 text-sm font-semibold text-wl-text">Notes</h3>
                <p className="text-sm text-wl-text">{reviewPayload.notes ?? "—"}</p>
              </section>
            </div>
          }
          rail={
            <section aria-label="Inspection summary" className="flex flex-col gap-3 rounded-xl border border-wl-border bg-wl-surface-raised p-4">
              <h2 className="text-sm font-semibold text-wl-text">Record this inspection</h2>
              <p className="text-xs text-wl-text-secondary">
                Recording never changes living quantity or opens a Crop Issue by itself.
              </p>
              <StickyActionBar
                blockers={
                  errorLines.length > 0 && (
                    <ul role="alert" className={blockerListClass}>
                      {errorLines.map((b) => (
                        <li key={b}>{b}</li>
                      ))}
                    </ul>
                  )
                }
              >
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setStep("configure")} disabled={locked}>
                    Back to edit
                  </Button>
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={recordInspectionCommand}
                    disabled={command.outcome === "submitting"}
                  >
                    {command.outcome === "submitting"
                      ? "Recording…"
                      : command.outcome === "uncertain"
                        ? "Retry"
                        : "Record Inspection"}
                  </Button>
                </div>
              </StickyActionBar>
            </section>
          }
        />
      </div>
    );
  }

  const configureBlockers = [targetBlocker, ...errorLines].filter((b): b is string => Boolean(b));

  return (
    <div>
      {header}
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-wl-brand">Step 1 of 2 · Configure</p>
      {context}

      <SplitWorkspace
        main={
          <fieldset disabled={locked} className="flex min-w-0 flex-col gap-4">
            {/* Always offered when the placement read fails -- including for
                a valid deep-linked assignment, where the picker is hidden. */}
            {targetsQuery.isError && (
              <ErrorState error={targetsQuery.error} onRetry={() => targetsQuery.refetch()} />
            )}
            {showTargetPicker && !targetsQuery.isError && (
              <section className="rounded-xl border border-wl-border bg-wl-surface-raised p-4">
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>Exact placement being inspected (required)</span>
                  <select
                    className={inputClass}
                    value={resolvedTarget?.id ?? ""}
                    disabled={targetsQuery.isLoading}
                    onChange={(e) => chooseTarget(e.target.value)}
                  >
                    <option value="">{targetsQuery.isLoading ? "Loading placements…" : "Select a placement…"}</option>
                    {targets.map((t) => (
                      <option key={t.id} value={t.id}>
                        {targetLabel(t)}
                      </option>
                    ))}
                  </select>
                </label>
                {targetsQuery.isSuccess && targets.length === 0 && (
                  <p className="mt-2 text-xs text-wl-text-secondary">This Batch has no active placements to inspect.</p>
                )}
                <p className="mt-2 text-xs text-wl-text-secondary">Changing the placement clears this draft.</p>
              </section>
            )}

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
                    const raw = observationRows[r.requirement.observation_definition_id] ?? "";
                    const setRaw = (value: string) =>
                      setObservationRows((prev) => ({ ...prev, [r.requirement.observation_definition_id]: value }));
                    return (
                      <div
                        key={r.requirement.id}
                        className="grid grid-cols-1 items-center gap-2 rounded-lg border border-wl-border p-2.5 sm:grid-cols-[1fr_auto]"
                      >
                        <label className="flex flex-col gap-1">
                          <span className={labelClass}>
                            {r.observation_definition_name}
                            {definition?.unit ? ` (${definition.unit})` : ""}
                            {r.requirement.requirement_level === "required" ? " · required" : " · recommended"}
                          </span>
                          {definition?.value_type === "boolean" ? (
                            <select className={inputClass} value={raw} onChange={(e) => setRaw(e.target.value)}>
                              <option value="">Not observed</option>
                              <option value="true">Yes</option>
                              <option value="false">No</option>
                            </select>
                          ) : definition?.value_type === "text" ? (
                            <input className={inputClass} value={raw} onChange={(e) => setRaw(e.target.value)} />
                          ) : (
                            <input type="number" className={inputClass} value={raw} onChange={(e) => setRaw(e.target.value)} />
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
                <dt className="text-wl-text-secondary">Placement</dt>
                <dd className="text-right font-semibold text-wl-text">{resolvedTarget?.carrier.code ?? "—"}</dd>
              </div>
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
            <StickyActionBar
              blockers={
                configureBlockers.length > 0 && (
                  <ul role="alert" className={blockerListClass}>
                    {configureBlockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                )
              }
            >
              <Button variant="primary" className="w-full" onClick={goToReview} disabled={!resolvedTarget || locked}>
                Review Inspection
              </Button>
            </StickyActionBar>
          </section>
        }
      />
    </div>
  );
}

/** UX-OPS-001C/R1: rendered from the authoritative server response. The
 * carrier comes from the Batch's own target read for the response's
 * `batch_carrier_assignment_id`; the location is the snapshot the server
 * stored (`location_id`), resolved through the generic location-path read;
 * the observation count is read back from the recorded ObservationEvent. */
function InspectionReceipt({
  farmId,
  batchId,
  batchCode,
  inspection,
  target,
  onDone,
  onRecordAnother,
}: {
  farmId: string;
  batchId: string;
  batchCode: string;
  inspection: GrowerInspectionRead;
  target: ObservationTargetRead | null;
  onDone: () => void;
  onRecordAnother: () => void;
}) {
  const router = useRouter();
  const openIssue = useOpenCropIssue(farmId, batchId);
  const locationQuery = useLocationPath(farmId, inspection.location_id);
  const historyQuery = useObservationHistory(farmId, inspection.observation_event_id ? batchId : null);
  const recordedEvent = (historyQuery.data ?? []).find((e) => e.id === inspection.observation_event_id);
  const receiptCarrier =
    target && target.id === inspection.batch_carrier_assignment_id ? target.carrier.code : null;

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
  // Same frozen-command rules as Record Inspection: an uncertain Open Issue
  // keeps its id + payload for Retry and can't be cancelled.
  const issueCommand = useFrozenSubmission<CropIssueOpenIn & Record<string, unknown>>();
  const issueLocked = issueCommand.outcome !== "editing";

  function sendOpenIssue(payload: CropIssueOpenIn) {
    openIssue.mutateAsync(payload).then(
      (issue) => {
        issueCommand.handleSuccess();
        router.push(`/farms/${farmId}/crop-issues/${issue.id}`);
      },
      (error) => issueCommand.handleError(toCommandError(error)),
    );
  }

  function handleOpenIssue() {
    if (issueCommand.outcome === "uncertain") {
      const payload = issueCommand.retry();
      if (payload) sendOpenIssue(payload);
      return;
    }
    if (!description.trim()) return;
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

  return (
    <div>
      <PageHeader compact title="Inspection recorded" />
      <div role="status" className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
        <p className="text-sm text-wl-text">
          Inspection saved with {inspection.findings.length} finding{inspection.findings.length === 1 ? "" : "s"}.
        </p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-wl-text-secondary">Batch</dt>
            <dd className="font-medium text-wl-text">{batchCode}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Carrier / placement</dt>
            <dd className="font-medium text-wl-text">{receiptCarrier ?? (inspection.batch_carrier_assignment_id ? "Recorded placement" : "—")}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Location (stored snapshot)</dt>
            <dd className="font-medium text-wl-text">
              {!inspection.location_id
                ? "No location on record"
                : locationQuery.data?.path_string ?? (locationQuery.isLoading ? "Loading…" : "Unavailable")}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Recorded at</dt>
            <dd className="font-medium text-wl-text">{new Date(inspection.effective_time).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Assessment</dt>
            <dd className="font-medium text-wl-text">{humanize(inspection.overall_assessment)}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Inspected</dt>
            <dd className="font-medium tabular-nums text-wl-text">{inspection.inspected_count ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Observations</dt>
            <dd className="font-medium tabular-nums text-wl-text">
              {!inspection.observation_event_id
                ? 0
                : recordedEvent
                  ? recordedEvent.values.length
                  : historyQuery.isLoading
                    ? "Loading…"
                    : "Recorded"}
            </dd>
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
          <fieldset disabled={issueLocked} className="flex flex-col gap-3 rounded-lg border border-wl-border p-3">
            <legend className="px-1 text-sm font-medium text-wl-text">Open Crop Issue</legend>
            {inspection.findings.length > 1 && (
              <label className="flex flex-col gap-1">
                <span className={labelClass}>From finding</span>
                <select
                  className={inputClass}
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
              <textarea className={`${inputClass} min-h-16`} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelClass}>Suspected cause (optional)</span>
              <input className={inputClass} value={suspectedCause} onChange={(e) => setSuspectedCause(e.target.value)} />
            </label>
          </fieldset>
        )}
        {openingIssue && (
          <>
            {issueCommand.error && (
              <p role="alert" className="text-xs text-danger-700">
                {friendlyMutationErrorMessage(issueCommand.error)}
                {issueCommand.outcome === "uncertain" && ` ${UNCERTAIN_OUTCOME_COPY}`}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  issueCommand.abandon();
                  setOpeningIssue(false);
                }}
                // Never abandon an in-flight or unresolved Open Issue.
                disabled={issueLocked}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleOpenIssue}
                disabled={issueCommand.outcome === "submitting" || (!issueLocked && !description.trim())}
              >
                {issueCommand.outcome === "submitting"
                  ? "Opening…"
                  : issueCommand.outcome === "uncertain"
                    ? "Retry"
                    : "Open Issue"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
