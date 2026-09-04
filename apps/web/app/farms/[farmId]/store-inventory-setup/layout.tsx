"use client";

import Link from "next/link";
import { usePathname, useParams } from "next/navigation";
import type { ReactNode } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";

interface WorkspaceTab {
  label: string;
  href: string;
}

function subNavLinkClass(active: boolean): string {
  return `flex h-9 items-center rounded-lg px-3 text-sm font-medium transition-colors ${
    active
      ? "bg-wl-brand-subtle text-wl-brand"
      : "text-wl-text-secondary hover:bg-wl-surface-hover hover:text-wl-text"
  }`;
}

/** UX-IA-001: local workspace sub-navigation (Overview / Storage /
 * Inventory Catalog / Settings) -- a subordinate view switcher within the
 * ONE "Store & Inventory Setup" entry in the main sidebar, deliberately
 * styled lighter (pill highlight, no underline) than AppShell's own
 * top-nav/contextual-sidebar so it never reads as a second, competing
 * primary nav. Every child route stays inside AppShell (mounted one level
 * up by `[farmId]/layout.tsx`), so the Farm/Tenant switcher and the
 * "Store & Inventory Setup" contextual-sidebar entry remain visible and
 * active throughout -- `findActiveHref`'s prefix match already treats
 * every route under this segment as one module (AppShell.tsx). */
export default function StoreInventorySetupLayout({ children }: { children: ReactNode }) {
  const { farmId } = useParams<{ farmId: string }>();
  const pathname = usePathname();
  const base = `/farms/${farmId}/store-inventory-setup`;
  const tabs: WorkspaceTab[] = [
    { label: "Overview", href: base },
    { label: "Storage", href: `${base}/storage` },
    { label: "Inventory Catalog", href: `${base}/catalog` },
    { label: "Settings", href: `${base}/settings` },
  ];

  return (
    <div>
      <PageHeader
        title="Store & Inventory Setup"
        description="Configure this farm's storage and the tenant's material catalog."
        breadcrumbs={
          <Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Store & Inventory Setup" }]} />
        }
      />
      <nav aria-label="Store & Inventory Setup views" className="mb-6 flex flex-wrap gap-1">
        {tabs.map((tab) => {
          const active = tab.href === base ? pathname === base : pathname.startsWith(tab.href);
          return (
            <Link key={tab.href} href={tab.href} aria-current={active ? "page" : undefined} className={subNavLinkClass(active)}>
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
