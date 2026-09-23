import Link from "next/link";

import { InspectorEmptyState, InspectorShell } from "@/components/layout/InspectorShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import type { SeedlingBiologicalTrayRead } from "@/lib/api/client";

/** UX-OPS-001B: the Seedling selected-item inspector. Current living
 * quantity stays the authoritative, emphasized figure; Starting living
 * stays visible but historically subordinate (muted) -- the same "current
 * != starting" distinction the prior inline table enforced, never
 * recalculated or renamed here (CLAUDE.md's frozen biological-quantity
 * rule). Record/History are offered only when the row's own existing
 * eligibility fields (`assignment_active`, `is_depleted`, `event_count`)
 * say so -- never re-derived. */
export function SeedlingInspector({
  row,
  farmId,
  onRecord,
  onHistory,
  onClose,
}: {
  row: SeedlingBiologicalTrayRead | null;
  farmId: string;
  onRecord: (assignmentId: string) => void;
  onHistory: (seedlingEntryId: string) => void;
  onClose: () => void;
}) {
  if (!row) return <InspectorEmptyState />;

  const tone: StatusTone = row.is_depleted ? "attention" : row.assignment_active ? "active" : "closed";
  const label = row.is_depleted ? "Depleted" : row.assignment_active ? "Active" : "Released";

  return (
    <InspectorShell title={row.tray_code} subtitle={`Batch ${row.batch_code}`} onClose={onClose}>
      <StatusBadge label={label} tone={tone} />
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-wl-text-secondary">Starting Living</dt>
          <dd className="text-wl-text-secondary">{row.starting_living_seedling_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Current Living</dt>
          <dd className="font-semibold text-wl-text">{row.current_living_seedling_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Table</dt>
          <dd className="text-wl-text">{row.seedling_table_code ?? "—"}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap items-center gap-2 border-t border-wl-border pt-3">
        {row.assignment_active && !row.is_depleted ? (
          <Button type="button" variant="primary" onClick={() => onRecord(row.batch_carrier_assignment_id)}>
            Record disposition
          </Button>
        ) : (
          <span className="text-xs text-wl-text-secondary">No disposition action currently valid.</span>
        )}
        {row.event_count > 0 && (
          <Button type="button" variant="secondary" onClick={() => onHistory(row.seedling_entry_id)}>
            History
          </Button>
        )}
        {row.assignment_active && (
          <Link
            href={`/farms/${farmId}/labels/batch_carrier_assignment/${row.batch_carrier_assignment_id}`}
            className="text-xs font-medium text-wl-text-secondary underline hover:text-wl-text"
          >
            Reprint label
          </Link>
        )}
      </div>
    </InspectorShell>
  );
}
