"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { findActiveHref } from "@/components/AppShell";

/** PILOT-UX-005 closure: replaces the removed Store contextual sidebar.
 * Same two destinations (Operations, Inventory), same longest-prefix active
 * matching as the rest of primary navigation (`findActiveHref`), just
 * rendered horizontally near each Store page's own header instead of in a
 * permanent left column -- freeing that width for Store's tables/queues.
 * Rendered on every Store & Inventory route (Operations, Inventory, and the
 * task pages Receive Goods/Putaway/Quality/Issue) so there is always a way
 * back to the two Store destinations, mirroring what the sidebar covered. */
export function StoreSubNav({ farmId }: { farmId: string }) {
  const pathname = usePathname();
  const tabs = [
    { label: "Operations", href: `/farms/${farmId}/store-inventory` },
    { label: "Inventory", href: `/farms/${farmId}/store-inventory/inventory` },
  ];
  const activeHref = findActiveHref(pathname, tabs.map((t) => t.href));

  return (
    <nav aria-label="Store & Inventory" className="mb-5 flex gap-4 border-b border-wl-border">
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
