import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { ProductionRequirementRead, RequirementHarvestOutlook } from "@/lib/api/client";
import { COVERAGE_STATUS_LABEL, deriveCoverageStatus } from "@/lib/format/forecastCoverage";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";

function statusTone(status: string): "active" | "closed" | "neutral" {
  if (status === "open") return "active";
  if (status === "closed") return "closed";
  return "neutral";
}

function coverageTone(status: ReturnType<typeof deriveCoverageStatus>): "attention" | "active" | "neutral" | "closed" {
  if (status === "SHORT") return "attention";
  if (status === "COVERED") return "active";
  if (status === "OVER") return "closed";
  return "neutral";
}

/** PILOT-PLAN-001B section 3: when `outlookByRequirementId` is supplied,
 * this renders the additional Forecast/Harvested/Outlook columns from the
 * `RequirementHarvestOutlook` read model -- FORECAST != DEMAND != PLANNED,
 * so these columns are always additional to (never replace) the existing
 * seeding-plan Demand/Planned/Gap columns above. When omitted (the plain
 * Requirements list use), the table renders exactly as before. */
export function RequirementsTable({
  requirements,
  farmId,
  outlookByRequirementId,
  outlookLoading,
}: {
  requirements: ProductionRequirementRead[];
  farmId: string;
  outlookByRequirementId?: Record<string, RequirementHarvestOutlook | undefined>;
  outlookLoading?: boolean;
}) {
  const showOutlook = Boolean(outlookByRequirementId);
  return (
    <div className="overflow-x-auto rounded-lg border border-wl-border">
      <table className={`w-full text-left text-sm ${showOutlook ? "min-w-[1080px]" : "min-w-[720px]"}`}>
        <thead className="bg-wl-surface-sunken text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">
          <tr>
            <th scope="col" className="px-3 py-2">Required by</th>
            <th scope="col" className="px-3 py-2">Crop</th>
            <th scope="col" className="px-3 py-2">Variety</th>
            <th scope="col" className="px-3 py-2">Demand</th>
            <th scope="col" className="px-3 py-2">Planned</th>
            <th scope="col" className="px-3 py-2">Gap</th>
            {showOutlook && (
              <>
                <th scope="col" className="px-3 py-2">Forecast (expected)</th>
                <th scope="col" className="px-3 py-2">Harvested</th>
                <th scope="col" className="px-3 py-2">Outlook</th>
              </>
            )}
            <th scope="col" className="px-3 py-2">Status</th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {requirements.map((requirement) => {
            const outlook = outlookByRequirementId?.[requirement.id];
            const coverageStatus = showOutlook ? deriveCoverageStatus(outlook) : null;
            return (
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
                {showOutlook && (
                  <>
                    <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                      {outlookLoading && !outlook ? (
                        "…"
                      ) : outlook && outlook.forecast_comparable && outlook.forecast_expected_quantity !== null ? (
                        formatQuantity(outlook.forecast_expected_quantity, requirement.uom.code)
                      ) : outlook && outlook.batches_with_current_forecast_count > 0 ? (
                        <span className="text-wl-text-secondary">Not comparable</span>
                      ) : (
                        <span className="text-wl-text-secondary">No forecast</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                      {outlookLoading && !outlook ? (
                        "…"
                      ) : outlook && outlook.actual_harvested_comparable && outlook.actual_harvested_quantity !== null ? (
                        formatQuantity(outlook.actual_harvested_quantity, requirement.uom.code)
                      ) : (
                        <span className="text-wl-text-secondary">
                          {outlook ? `Not comparable (${outlook.actual_harvested_weight_kg} kg)` : "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {coverageStatus && (
                        <StatusBadge label={COVERAGE_STATUS_LABEL[coverageStatus]} tone={coverageTone(coverageStatus)} />
                      )}
                    </td>
                  </>
                )}
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
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
