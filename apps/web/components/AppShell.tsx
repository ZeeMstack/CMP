"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { WaterlineWordmark } from "@/components/brand/WaterlineMark";
import { FarmSelector } from "@/components/FarmSelector";
import { NetworkStatusIndicator } from "@/components/NetworkStatusIndicator";
import { TenantSelector } from "@/components/TenantSelector";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { performSignOut } from "@/lib/auth/logout";
import { useFarms } from "@/lib/query/hooks";
import type { TenantMembership } from "@/lib/auth/types";
import type { FarmRead } from "@/lib/api/client";

interface NavLink {
  label: string;
  href: string;
}

interface NavGroupDef {
  id: string;
  label: string;
  items: NavLink[];
}

/** The frozen UI-OPT-001 navigation tree (CEO_ALIGNMENT_SPEC.md), now
 * rendered as PILOT-UX-001A2-R2's top-nav-plus-contextual-sidebar IA rather
 * than one grouped accordion sidebar -- see AppShell's module doc below.
 * Routes not named here (Processing landing, Seed Lots, Locations, Batches,
 * and -- as of UX-IA-001 -- Stores & Bins, Inventory Categories, Inventory
 * Items, Units of Measure, superseded into the single "Store & Inventory
 * Setup" entry above) are intentionally removed from primary navigation but
 * remain live routes -- reachable by direct link/URL, never deleted.
 * "Greenhouse & Locations"
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
      items: [
        { label: "Leafy Production", href: `/farms/${farmId}/leafy-production` },
        { label: "Transfer to Production", href: `/farms/${farmId}/leafy-production/transfer` },
      ],
    },
    {
      id: "harvest",
      label: "Harvest & Post-Harvest",
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
      items: [
        { label: "Dispatch", href: `/farms/${farmId}/processing/dispatch` },
        { label: "Traceability", href: `/farms/${farmId}/traceability` },
        { label: "Recall Cases", href: `/farms/${farmId}/processing/recall-cases` },
      ],
    },
    {
      id: "farm-setup",
      label: "Farm Setup & Master Data",
      items: [
        { label: "Greenhouse & Locations", href: `/farms/${farmId}/farm-setup` },
        // UX-IA-001 (CEO_ALIGNMENT_SPEC.md "Store & Inventory Setup
        // navigation"): supersedes the four separate STORE-INV-001A
        // entries (Stores & Bins, Inventory Categories, Inventory Items,
        // Units of Measure) with ONE workspace entry -- Overview/Storage/
        // Inventory Catalog/Settings are workspace views, not sidebar
        // modules. The four legacy routes stay live for deep links/
        // bookmarks (never deleted), same precedent as Processing landing/
        // Seed Lots/Locations/Batches above.
        { label: "Store & Inventory Setup", href: `/farms/${farmId}/store-inventory-setup` },
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

/** URL is the single source of truth for nav state (PILOT-UX-001A2-R2
 * section 12) -- no separate "which module is open" state is stored
 * anywhere. `moduleId` is "home" on the farm home route, the id of the
 * group owning the most-specific matching leaf href, or null when the
 * route has no dedicated nav entry at all (e.g. the removed Seed Lots
 * page) -- in which case nothing in the top nav is marked active and no
 * contextual sidebar renders. */
function resolveActiveNav(
  pathname: string,
  farmId: string,
  groups: NavGroupDef[],
): { moduleId: string | null; activeHref: string | null } {
  const homeHref = `/farms/${farmId}`;
  if (pathname === homeHref) {
    return { moduleId: "home", activeHref: homeHref };
  }
  const leafHrefs = groups.flatMap((g) => g.items.map((i) => i.href));
  const activeHref = findActiveHref(pathname, leafHrefs);
  const moduleId = groups.find((g) => g.items.some((i) => i.href === activeHref))?.id ?? null;
  return { moduleId, activeHref };
}

function topNavLinkClass(active: boolean): string {
  return `relative flex h-12 shrink-0 items-center px-3 text-sm font-medium transition-colors after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:content-[''] ${
    active ? "text-wl-brand after:bg-wl-brand" : "text-wl-text-secondary after:bg-transparent hover:text-wl-text"
  }`;
}

/** Top navigation = main application modules (PILOT-UX-001A2-R2 section 8).
 * A heading with no dedicated landing page links to its first currently
 * visible child, per section 12. */
function TopNav({
  farmId,
  groups,
  activeModuleId,
}: {
  farmId: string;
  groups: NavGroupDef[];
  activeModuleId: string | null;
}) {
  const homeHref = `/farms/${farmId}`;
  return (
    <nav
      aria-label="Main"
      className="hidden items-stretch gap-1 overflow-x-auto border-b border-wl-border bg-wl-surface-raised px-4 md:flex md:px-6"
    >
      <Link
        href={homeHref}
        aria-current={activeModuleId === "home" ? "page" : undefined}
        className={topNavLinkClass(activeModuleId === "home")}
      >
        Home
      </Link>
      {groups.map((group) => (
        <Link
          key={group.id}
          href={group.items[0]?.href ?? homeHref}
          aria-current={activeModuleId === group.id ? "true" : undefined}
          className={topNavLinkClass(activeModuleId === group.id)}
        >
          {group.label}
        </Link>
      ))}
    </nav>
  );
}

/** Left context sidebar = only child items of the active main module
 * (PILOT-UX-001A2-R2 section 11) -- never every group's children at once. */
function ContextualSidebar({ group, activeHref }: { group: NavGroupDef; activeHref: string | null }) {
  return (
    <aside
      aria-label={`${group.label} navigation`}
      className="hidden w-60 shrink-0 flex-col gap-0.5 border-r border-wl-border bg-wl-surface py-4 md:flex"
    >
      <div className="px-4 pb-2 text-[11px] font-medium uppercase tracking-wide text-wl-text-tertiary">
        {group.label}
      </div>
      <ul className="flex flex-col gap-0.5 px-2">
        {group.items.map((item) => {
          const active = item.href === activeHref;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-9 items-center rounded-lg px-3 text-sm font-medium ${
                  active
                    ? "bg-wl-brand-subtle text-wl-brand"
                    : "text-wl-text-secondary hover:bg-wl-surface-hover hover:text-wl-text"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function mobileLinkClass(active: boolean): string {
  return `flex min-h-11 items-center rounded-lg px-3 text-sm font-medium ${
    active ? "bg-wl-brand-subtle text-wl-brand" : "text-wl-text-secondary hover:bg-wl-surface-hover hover:text-wl-text"
  }`;
}

/** Mobile keeps the existing drawer/accordion navigation concept (section
 * 29) rather than compressing the top-nav/contextual-sidebar split into an
 * unreadable width -- Home plus each module, expandable to that module's
 * children, all in one panel. Farm/Tenant selection also lives here on
 * mobile since the identity bar hides them below `md:`. */
function MobileNav({
  farmId,
  groups,
  activeModuleId,
  activeHref,
  onNavigate,
  onSignOut,
  farms,
  memberships,
  selectedTenantId,
  onSelectTenant,
  isSwitchingTenant,
}: {
  farmId: string;
  groups: NavGroupDef[];
  activeModuleId: string | null;
  activeHref: string | null;
  onNavigate: () => void;
  onSignOut: () => void;
  farms: FarmRead[] | undefined;
  memberships: TenantMembership[] | undefined;
  selectedTenantId: string | null | undefined;
  onSelectTenant: (tenantId: string) => void;
  isSwitchingTenant: boolean;
}) {
  const homeHref = `/farms/${farmId}`;
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    () => new Set(activeModuleId && activeModuleId !== "home" ? [activeModuleId] : []),
  );

  function toggleGroup(id: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <nav id="mobile-nav" aria-label="Main" className="flex flex-col border-b border-wl-border bg-wl-surface-raised px-3 py-3 md:hidden">
      {(farms || memberships) && (
        <div className="mb-3 flex flex-col gap-2 border-b border-wl-border pb-3">
          {farms && (
            <div className="flex flex-col leading-tight">
              <span className="text-[10px] font-medium uppercase tracking-wide text-wl-text-tertiary">Farm</span>
              <FarmSelector farms={farms} currentFarmId={farmId} />
            </div>
          )}
          {memberships && (
            <div className="flex flex-col leading-tight">
              <span className="text-[10px] font-medium uppercase tracking-wide text-wl-text-tertiary">Tenant</span>
              <TenantSelector
                memberships={memberships}
                selectedTenantId={selectedTenantId ?? null}
                onSelect={onSelectTenant}
                disabled={isSwitchingTenant}
              />
            </div>
          )}
        </div>
      )}

      <Link
        href={homeHref}
        onClick={onNavigate}
        aria-current={activeModuleId === "home" ? "page" : undefined}
        className={mobileLinkClass(activeModuleId === "home")}
      >
        Home
      </Link>

      {groups.map((group) => {
        const isOpen = openGroups.has(group.id);
        const isModuleActive = activeModuleId === group.id;
        const panelId = `mobile-nav-group-${group.id}`;
        return (
          <div key={group.id} className="mt-1">
            <button
              type="button"
              onClick={() => toggleGroup(group.id)}
              aria-expanded={isOpen}
              aria-controls={panelId}
              className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-3 text-sm font-medium hover:bg-wl-surface-hover ${
                isModuleActive ? "text-wl-brand" : "text-wl-text-secondary"
              }`}
            >
              {group.label}
              <ChevronDown
                aria-hidden="true"
                className={`h-4 w-4 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
              />
            </button>
            {isOpen && (
              <ul id={panelId} className="ml-2 flex flex-col gap-0.5 border-l border-wl-border py-1 pl-3">
                {group.items.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={item.href === activeHref ? "page" : undefined}
                      className={mobileLinkClass(item.href === activeHref)}
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

      <button
        type="button"
        onClick={onSignOut}
        className="mt-3 flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-left text-sm font-medium text-wl-text-secondary hover:bg-wl-surface-hover"
      >
        <LogOut aria-hidden="true" className="h-4 w-4" />
        Sign out
      </button>
    </nav>
  );
}

/** Waterline application shell (PILOT-UX-001A2-R2): a compact identity/
 * context bar, main-module top navigation, and a contextual left sidebar
 * that shows only the active module's children -- replacing the prior
 * single grouped-accordion sidebar. See section 8 for the frozen IA. */
export function AppShell({ farmId, children }: { farmId: string; children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { bootstrap, selectTenant, isSwitchingTenant } = useAuthBootstrap();
  const { data: farms } = useFarms();

  const groups = useMemo(() => navGroups(farmId), [farmId]);
  const { moduleId: activeModuleId, activeHref } = useMemo(
    () => resolveActiveNav(pathname, farmId, groups),
    [pathname, farmId, groups],
  );
  const activeGroup = groups.find((g) => g.id === activeModuleId) ?? null;

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
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-wl-brand focus:px-3 focus:py-2 focus:text-wl-text-on-brand"
      >
        Skip to content
      </a>

      {/* Identity / context bar (section 14): brand first, Farm as the
          stronger operational context, Tenant secondary. */}
      <header className="flex items-center justify-between gap-3 border-b border-wl-border bg-wl-surface-raised px-3 py-2.5 md:px-6">
        <div className="flex min-w-0 items-center gap-3 md:gap-6">
          <button
            type="button"
            onClick={() => setMobileNavOpen((v) => !v)}
            aria-expanded={mobileNavOpen}
            aria-controls="mobile-nav"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-wl-text hover:bg-wl-surface-hover md:hidden"
          >
            {mobileNavOpen ? <X aria-hidden="true" className="h-5 w-5" /> : <Menu aria-hidden="true" className="h-5 w-5" />}
            <span className="sr-only">Toggle navigation</span>
          </button>

          <WaterlineWordmark />

          <div className="hidden min-w-0 items-center gap-5 md:flex">
            {farms && (
              <div className="flex flex-col leading-tight">
                <span className="text-[10px] font-medium uppercase tracking-wide text-wl-text-tertiary">Farm</span>
                <FarmSelector farms={farms} currentFarmId={farmId} />
              </div>
            )}
            {bootstrap && (
              <div className="flex flex-col leading-tight">
                <span className="text-[10px] font-medium uppercase tracking-wide text-wl-text-tertiary">Tenant</span>
                <TenantSelector
                  memberships={bootstrap.memberships}
                  selectedTenantId={bootstrap.selectedTenantId}
                  onSelect={handleTenantSelect}
                  disabled={isSwitchingTenant}
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <NetworkStatusIndicator />
          <button
            type="button"
            onClick={handleSignOut}
            className="hidden h-9 items-center gap-1.5 rounded-lg px-2 text-sm font-medium text-wl-text-secondary hover:bg-wl-surface-hover hover:text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus md:flex"
          >
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </header>

      <TopNav farmId={farmId} groups={groups} activeModuleId={activeModuleId} />

      {mobileNavOpen && (
        <MobileNav
          farmId={farmId}
          groups={groups}
          activeModuleId={activeModuleId}
          activeHref={activeHref}
          onNavigate={() => setMobileNavOpen(false)}
          onSignOut={handleSignOut}
          farms={farms}
          memberships={bootstrap?.memberships}
          selectedTenantId={bootstrap?.selectedTenantId}
          onSelectTenant={handleTenantSelect}
          isSwitchingTenant={isSwitchingTenant}
        />
      )}

      <div className="flex min-w-0 flex-1">
        {activeGroup && <ContextualSidebar group={activeGroup} activeHref={activeHref} />}
        <main id="main-content" className="min-w-0 flex-1 bg-wl-surface px-4 py-5 md:px-8 md:py-7">
          {children}
        </main>
      </div>
    </div>
  );
}
