import type { GreenhouseOverviewItem } from "@/lib/api/client";

const CLASSIFICATION_LABELS: Record<string, string> = {
  nursery: "Nursery",
  leafy_greens: "Leafy Greens",
  vines: "Vines",
};

export function classificationLabel(classification: string): string {
  return CLASSIFICATION_LABELS[classification] ?? classification;
}

const STATUS_LABELS: Record<string, string> = {
  empty: "Empty",
  partial: "Partially configured",
  configured: "Configured",
};

export function setupStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/** One human-readable line summarizing an already-configured structure,
 * e.g. "2 Zones · 4 Spans · 12 Tables" -- every number comes straight from
 * `item.counts`, never fabricated or estimated. Zero-count groups are
 * omitted (a Vines greenhouse never mentions "0 Tables"). */
export function structureSummaryLine(item: GreenhouseOverviewItem): string {
  const { counts, classification } = item;
  const parts: string[] = [];
  if (counts.zones > 0) parts.push(`${counts.zones} ${counts.zones === 1 ? "Zone" : "Zones"}`);
  if (counts.spans > 0) parts.push(`${counts.spans} ${counts.spans === 1 ? "Span" : "Spans"}`);

  if (classification === "leafy_greens") {
    if (counts.tables > 0) parts.push(`${counts.tables} ${counts.tables === 1 ? "Table" : "Tables"}`);
  } else if (classification === "vines") {
    if (counts.gutters > 0) parts.push(`${counts.gutters} ${counts.gutters === 1 ? "Gutter" : "Gutters"}`);
    if (counts.bag_positions > 0) parts.push(`${counts.bag_positions.toLocaleString()} Bag Positions`);
  } else {
    if (counts.seeding_stations > 0) parts.push("Seeding Station");
    if (counts.germination_chambers > 0) parts.push("Germination Chamber");
    if (counts.seedling_tables > 0) parts.push(`${counts.seedling_tables} Seedling Tables`);
    if (counts.intersalads_tables > 0) parts.push(`${counts.intersalads_tables} InterSalads Tables`);
    if (counts.intervines_tables > 0) parts.push(`${counts.intervines_tables} InterVines Tables`);
  }

  // FARM-SETUP-001.2 section 9: Trolleys/Seeding Machines are farm-level
  // equipment, not Nursery structure -- kept out of the structural summary
  // line entirely (never blended indistinguishably with Seedling/
  // InterSalads/InterVines counts) and, when present, appended as its own
  // clearly-labeled clause so proximity/formatting never implies ownership.
  const equipmentParts: string[] = [];
  if (classification === "nursery" && counts.trolleys > 0) {
    equipmentParts.push(`${counts.trolleys} ${counts.trolleys === 1 ? "Trolley" : "Trolleys"}`);
  }
  if (classification === "nursery" && counts.seeding_machines > 0) {
    equipmentParts.push(`${counts.seeding_machines} Seeding Machines`);
  }

  const structureLine = parts.length > 0 ? parts.join(" · ") : "No structure configured yet";
  if (equipmentParts.length === 0) return structureLine;
  return `${structureLine} · ${equipmentParts.join(", ")} registered (farm-level equipment)`;
}
