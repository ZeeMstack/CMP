import type { LocationValidationResult } from "@/lib/scan/validateScanAgainstWorkingLocation";

const APPEARANCE: Record<
  Exclude<LocationValidationResult["kind"], "NO_WORKING_LOCATION">,
  { icon: string; heading: string; className: string; role: "status" | "alert" }
> = {
  MATCH_EXACT: { icon: "✓", heading: "Location confirmed", className: "border-emerald-300 bg-emerald-50 text-emerald-900", role: "status" },
  MATCH_DESCENDANT: {
    icon: "✓",
    heading: "Location confirmed",
    className: "border-emerald-300 bg-emerald-50 text-emerald-900",
    role: "status",
  },
  MISMATCH: { icon: "⚠", heading: "Location does not match", className: "border-red-300 bg-red-50 text-red-900", role: "alert" },
  CANNOT_VALIDATE: {
    icon: "?",
    heading: "Exact location cannot be confirmed",
    className: "border-amber-300 bg-amber-50 text-amber-900",
    role: "status",
  },
  HISTORICAL: { icon: "\u{1F551}", heading: "Historical placement", className: "border-slate-300 bg-slate-100 text-slate-900", role: "status" },
};

/** PILOT-SCAN-001F: compact, calm status block -- never a giant success/
 * error card, never color alone (icon + text always paired). Renders
 * nothing when there is no working location to validate against; the
 * absence of a working location is not itself a validation outcome. */
export function LocationValidationBanner({ result }: { result: LocationValidationResult }) {
  if (result.kind === "NO_WORKING_LOCATION") return null;
  const appearance = APPEARANCE[result.kind];

  return (
    <div role={appearance.role} className={`flex flex-col gap-1 rounded-md border p-3 text-sm ${appearance.className}`}>
      <p className="flex items-center gap-1.5 font-medium">
        <span aria-hidden="true">{appearance.icon}</span>
        {appearance.heading}
      </p>
      {result.kind === "MATCH_EXACT" && <p>At selected working location.</p>}
      {result.kind === "MATCH_DESCENDANT" && <p>Within selected working location.</p>}
      {result.kind === "MISMATCH" && result.reason === "different_farm" && (
        <p>This resource&apos;s current location is on a different farm than your working location.</p>
      )}
      {result.kind === "MISMATCH" && result.reason === "different_location" && (
        <p>
          Currently recorded at {result.pathString ?? "an unknown location"} — not your working location. Physical
          operations for this scan are hidden until you clear or replace your working location, or scan the correct
          item.
        </p>
      )}
      {result.kind === "CANNOT_VALIDATE" && <p>{result.reason}</p>}
      {result.kind === "HISTORICAL" && (
        <p>
          This placement is no longer active/current
          {result.pathString ? ` (last recorded at ${result.pathString})` : ""}. Historical location is shown for
          reference only — it is not valid current-location proof.
        </p>
      )}
    </div>
  );
}
