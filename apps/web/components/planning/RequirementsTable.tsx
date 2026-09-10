import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { ProductionRequirementRead } from "@/lib/api/client";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";

function statusTone(status: string): "active" | "closed" | "neutral" {
  if (status === "open") return "active";
  if (status === "closed") return "closed";
  return "neutral";
}

export function RequirementsTable({
  requirements,
  farmId,
}: {
  requirements: ProductionRequirementRead[];
  farmId: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-wl-border">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="bg-wl-surface-sunken text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">
          <tr>
            <th scope="col" className="px-3 py-2">Required by</th>
            <th scope="col" className="px-3 py-2">Crop</th>
            <th scope="col" className="px-3 py-2">Variety</th>
            <th scope="col" className="px-3 py-2">Demand</th>
            <th scope="col" className="px-3 py-2">Planned</th>
            <th scope="col" className="px-3 py-2">Gap</th>
            <th scope="col" className="px-3 py-2">Status</th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {requirements.map((requirement) => (
            <tr key={requirement.id} className="hover:bg-wl-surface-hover">
              <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                {formatPlanDate(requirement.required_by_date)}
              </td>
              <td className="px-3 py-2 text-wl-text">{requirement.crop.common_name}</td>
              <td className="px-3 py-2 text-wl-text-secondary">{requirement.variety?.name ?? "—"}</td>
              <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                {formatQuantity(requirement.required_quantity, requirement.uom.code)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                {formatQuantity(requirement.fulfillment.planned_coverage_quantity, requirement.uom.code)}
              </td>
              <td className="whitespace-nowrap px-3 py-2">
                {requirement.fulfillment.is_overplanned ? (
                  <span className="text-wl-grow-fg">
                    +{formatQuantity(requirement.fulfillment.overplanned_quantity, requirement.uom.code)} over
                  </span>
                ) : (
                  <span className="text-wl-text">
                    {formatQuantity(requirement.fulfillment.gap_quantity, requirement.uom.code)}
                  </span>
                )}
              </td>
              <td className="px-3 py-2">
                <StatusBadge
                  label={requirement.status[0].toUpperCase() + requirement.status.slice(1)}
                  tone={statusTone(requirement.status)}
                />
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right">
                <Link
                  href={`/farms/${farmId}/planning/requirements/${requirement.id}`}
                  className="inline-flex min-h-9 items-center rounded-md border border-wl-border-strong px-3 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
                >
                  Plan
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
