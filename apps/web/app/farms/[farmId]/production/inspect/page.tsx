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
import { Button } from "@/components/ui/Button";
import type { GrowerInspectionRead, InspectionFindingIn, InspectionObservationValueIn } from "@/lib/api/client";
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
 * which builds one `GrowerInspectionCreate` for the whole form. */
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

    recordInspection.mutate(
      {
        client_command_id: crypto.randomUUID(),
        batch_id: batchId,
        batch_carrier_assignment_id: assignmentId,
        effective_time: null,
        inspected_count: inspected,
        overall_assessment: overallAssessment,
        notes: notes.trim() || null,
        findings: findingPayloads,
        observation_values: observationValues,
      },
      { onSuccess: (result) => setSaved(result) },
    );
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

  return (
    <div>
      <PageHeader
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
      <div className="mb-6 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-wl-text">
              {batch.code} — {batch.crop.common_name}
              {batch.variety ? ` / ${batch.variety.name}` : ""}
            </p>
            <p className="mt-0.5 text-xs text-wl-text-secondary">
              Stage: {batch.current_stage.name}
              {operational && (
                <>
                  {" · "}
                  <PlacementSummary placement={operational.placement} />
                </>
              )}
              {assignmentId && " · exact placement scan preserved"}
            </p>
          </div>
          {status?.protocol ? (
            <StatusBadge
              label={`${status.protocol.name} v${status.protocol_version?.version_number}`}
              tone="active"
            />
          ) : (
            <StatusBadge label="No protocol assigned" tone="neutral" />
          )}
        </div>
      </div>

      {/* WHAT IS DUE/WRONG + RECORD ACTION */}
      <div className="flex flex-col gap-6">
        <section>
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

        <section>
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

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Findings</h2>
            <Button variant="secondary" onClick={addFinding}>
              + Add finding
            </Button>
          </div>
          {findings.length === 0 && <p className="text-sm text-wl-text-secondary">No findings recorded.</p>}
          <div className="flex flex-col gap-3">
            {findings.map((f) => (
              <div key={f.key} className="grid grid-cols-1 gap-2 rounded-lg border border-wl-border p-3 sm:grid-cols-2">
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
                    {FINDING_SEVERITIES.map((s) => (
                      <option key={s} value={s}>
                        {humanize(s)}
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
        </section>

        <section>
          <label className="flex flex-col gap-1">
            <span className={labelClass}>Notes (optional)</span>
            <textarea className={`${inputClass} min-h-20`} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </section>

        {formError && (
          <p role="alert" className="text-xs text-danger-700">
            {formError}
          </p>
        )}
        {recordInspection.error && <ErrorState error={recordInspection.error} />}

        <div>
          <Button variant="primary" onClick={handleSubmit} disabled={recordInspection.isPending}>
            {recordInspection.isPending ? "Recording…" : "Record Inspection"}
          </Button>
        </div>
      </div>
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

  async function handleOpenIssue() {
    if (!description.trim()) return;
    const issue = await openIssue.mutateAsync({
      client_command_id: crypto.randomUUID(),
      originating_grower_inspection_id: inspection.id,
      originating_finding_id: findingId || null,
      category,
      severity,
      description: description.trim(),
      suspected_cause: suspectedCause.trim() || null,
    });
    router.push(`/farms/${farmId}/crop-issues/${issue.id}`);
  }

  return (
    <div>
      <PageHeader title="Inspection recorded" />
      <div className="flex flex-col gap-4 rounded-lg border border-wl-border bg-wl-surface-raised p-4">
        <p className="text-sm text-wl-text">
          Inspection saved with {inspection.findings.length} finding{inspection.findings.length === 1 ? "" : "s"}.
        </p>

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
            {openIssue.error && <ErrorState error={openIssue.error} />}
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setOpeningIssue(false)} disabled={openIssue.isPending}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleOpenIssue} disabled={openIssue.isPending || !description.trim()}>
                {openIssue.isPending ? "Opening…" : "Open Issue"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
