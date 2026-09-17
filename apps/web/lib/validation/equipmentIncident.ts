import { z } from "zod";

import type { EquipmentIncidentOpenIn } from "@/lib/api/client";

/** PILOT-ASSET-001: Report Incident form. `asset_id` is always required
 * (every Incident is equipment -- a Carrier-condition problem is
 * Readiness's `report_damage`, not an Incident, per
 * docs/domain/EQUIPMENT_READINESS_MODEL.md). `potentially_impacted_location_id`
 * is a second, independently-optional location field -- NEVER aliased from
 * `location_id` and NEVER labeled "Affected crop" in the UI. */
export const equipmentIncidentSeverityOptions = ["low", "medium", "high", "critical"] as const;
export const equipmentIncidentCategoryOptions = [
  "cooling", "ventilation", "irrigation_water", "fertigation_dosing", "ro_plant",
  "reservoir", "germination_chamber", "seeding_equipment", "scale", "cold_store", "other",
] as const;

/** Human-readable labels for the fixed category list -- deliberately not
 * run through `humanizeEnumCode` (it would render "ro_plant" as "Ro
 * plant"/"cold_store" as "Cold store", not the ticket's own required
 * "RO Plant"/"Cold Store" casing). */
export const EQUIPMENT_INCIDENT_CATEGORY_LABELS: Record<(typeof equipmentIncidentCategoryOptions)[number], string> = {
  cooling: "Cooling",
  ventilation: "Ventilation",
  irrigation_water: "Irrigation Water",
  fertigation_dosing: "Fertigation Dosing",
  ro_plant: "RO Plant",
  reservoir: "Reservoir",
  germination_chamber: "Germination Chamber",
  seeding_equipment: "Seeding Equipment",
  scale: "Scale",
  cold_store: "Cold Store",
  other: "Other",
};

export const equipmentIncidentFormSchema = z.object({
  assetId: z.string().min(1, "Asset is required"),
  locationId: z.string().nullable(),
  potentiallyImpactedLocationId: z.string().nullable(),
  severity: z.enum(equipmentIncidentSeverityOptions),
  category: z.enum(equipmentIncidentCategoryOptions),
  description: z.string().min(1, "Description is required"),
  detectedAt: z.string().min(1, "Detected at is required"), // datetime-local string
  notes: z.string(),
});
export type EquipmentIncidentFormValues = z.infer<typeof equipmentIncidentFormSchema>;

function nowDateTimeLocal(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export function defaultEquipmentIncidentFormValues(lockedAssetId?: string): EquipmentIncidentFormValues {
  return {
    assetId: lockedAssetId ?? "",
    locationId: null,
    potentiallyImpactedLocationId: null,
    severity: "medium",
    category: "other",
    description: "",
    detectedAt: nowDateTimeLocal(),
    notes: "",
  };
}

export function buildEquipmentIncidentOpenPayload(
  values: EquipmentIncidentFormValues,
  clientCommandId: string,
): EquipmentIncidentOpenIn {
  return {
    client_command_id: clientCommandId,
    asset_id: values.assetId,
    location_id: values.locationId || null,
    potentially_impacted_location_id: values.potentiallyImpactedLocationId || null,
    severity: values.severity,
    category: values.category,
    description: values.description.trim(),
    // A bare `datetime-local` value has no timezone -- interpreted as the
    // operator's own browser-local wall-clock time, mirroring
    // `buildFarmWorkItemCreatePayload`'s own `due_at` convention.
    detected_at: new Date(values.detectedAt).toISOString(),
    notes: values.notes.trim() || null,
  };
}
