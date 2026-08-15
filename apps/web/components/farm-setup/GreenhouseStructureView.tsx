"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import type { GreenhouseStructureRead } from "@/lib/api/client";

/** A collapsed-by-default branch -- large commercial structures (a Vines
 * greenhouse can have thousands of Grow Bag Positions) must never render
 * fully expanded on load. Only the top level (Zones) starts expanded. */
function Branch({ label, defaultExpanded, children }: { label: ReactNode; defaultExpanded: boolean; children: ReactNode }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <li>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex min-h-11 w-full items-center gap-2 rounded px-1 text-left hover:bg-surface-subtle"
      >
        <ChevronRight aria-hidden="true" className={`h-4 w-4 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`} />
        <span className="text-sm text-ink">{label}</span>
      </button>
      {expanded && <ul className="ml-6 border-l border-border-subtle pl-3">{children}</ul>}
    </li>
  );
}

function Leaf({ label }: { label: ReactNode }) {
  return <li className="flex min-h-11 items-center px-1 text-sm text-ink-muted">{label}</li>;
}

export function GreenhouseStructureView({ structure }: { structure: GreenhouseStructureRead }) {
  if (structure.leafy_zones) {
    return (
      <ul role="tree" aria-label="Greenhouse structure" className="divide-y divide-border-subtle">
        {structure.leafy_zones.map((zone) => (
          <Branch key={zone.id} label={`Zone ${zone.code}`} defaultExpanded>
            {zone.spans.map((span) => (
              <Branch key={span.id} label={`Span ${span.code} · ${span.tables.length} tables`} defaultExpanded={false}>
                {span.tables.map((table) => (
                  <Leaf key={table.id} label={`Table ${table.code}${table.capacity != null ? ` — capacity ${table.capacity}` : ""}`} />
                ))}
              </Branch>
            ))}
          </Branch>
        ))}
      </ul>
    );
  }

  if (structure.vines_zones) {
    return (
      <ul role="tree" aria-label="Greenhouse structure" className="divide-y divide-border-subtle">
        {structure.vines_zones.map((zone) => (
          <Branch key={zone.id} label={`Zone ${zone.code}`} defaultExpanded>
            {zone.spans.map((span) => (
              <Branch key={span.id} label={`Span ${span.code} · ${span.gutters.length} gutters`} defaultExpanded={false}>
                {span.gutters.map((gutter) => (
                  <Leaf key={gutter.id} label={`Gutter ${gutter.code} · ${gutter.bag_position_count} bag positions`} />
                ))}
              </Branch>
            ))}
          </Branch>
        ))}
      </ul>
    );
  }

  // Nursery
  const seedingStations = structure.nursery_seeding_stations ?? [];
  const sections = [
    { label: "Germination Chamber", section: structure.nursery_germination_chamber },
  ].filter((s) => s.section != null);
  const groups: { label: string; group: typeof structure.nursery_seedling }[] = [
    { label: "Seedling", group: structure.nursery_seedling },
    { label: "InterSalads", group: structure.nursery_intersalads },
    { label: "InterVines", group: structure.nursery_intervines },
  ];
  const nonEmpty = groups.filter((g) => g.group && g.group.tables.length > 0);
  if (seedingStations.length === 0 && sections.length === 0 && nonEmpty.length === 0) {
    return <p className="text-sm text-ink-muted">No structure configured yet.</p>;
  }
  return (
    <ul role="tree" aria-label="Greenhouse structure" className="divide-y divide-border-subtle">
      {seedingStations.map((station) => (
        <Leaf key={station.id} label={`Seeding Station · ${station.code}`} />
      ))}
      {sections.map(({ label, section }) => (
        <Leaf key={label} label={`${label} · ${section!.code}`} />
      ))}
      {nonEmpty.map(({ label, group }) => (
        <Branch key={label} label={`${label} · ${group!.tables.length} tables`} defaultExpanded>
          {group!.tables.map((table) => (
            <Leaf key={table.id} label={`Table ${table.code}${table.capacity != null ? ` — capacity ${table.capacity}` : ""}`} />
          ))}
        </Branch>
      ))}
    </ul>
  );
}
