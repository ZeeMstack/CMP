"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import {
  tableBodyDividerClass,
  tableHeadRowClass,
  tableRowHoverClass,
  tableTdClass,
  tableThClass,
  tableWrapperClass,
} from "@/components/ui/table";
import { humanizeEnumCode } from "@/lib/format/humanize";
import { AppError } from "@/lib/errors/adapter";
import {
  useActivateProtocolVersion,
  useAddProtocolCareActivity,
  useAddProtocolObservationRequirement,
  useGrowingProtocol,
  useObservationDefinitions,
  useProtocolCareActivities,
  useProtocolObservationRequirements,
  useProtocolVersion,
  useRetireProtocolVersion,
} from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

const STAGE_CATEGORIES = [
  "seeding", "germination", "nursery", "transplanting", "intermediate", "production",
  "harvest_ready", "harvesting", "completed", "rejected",
] as const;
const REQUIREMENT_LEVELS = ["required", "recommended"] as const;
const CARE_ACTIVITY_TYPES = [
  "inspect_roots", "scout_pests", "pruning", "training", "spacing", "crop_hygiene",
  "transfer_readiness", "harvest_readiness", "other",
] as const;

const inputClass =
  "min-h-10 rounded-md border border-wl-border bg-wl-surface px-2.5 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

export default function ProtocolVersionEditorPage() {
  const { protocolId, versionId } = useParams<{ protocolId: string; versionId: string }>();
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingActivate, setConfirmingActivate] = useState(false);

  const protocolQuery = useGrowingProtocol(protocolId);
  const versionQuery = useProtocolVersion(protocolId, versionId);
  const requirementsQuery = useProtocolObservationRequirements(protocolId, versionId);
  const activitiesQuery = useProtocolCareActivities(protocolId, versionId);
  const definitionsQuery = useObservationDefinitions();
  const definitionsById = new Map((definitionsQuery.data ?? []).map((d) => [d.id, d]));
  const activate = useActivateProtocolVersion(protocolId);
  const retire = useRetireProtocolVersion(protocolId);

  if (versionQuery.isLoading || protocolQuery.isLoading) {
    return (
      <StandaloneShell>
        <LoadingSkeleton rows={4} label="Loading protocol version" />
      </StandaloneShell>
    );
  }
  if (versionQuery.error) {
    return (
      <StandaloneShell>
        <ErrorState error={versionQuery.error} onRetry={() => versionQuery.refetch()} />
      </StandaloneShell>
    );
  }
  const version = versionQuery.data;
  const protocol = protocolQuery.data;
  if (!version || !protocol) return null;

  const isDraft = version.state === "draft";

  async function handleActivate() {
    setActionError(null);
    try {
      await activate.mutateAsync({ versionId, payload: { client_command_id: crypto.randomUUID() } });
      setConfirmingActivate(false);
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  async function handleRetire() {
    setActionError(null);
    if (!window.confirm(`Retire version ${version?.version_number}? This cannot be undone.`)) return;
    try {
      await retire.mutateAsync({ versionId, payload: { client_command_id: crypto.randomUUID() } });
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={`${protocol.name} — Version ${version.version_number}`}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Growing Protocols", href: "/growing-protocols" },
              { label: protocol.code, href: `/growing-protocols/${protocolId}` },
              { label: `v${version.version_number}` },
            ]}
          />
        }
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge label={version.state} tone={version.state === "active" ? "active" : version.state === "draft" ? "attention" : "closed"} />
            {isDraft && !confirmingActivate && (
              <Button variant="primary" onClick={() => setConfirmingActivate(true)}>
                Activate
              </Button>
            )}
            {version.state === "active" && (
              <Button variant="secondary" onClick={handleRetire} disabled={retire.isPending}>
                {retire.isPending ? "Retiring…" : "Retire"}
              </Button>
            )}
          </div>
        }
      />

      {actionError && (
        <p role="alert" className="mb-4 text-xs text-danger-700">
          {actionError}
        </p>
      )}

      {confirmingActivate && (
        <div className="mb-6 rounded-lg border border-wl-border-strong bg-wl-hold-bg p-4 text-sm text-wl-hold-fg">
          <p className="font-medium">
            Activating this version retires the currently active version. Existing Batch assignments are not
            automatically changed.
          </p>
          <div className="mt-3 flex gap-2">
            <Button variant="secondary" onClick={() => setConfirmingActivate(false)} disabled={activate.isPending}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleActivate} disabled={activate.isPending}>
              {activate.isPending ? "Activating…" : "Confirm Activate"}
            </Button>
          </div>
        </div>
      )}

      {/* A. Version metadata */}
      <section className="mb-8">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Version</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-wl-text-secondary">Reason</dt>
            <dd className="text-sm text-wl-text">{version.reason}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Effective date</dt>
            <dd className="text-sm text-wl-text">{version.effective_date ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-wl-text-secondary">Created</dt>
            <dd className="text-sm text-wl-text">{new Date(version.created_at).toLocaleDateString()}</dd>
          </div>
        </dl>
      </section>

      {/* B. Observation requirements */}
      <section className="mb-8">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">
          Observation requirements
        </h2>
        {requirementsQuery.isLoading && <LoadingSkeleton rows={2} label="Loading observation requirements" />}
        {requirementsQuery.error && <ErrorState error={requirementsQuery.error} onRetry={() => requirementsQuery.refetch()} />}
        {requirementsQuery.data && requirementsQuery.data.length === 0 && (
          <p className="mb-3 text-sm text-wl-text-secondary">No observation requirements yet.</p>
        )}
        {requirementsQuery.data && requirementsQuery.data.length > 0 && (
          <div className={`${tableWrapperClass} mb-3`}>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className={tableHeadRowClass}>
                  <th className={tableThClass}>Stage</th>
                  <th className={tableThClass}>Occurrence</th>
                  <th className={tableThClass}>Observation</th>
                  <th className={tableThClass}>Level</th>
                  <th className={tableThClass}>Frequency (days)</th>
                  <th className={tableThClass}>Due window (days)</th>
                </tr>
              </thead>
              <tbody className={tableBodyDividerClass}>
                {requirementsQuery.data.map((r) => (
                  <tr key={r.id} className={tableRowHoverClass}>
                    <td className={tableTdClass}>{humanizeEnumCode(r.stage_category)}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{r.stage_sequence_index ?? "Every"}</td>
                    <td className={`${tableTdClass} font-medium text-wl-text`}>
                      {definitionsById.get(r.observation_definition_id)?.name ?? "—"}
                    </td>
                    <td className={tableTdClass}>{humanizeEnumCode(r.requirement_level)}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{r.frequency_days ?? "—"}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>
                      {r.due_window_start_days ?? "—"}–{r.due_window_end_days ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {isDraft && <AddObservationRequirementForm protocolId={protocolId} versionId={versionId} />}
      </section>

      {/* C. Crop-care activities */}
      <section className="mb-8">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-wl-text-secondary">Crop-care activities</h2>
        {activitiesQuery.isLoading && <LoadingSkeleton rows={2} label="Loading care activities" />}
        {activitiesQuery.error && <ErrorState error={activitiesQuery.error} onRetry={() => activitiesQuery.refetch()} />}
        {activitiesQuery.data && activitiesQuery.data.length === 0 && (
          <p className="mb-3 text-sm text-wl-text-secondary">No care activities yet.</p>
        )}
        {activitiesQuery.data && activitiesQuery.data.length > 0 && (
          <div className={`${tableWrapperClass} mb-3`}>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className={tableHeadRowClass}>
                  <th className={tableThClass}>Stage</th>
                  <th className={tableThClass}>Occurrence</th>
                  <th className={tableThClass}>Activity</th>
                  <th className={tableThClass}>Title</th>
                  <th className={tableThClass}>Frequency (days)</th>
                </tr>
              </thead>
              <tbody className={tableBodyDividerClass}>
                {activitiesQuery.data.map((a) => (
                  <tr key={a.id} className={tableRowHoverClass}>
                    <td className={tableTdClass}>{humanizeEnumCode(a.stage_category)}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{a.stage_sequence_index ?? "Every"}</td>
                    <td className={tableTdClass}>{humanizeEnumCode(a.activity_type)}</td>
                    <td className={`${tableTdClass} font-medium text-wl-text`}>{a.title}</td>
                    <td className={`${tableTdClass} text-wl-text-secondary`}>{a.frequency_days ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {isDraft && <AddCareActivityForm protocolId={protocolId} versionId={versionId} />}
      </section>
    </StandaloneShell>
  );
}

function AddObservationRequirementForm({ protocolId, versionId }: { protocolId: string; versionId: string }) {
  const definitionsQuery = useObservationDefinitions();
  const addRequirement = useAddProtocolObservationRequirement(protocolId, versionId);
  const [stageCategory, setStageCategory] = useState<(typeof STAGE_CATEGORIES)[number]>("production");
  const [definitionId, setDefinitionId] = useState("");
  const [level, setLevel] = useState<(typeof REQUIREMENT_LEVELS)[number]>("required");
  const [frequencyDays, setFrequencyDays] = useState("");
  const [dueWindowEnd, setDueWindowEnd] = useState("");
  const [escalation, setEscalation] = useState("");
  const [error, setError] = useState<string | null>(null);

  const definitions = definitionsQuery.data ?? [];

  async function handleAdd() {
    setError(null);
    if (!definitionId) {
      setError("Choose an observation definition.");
      return;
    }
    try {
      await addRequirement.mutateAsync({
        stage_category: stageCategory,
        observation_definition_id: definitionId,
        requirement_level: level,
        frequency_days: frequencyDays ? Number(frequencyDays) : null,
        due_window_start_days: null,
        due_window_end_days: dueWindowEnd ? Number(dueWindowEnd) : null,
        stage_sequence_index: null,
        instructions: null,
        escalation_guidance: escalation.trim() || null,
        display_order: 0,
      });
      setDefinitionId("");
      setFrequencyDays("");
      setDueWindowEnd("");
      setEscalation("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-wl-border p-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Stage</span>
        <select value={stageCategory} onChange={(e) => setStageCategory(e.target.value as typeof stageCategory)} className={inputClass}>
          {STAGE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {humanizeEnumCode(c)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Observation</span>
        <select value={definitionId} onChange={(e) => setDefinitionId(e.target.value)} className={inputClass}>
          <option value="">Select…</option>
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {d.unit ? ` (${d.unit})` : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Level</span>
        <select value={level} onChange={(e) => setLevel(e.target.value as typeof level)} className={inputClass}>
          {REQUIREMENT_LEVELS.map((l) => (
            <option key={l} value={l}>
              {humanizeEnumCode(l)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Frequency (days)</span>
        <input value={frequencyDays} onChange={(e) => setFrequencyDays(e.target.value)} className={`${inputClass} w-24`} inputMode="numeric" />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Due window end (days)</span>
        <input value={dueWindowEnd} onChange={(e) => setDueWindowEnd(e.target.value)} className={`${inputClass} w-28`} inputMode="numeric" />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Escalation guidance (optional)</span>
        <input value={escalation} onChange={(e) => setEscalation(e.target.value)} className={`${inputClass} w-48`} />
      </label>
      <Button variant="secondary" onClick={handleAdd} disabled={addRequirement.isPending}>
        {addRequirement.isPending ? "Adding…" : "Add"}
      </Button>
      {error && <p className="w-full text-xs text-danger-700">{error}</p>}
    </div>
  );
}

function AddCareActivityForm({ protocolId, versionId }: { protocolId: string; versionId: string }) {
  const addActivity = useAddProtocolCareActivity(protocolId, versionId);
  const [stageCategory, setStageCategory] = useState<(typeof STAGE_CATEGORIES)[number]>("production");
  const [activityType, setActivityType] = useState<(typeof CARE_ACTIVITY_TYPES)[number]>("scout_pests");
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [frequencyDays, setFrequencyDays] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleAdd() {
    setError(null);
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    try {
      await addActivity.mutateAsync({
        stage_category: stageCategory,
        activity_type: activityType,
        title: title.trim(),
        instructions: instructions.trim() || null,
        frequency_days: frequencyDays ? Number(frequencyDays) : null,
        stage_sequence_index: null,
        display_order: 0,
      });
      setTitle("");
      setInstructions("");
      setFrequencyDays("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-wl-border p-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Stage</span>
        <select value={stageCategory} onChange={(e) => setStageCategory(e.target.value as typeof stageCategory)} className={inputClass}>
          {STAGE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {humanizeEnumCode(c)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Activity</span>
        <select value={activityType} onChange={(e) => setActivityType(e.target.value as typeof activityType)} className={inputClass}>
          {CARE_ACTIVITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {humanizeEnumCode(t)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputClass} w-40`} />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Instructions (optional)</span>
        <input value={instructions} onChange={(e) => setInstructions(e.target.value)} className={`${inputClass} w-48`} />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-wl-text-secondary">Frequency (days)</span>
        <input value={frequencyDays} onChange={(e) => setFrequencyDays(e.target.value)} className={`${inputClass} w-24`} inputMode="numeric" />
      </label>
      <Button variant="secondary" onClick={handleAdd} disabled={addActivity.isPending}>
        {addActivity.isPending ? "Adding…" : "Add"}
      </Button>
      {error && <p className="w-full text-xs text-danger-700">{error}</p>}
    </div>
  );
}
