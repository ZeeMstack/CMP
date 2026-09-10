import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import type { SeedingProgramLineRead } from "@/lib/api/client";
import { formatPlanDate } from "@/lib/format/planDate";
import { formatQuantity } from "@/lib/format/planQuantity";

function lineStatusLabel(line: SeedingProgramLineRead): { label: string; tone: "active" | "closed" | "neutral" } {
  if (line.status === "cancelled") return { label: "Cancelled", tone: "neutral" };
  if (line.linked_sowing_count > 0) return { label: "Complete", tone: "closed" };
  return { label: "Planned", tone: "active" };
}

function sowNowHref(farmId: string, line: SeedingProgramLineRead): string {
  const params = new URLSearchParams({ seeding_program_line_id: line.id, crop_id: line.crop.id });
  if (line.variety) params.set("variety_id", line.variety.id);
  return `/farms/${farmId}/nursery/sowings/new?${params.toString()}`;
}

export function SeedingProgramTable({ lines, farmId }: { lines: SeedingProgramLineRead[]; farmId: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-wl-border">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="bg-wl-surface-sunken text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">
          <tr>
            <th scope="col" className="px-3 py-2">Sow date</th>
            <th scope="col" className="px-3 py-2">Crop</th>
            <th scope="col" className="px-3 py-2">Variety</th>
            <th scope="col" className="px-3 py-2">Planned sowing</th>
            <th scope="col" className="px-3 py-2">Coverage</th>
            <th scope="col" className="px-3 py-2">Actual</th>
            <th scope="col" className="px-3 py-2">Status</th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-wl-border">
          {lines.map((line) => {
            const status = lineStatusLabel(line);
            return (
              <tr key={line.id} className="hover:bg-wl-surface-hover">
                <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                  <Link
                    href={`/farms/${farmId}/planning/seeding-program-lines/${line.id}`}
                    className="hover:underline"
                  >
                    {formatPlanDate(line.planned_sow_date)}
                  </Link>
                </td>
                <td className="px-3 py-2 text-wl-text">{line.crop.common_name}</td>
                <td className="px-3 py-2 text-wl-text-secondary">{line.variety?.name ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                  {formatQuantity(line.planned_quantity, line.planned_quantity_uom.code)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-wl-text">
                  {formatQuantity(line.expected_coverage_quantity, line.expected_coverage_uom.code)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-wl-text-secondary">
                  {line.linked_sowing_count > 0 ? `Sown (${line.linked_sowing_count})` : "—"}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge label={status.label} tone={status.tone} />
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {line.status === "cancelled" ? (
                    <span className="text-sm text-wl-text-tertiary">—</span>
                  ) : (
                    <Link
                      href={sowNowHref(farmId, line)}
                      className="inline-flex min-h-9 items-center rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
                    >
                      Sow now
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
