import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { tableRowHoverClass, tableTdClass } from "@/components/ui/table";
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

/** WHAT/WHERE/CONTEXT/OWNER/WHEN/STATUS/NEXT ACTION, one compact row --
 * every piece of context already resolved server-side (`FarmWorkItemRead`'s
 * nested summaries), never a second lookup by this component. The action
 * cell itself is `WorkItemActions` (extracted UX-OPS-001B R1 so the same
 * commands/payloads can be reused in a selected-item inspector without a
 * six-column table row). */
export function WorkItemRow({ item, farmId, currentUserId }: { item: FarmWorkItemRead; farmId: string; currentUserId?: string }) {
  const quantity = item.quantity && item.quantity_uom ? `${item.quantity} ${item.quantity_uom.code}` : null;
  // PILOT-OPS-001 closure: every structured context piece the Work Item
  // actually carries is shown, never just the first one -- e.g. a Batch
  // AND a Location together (ticket example: "Check Batch B-... after
  // transfer"). A context kind that doesn't apply renders no placeholder
  // at all, never an empty "—" line for it specifically.
  const hasContext = Boolean(item.crop_batch || item.location || item.asset || item.carrier || quantity);
  const isMine = currentUserId != null && item.assigned_to_user_id === currentUserId;

  return (
    <tr className={tableRowHoverClass}>
      <td className={`${tableTdClass} font-medium text-wl-text`}>
        {item.title}
        <div className="text-xs font-normal text-wl-text-secondary">{item.code}</div>
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>
        {item.crop_batch && <div>Batch {item.crop_batch.code}</div>}
        {item.location && (
          <div className={item.crop_batch ? "text-xs" : undefined}>
            {item.location.code} {item.location.name}
          </div>
        )}
        {item.asset && <div className="text-xs">{item.asset.name}</div>}
        {item.carrier && <div className="text-xs">{item.carrier.code}</div>}
        {quantity && <div className="text-xs">{quantity}</div>}
        {!hasContext && "—"}
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>
        {isMine ? "You" : item.assigned_to_user_id ? "Assigned" : "Unassigned"}
      </td>
      <td className={`${tableTdClass} text-wl-text-secondary`}>{formatDue(item.due_at)}</td>
      <td className={tableTdClass}>
        <div className="flex flex-col gap-1">
          <StatusBadge label={humanizeEnumCode(item.status)} tone={STATUS_TONE[item.status]} />
          {item.priority !== "normal" && (
            <StatusBadge label={humanizeEnumCode(item.priority)} tone={item.priority === "critical" ? "critical" : "attention"} />
          )}
        </div>
        {item.status === "blocked" && item.blocked_reason && (
          <p className="mt-1 max-w-[22ch] text-xs text-wl-hold-fg">{item.blocked_reason}</p>
        )}
      </td>
      <td className={tableTdClass}>
        {/* R2: keyed by item.id so selecting a different Work Item
            remounts WorkItemActions (and its useFrozenSubmission
            instances) from scratch -- a frozen/uncertain command for one
            item can never leak its client_command_id into another. */}
        <WorkItemActions key={item.id} item={item} farmId={farmId} currentUserId={currentUserId} />
      </td>
    </tr>
  );
}
