"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { findActiveHref } from "@/components/AppShell";

/** PILOT-WATER-001B: the Water & Nutrients workspace's own six views,
 * reached from one "Water & Nutrients" primary-nav entry -- mirrors Store &
 * Inventory's own `StoreSubNav` pattern (a horizontal in-page tab strip,
 * same longest-prefix active matching via `findActiveHref`) scaled from two
 * destinations to six. Rendered on every Water route so there is always a
 * way to every other view. */
export function WaterSubNav({ farmId }: { farmId: string }) {
  const pathname = usePathname();
  const tabs = [
    { label: "Overview", href: `/farms/${farmId}/water` },
    { label: "Measurements", href: `/farms/${farmId}/water/measurements` },
    { label: "Mixing", href: `/farms/${farmId}/water/mixing` },
    { label: "Delivery", href: `/farms/${farmId}/water/delivery` },
    { label: "Exposure", href: `/farms/${farmId}/water/exposure` },
    { label: "System Setup", href: `/farms/${farmId}/water/setup` },
  ];
  const activeHref = findActiveHref(pathname, tabs.map((t) => t.href));

  return (
    <nav aria-label="Water & Nutrients" className="mb-5 flex flex-wrap gap-4 border-b border-wl-border">
      {tabs.map((tab) => {
        const active = tab.href === activeHref;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px border-b-2 px-1 pb-2 text-sm font-medium ${
              active ? "border-wl-brand text-wl-brand" : "border-transparent text-wl-text-secondary hover:text-wl-text"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
