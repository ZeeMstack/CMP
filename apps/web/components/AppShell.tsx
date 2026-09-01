"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ClipboardList, LayoutGrid, LogOut, Menu, Sprout, Truck, Wheat, Wrench, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { FarmSelector } from "@/components/FarmSelector";
import { NetworkStatusIndicator } from "@/components/NetworkStatusIndicator";
import { TenantSelector } from "@/components/TenantSelector";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { performSignOut } from "@/lib/auth/logout";
import { useFarms } from "@/lib/query/hooks";

interface NavLink {
  label: string;
  href: string;
}

interface NavGroupDef {
  id: string;
  label: string;
  icon: LucideIcon;
  items: NavLink[];
}

/** The frozen UI-OPT-001 navigation tree (CEO_ALIGNMENT_SPEC.md). Routes
 * not named here (Processing landing, Seed Lots, Locations, Batches) are
 * intentionally removed from primary navigation but remain live routes --
 * reachable by direct link/URL, never deleted. "Greenhouse & Locations"
 * stays a single leaf pointing at /farm-setup only (not merged with
 * /locations, which keeps its own distinct domain purpose -- Batch B adds
 * a secondary in-page link from Farm Setup to Locations/Occupancy).
 * "Carrier Specifications" is deliberately NOT farm-scoped (a
 * CarrierSpecification is shared across every farm in the tenant,
 * CARRIER-CONFIG-001) -- its href has no farmId segment.
 * "Traceability" points at the future Batch F route; that page does not
 * exist yet on this branch by design (see Batch A ticket). */
function navGroups(farmId: string): NavGroupDef[] {
  return [
    {
      id: "nursery",
      label: "Nursery Operations",
      icon: Sprout,
      items: [
        { label: "Seeding", href: `/farms/${farmId}/nursery/sowings/new` },
        { label: "Germination", href: `/farms/${farmId}/nursery/germination` },
        { label: "Seedling", href: `/farms/${farmId}/nursery/seedling` },
        { label: "Transfer to Inter Leafy Greens", href: `/farms/${farmId}/nursery/intersalads` },
      ],
    },
    {
      id: "production",
      label: "Production Operations",
      icon: ClipboardList,
      items: [
        { label: "Leafy Production", href: `/farms/${farmId}/leafy-production` },
        { label: "Transfer to Production", href: `/farms/${farmId}/leafy-production/transfer` },
      ],
    },
    {
      id: "harvest",
      label: "Harvest & Post-Harvest",
      icon: Wheat,
      items: [
        { label: "Harvest", href: `/farms/${farmId}/leafy-production/harvest` },
        { label: "Grading", href: `/farms/${farmId}/processing/grading` },
        { label: "Graded Produce", href: `/farms/${farmId}/processing/graded-lots` },
        { label: "Packing", href: `/farms/${farmId}/processing/packing` },
        { label: "Finished Goods", href: `/farms/${farmId}/processing/finished-goods` },
        { label: "Cold Storage", href: `/farms/${farmId}/processing/cold-storage` },
      ],
    },
    {
      id: "dispatch",
      label: "Dispatch & Traceability",
      icon: Truck,
      items: [
        { label: "Dispatch", href: `/farms/${farmId}/processing/dispatch` },
        { label: "Traceability", href: `/farms/${farmId}/traceability` },
        { label: "Recall Cases", href: `/farms/${farmId}/processing/recall-cases` },
      ],
    },
    {
      id: "farm-setup",
      label: "Farm Setup & Master Data",
      icon: Wrench,
      items: [
        { label: "Greenhouse & Locations", href: `/farms/${farmId}/farm-setup` },
        { label: "Carrier Specifications", href: "/carrier-specifications" },
        { label: "Crops & Varieties", href: "/crops" },
        { label: "Production Systems", href: "/production-systems" },
        { label: "Workflows", href: "/workflows" },
        { label: "Grade Definitions", href: "/grade-definitions" },
        { label: "Packaging Units", href: "/packaging-units" },
        { label: "Pack Specifications", href: "/pack-specifications" },
      ],
    },
  ];
}

/** Deterministic most-specific-prefix match: among every nav href, picks
 * the longest one that is either an exact match or a path-segment prefix
 * of `pathname`. This is what makes e.g. /leafy-production/harvest
 * activate "Harvest" rather than the shorter "/leafy-production" (Leafy
 * Production) href it also happens to start with. Exported for direct
 * unit testing independent of rendering. */
export function findActiveHref(pathname: string, hrefs: string[]): string | null {
  let best: string | null = null;
  for (const href of hrefs) {
    const matches = pathname === href || pathname.startsWith(`${href}/`);
    if (matches && (best === null || href.length > best.length)) {
      best = href;
    }
  }
  return best;
}

function navLinkClass(active: boolean): string {
  return `flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium ${
    active ? "bg-brand-100 text-brand-800" : "text-ink-muted hover:bg-surface-subtle hover:text-ink"
  }`;
}

function SidebarNav({
  farmId,
  pathname,
  variant,
  onNavigate,
  footer,
}: {
  farmId: string;
  pathname: string;
  variant: "desktop" | "mobile";
  onNavigate?: () => void;
  footer?: ReactNode;
}) {
  const homeHref = `/farms/${farmId}`;
  const groups = useMemo(() => navGroups(farmId), [farmId]);
  // Home is matched by exact equality only, deliberately excluded from the
  // most-specific-prefix pool below -- otherwise, since every farm-scoped
  // route is nested under Home's own href, any page with no dedicated nav
  // entry (e.g. the removed Seed Lots/Locations routes) would misleadingly
  // show Home as "active" simply for being its descendant.
  const leafHrefs = useMemo(() => groups.flatMap((g) => g.items.map((i) => i.href)), [groups]);
  const homeActive = pathname === homeHref;
  const activeHref = homeActive ? homeHref : findActiveHref(pathname, leafHrefs);
  const activeGroupId = groups.find((g) => g.items.some((i) => i.href === activeHref))?.id ?? null;

  // Independent per-instance (desktop/mobile) expand state -- each
  // viewport's nav auto-expands the group containing the active route on
  // mount and whenever navigation changes which group is active, without
  // fighting the operator's own manual collapse/expand of other groups.
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set(activeGroupId ? [activeGroupId] : []));

  // Adjust state during render rather than in an Effect (React's own
  // recommended pattern for "state that depends on a changed prop"): track
  // the last activeGroupId we've already auto-expanded for, and when it
  // changes -- a fresh mount, a deep link, or a client-side navigation into
  // a different group -- fold it into openGroups. This never fires for a
  // navigation that stays within the same group, so it never fights a
  // manual collapse of that group.
  const [lastAutoExpandedGroupId, setLastAutoExpandedGroupId] = useState(activeGroupId);
  if (activeGroupId !== lastAutoExpandedGroupId) {
    setLastAutoExpandedGroupId(activeGroupId);
    if (activeGroupId && !openGroups.has(activeGroupId)) {
      setOpenGroups(new Set(openGroups).add(activeGroupId));
    }
  }

  function toggleGroup(id: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const idPrefix = variant === "mobile" ? "mobile" : "desktop";

  return (
    <nav
      id={variant === "mobile" ? "mobile-nav" : undefined}
      aria-label="Primary"
      className={
        variant === "mobile"
          ? "border-b border-border-subtle bg-surface px-2 py-2 md:hidden"
          : "flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-4"
      }
    >
      <Link
        href={homeHref}
        onClick={onNavigate}
        aria-current={activeHref === homeHref ? "page" : undefined}
        className={navLinkClass(activeHref === homeHref)}
      >
        <LayoutGrid aria-hidden="true" className="h-4 w-4" />
        Home
      </Link>

      {groups.map((group) => {
        const isOpen = openGroups.has(group.id);
        const isGroupActive = group.id === activeGroupId;
        const Icon = group.icon;
        const groupPanelId = `nav-group-${idPrefix}-${group.id}`;
        return (
          <div key={group.id} className="mt-1">
            <button
              type="button"
              onClick={() => toggleGroup(group.id)}
              aria-expanded={isOpen}
              aria-controls={groupPanelId}
              className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-3 text-xs font-semibold uppercase tracking-wide hover:bg-surface-subtle ${
                isGroupActive ? "text-brand-800" : "text-ink-muted"
              }`}
            >
              <span className="flex items-center gap-2">
                <Icon aria-hidden="true" className="h-4 w-4" />
                {group.label}
              </span>
              <ChevronDown
                aria-hidden="true"
                className={`h-3.5 w-3.5 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
              />
            </button>
            {isOpen && (
              <ul id={groupPanelId} className="ml-3 flex flex-col gap-0.5 border-l border-border-subtle py-1 pl-3">
                {group.items.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={item.href === activeHref ? "page" : undefined}
                      className={navLinkClass(item.href === activeHref)}
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}

      {footer}
    </nav>
  );
}

export function AppShell({ farmId, children }: { farmId: string; children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { bootstrap, selectTenant, isSwitchingTenant } = useAuthBootstrap();
  const { data: farms } = useFarms();

  // Switching tenant always returns to /farms -- a farm id from the
  // previous tenant must never survive into the new tenant's URL (it may
  // not exist there at all, or worse, could coincidentally resolve to an
  // unrelated farm).
  async function handleTenantSelect(tenantId: string) {
    const result = await selectTenant(tenantId);
    if (result.ok) {
      router.push("/farms");
    }
  }

  async function handleSignOut() {
    await performSignOut(queryClient);
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-brand-700 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border-subtle bg-surface md:flex md:flex-col">
        <div className="px-4 py-4">
          <div className="font-serif text-base font-semibold leading-tight text-brand-900">GrowCMP</div>
          <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
            Crop Management Platform
          </div>
        </div>
        <SidebarNav farmId={farmId} pathname={pathname} variant="desktop" />
      </aside>

      {/* Mobile top bar */}
      <header className="flex items-center justify-between border-b border-border-subtle bg-surface px-3 py-2 md:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen((v) => !v)}
          aria-expanded={mobileNavOpen}
          aria-controls="mobile-nav"
          className="flex h-11 w-11 items-center justify-center rounded-md text-ink hover:bg-surface-subtle"
        >
          {mobileNavOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          <span className="sr-only">Toggle navigation</span>
        </button>
        <span className="font-serif text-base font-semibold text-brand-900">GrowCMP</span>
        <div className="flex min-w-0 items-center gap-2">
          {bootstrap && (
            <TenantSelector
              memberships={bootstrap.memberships}
              selectedTenantId={bootstrap.selectedTenantId}
              onSelect={handleTenantSelect}
              disabled={isSwitchingTenant}
            />
          )}
          {farms && <FarmSelector farms={farms} currentFarmId={farmId} />}
        </div>
      </header>
      {mobileNavOpen && (
        <SidebarNav
          farmId={farmId}
          pathname={pathname}
          variant="mobile"
          onNavigate={() => setMobileNavOpen(false)}
          footer={
            <button
              type="button"
              onClick={handleSignOut}
              className="mt-2 flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-sm font-medium text-ink-muted hover:bg-surface-subtle"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
              Sign out
            </button>
          }
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Desktop top bar: farm context + network status */}
        <header className="hidden items-center justify-between border-b border-border-subtle bg-surface px-6 py-3 md:flex">
          <div className="flex items-center gap-3">
            {bootstrap && (
              <TenantSelector
                memberships={bootstrap.memberships}
                selectedTenantId={bootstrap.selectedTenantId}
                onSelect={handleTenantSelect}
                disabled={isSwitchingTenant}
              />
            )}
            {farms && <FarmSelector farms={farms} currentFarmId={farmId} />}
          </div>
          <div className="flex items-center gap-3">
            <NetworkStatusIndicator />
            <button
              type="button"
              onClick={handleSignOut}
              className="flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </header>
        <div className="flex justify-end px-3 py-2 md:hidden">
          <NetworkStatusIndicator />
        </div>
        <main id="main-content" className="flex-1 px-4 py-4 md:px-6 md:py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
