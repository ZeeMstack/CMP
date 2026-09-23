import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import type { EquipmentReadinessStateRead } from "@/lib/api/client";
import { primaryReadinessAction, READINESS_ACTION_LABEL } from "@/lib/format/equipmentReadinessActions";
import { humanizeEnumCode } from "@/lib/format/humanize";

export const READINESS_STATE_TONE: Record<EquipmentReadinessStateRead["current_state"], StatusTone> = {
  unknown: "neutral",
  awaiting_cleaning: "attention",
  cleaning_completed: "attention",
  ready: "active",
  damaged: "critical",
  maintenance: "attention",
  retired: "closed",
};

export function readinessDetailHref(farmId: string, state: EquipmentReadinessStateRead): string {
  const entityId = state.asset_id ?? state.carrier_id;
  return `/farms/${farmId}/equipment/${state.entity_type}/${entityId}/readiness`;
}

/** UX-OPS-001B: the Readiness queue's selected-item inspector -- compact
 * identity/type/state facts plus the ONE valid primary next action (via
 * the shared `primaryReadinessAction`, never a second copy of the
 * transition table), which links into the existing Readiness detail route
 * with `?action=` pre-opening that exact command form. A state with no
 * forward action (already blocked, or terminal) links to "Open Readiness"
 * only -- never a fabricated action. */
export function ReadinessInspector({
  state, farmId, onClose,
}: {
  state: EquipmentReadinessStateRead | null;
  farmId: string;
  onClose: () => void;
}) {
  if (!state) return <InspectorEmptyState />;

  const href = readinessDetailHref(farmId, state);
  const primary = primaryReadinessAction(state);

  return (
    <InspectorShell
      title={state.entity_code}
      subtitle={state.equipment_type_name}
      status={<StatusBadge label={humanizeEnumCode(state.current_state)} tone={READINESS_STATE_TONE[state.current_state]} />}
      onClose={onClose}
    >
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-wl-text-secondary">Kind</dt>
          <dd className="text-wl-text">{humanizeEnumCode(state.entity_type)}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Requires cleaning</dt>
          <dd className="text-wl-text">{state.requires_cleaning ? "Yes" : "No"}</dd>
        </div>
        {state.entity_type === "carrier" && (
          <div>
            <dt className="text-xs text-wl-text-secondary">In use</dt>
            <dd className="text-wl-text">{state.is_in_use ? "Yes" : "No"}</dd>
          </div>
        )}
        {state.latest_cleaning_result && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Latest cleaning result</dt>
            <dd className={state.latest_cleaning_result === "needs_rework" ? "text-wl-flag-fg" : "text-wl-text"}>
              {humanizeEnumCode(state.latest_cleaning_result)}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-wl-text-secondary">State changed</dt>
          <dd className="text-wl-text">{new Date(state.state_changed_at).toLocaleString()}</dd>
        </div>
      </dl>
      <Link
        href={primary ? `${href}?action=${primary}` : href}
        className="inline-block text-sm font-medium text-wl-brand hover:underline"
      >
        {primary ? READINESS_ACTION_LABEL[primary] : "Open Readiness"}
      </Link>
    </InspectorShell>
  );
}
