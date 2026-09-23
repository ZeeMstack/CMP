import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { WorkItemActions } from "@/components/work-items/WorkItemActions";
import type { FarmWorkItemRead } from "@/lib/api/client";
import { humanizeEnumCode } from "@/lib/format/humanize";

const STATUS_TONE: Record<FarmWorkItemRead["status"], StatusTone> = {
  open: "neutral",
  in_progress: "active",
  blocked: "attention",
  completed: "closed",
  cancelled: "closed",
};

function formatDue(dueAt: string | null): string {
  if (!dueAt) return "—";
  return new Date(dueAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** UX-OPS-001B R1: a compact, vertically-stacked Work Item fact/action
 * panel for a narrow selected-item inspector rail -- reuses `WorkItemActions`
 * verbatim (same commands/payloads/stable command identity) but never
 * embeds `WorkItemRow`'s six-column table, which does not fit a ~360px
 * rail and risks overflow on mobile. */
export function WorkItemInspectorPanel({
  item, farmId, currentUserId,
}: {
  item: FarmWorkItemRead;
  farmId: string;
  currentUserId?: string;
}) {
  const quantity = item.quantity && item.quantity_uom ? `${item.quantity} ${item.quantity_uom.code}` : null;
  const hasContext = Boolean(item.crop_batch || item.location || item.asset || item.carrier || quantity);
  const isMine = currentUserId != null && item.assigned_to_user_id === currentUserId;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge label={humanizeEnumCode(item.status)} tone={STATUS_TONE[item.status]} />
        {item.priority !== "normal" && (
          <StatusBadge label={humanizeEnumCode(item.priority)} tone={item.priority === "critical" ? "critical" : "attention"} />
        )}
      </div>
      {item.status === "blocked" && item.blocked_reason && (
        <p className="text-xs text-wl-hold-fg">{item.blocked_reason}</p>
      )}
      <dl className="flex flex-col gap-2 text-sm">
        {hasContext && (
          <div>
            <dt className="text-xs text-wl-text-secondary">Context</dt>
            <dd className="text-wl-text">
              {item.crop_batch && <div>Batch {item.crop_batch.code}</div>}
              {item.location && <div>{item.location.code} {item.location.name}</div>}
              {item.asset && <div>{item.asset.name}</div>}
              {item.carrier && <div>{item.carrier.code}</div>}
              {quantity && <div>{quantity}</div>}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-wl-text-secondary">Owner</dt>
          <dd className="text-wl-text">{isMine ? "You" : item.assigned_to_user_id ? "Assigned" : "Unassigned"}</dd>
        </div>
        <div>
          <dt className="text-xs text-wl-text-secondary">Due</dt>
          <dd className="text-wl-text">{formatDue(item.due_at)}</dd>
        </div>
      </dl>
      <div className="border-t border-wl-border pt-3">
        {/* R2: keyed by item.id -- see WorkItemRow.tsx's identical
            comment. This is the more critical of the two call sites: a
            fixed-position inspector rail is exactly where React would
            otherwise reuse the same WorkItemActions instance across a
            selection change. */}
        <WorkItemActions key={item.id} item={item} farmId={farmId} currentUserId={currentUserId} />
      </div>
    </div>
  );
}
