"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Boxes, ClipboardList, Layers, Leaf, LayoutGrid, LogOut, Map, Menu, Package, PackageCheck, Scale, Sprout, Table2, Thermometer, Warehouse, Wheat, Wrench, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import type { ReactNode } from "react";

import { FarmSelector } from "@/components/FarmSelector";
import { NetworkStatusIndicator } from "@/components/NetworkStatusIndicator";
import { TenantSelector } from "@/components/TenantSelector";
import { useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { performSignOut } from "@/lib/auth/logout";
import { useFarms } from "@/lib/query/hooks";

function navItems(farmId: string) {
  return [
    { href: `/farms/${farmId}`, label: "Home", icon: LayoutGrid, exact: true },
    { href: `/farms/${farmId}/locations`, label: "Locations", icon: Map, exact: false },
    { href: `/farms/${farmId}/crop-batches`, label: "Batches", icon: Boxes, exact: false },
    { href: `/farms/${farmId}/seed-lots`, label: "Seed Lots", icon: Package, exact: false },
    { href: `/farms/${farmId}/nursery/sowings/new`, label: "Sowing", icon: Sprout, exact: false },
    { href: `/farms/${farmId}/nursery/germination`, label: "Germination", icon: Thermometer, exact: false },
    { href: `/farms/${farmId}/nursery/seedling`, label: "Seedling", icon: Leaf, exact: false },
    { href: `/farms/${farmId}/nursery/intersalads`, label: "InterSalads", icon: Table2, exact: false },
    { href: `/farms/${farmId}/leafy-production`, label: "Leafy Production", icon: ClipboardList, exact: true },
    { href: `/farms/${farmId}/leafy-production/transfer`, label: "Production Transfer", icon: ArrowRightLeft, exact: false },
    { href: `/farms/${farmId}/leafy-production/harvest`, label: "Harvest", icon: Wheat, exact: false },
    { href: `/farms/${farmId}/processing`, label: "Processing", icon: Scale, exact: true },
    { href: `/farms/${farmId}/processing/grading`, label: "Grading", icon: Scale, exact: false },
    { href: `/farms/${farmId}/processing/graded-lots`, label: "Graded Produce Lots", icon: Layers, exact: false },
    { href: `/farms/${farmId}/processing/packing`, label: "Packing", icon: PackageCheck, exact: false },
    { href: `/farms/${farmId}/processing/finished-goods`, label: "Finished Goods", icon: Warehouse, exact: false },
    { href: `/farms/${farmId}/farm-setup`, label: "Farm Setup", icon: Wrench, exact: false },
  ];
}

function isActive(pathname: string, href: string, exact: boolean) {
  return exact ? pathname === href : pathname.startsWith(href);
}

export function AppShell({ farmId, children }: { farmId: string; children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { bootstrap, selectTenant, isSwitchingTenant } = useAuthBootstrap();
  const { data: farms } = useFarms();
  const items = navItems(farmId);

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
      <aside className="hidden w-56 shrink-0 border-r border-border-subtle bg-surface md:flex md:flex-col">
        <div className="px-4 py-4">
          <span className="text-lg font-semibold text-brand-700">CMP</span>
        </div>
        <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 px-2">
          {items.map(({ href, label, icon: Icon, exact }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(pathname, href, exact) ? "page" : undefined}
              className={`flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium ${
                isActive(pathname, href, exact)
                  ? "bg-brand-100 text-brand-800"
                  : "text-ink-muted hover:bg-surface-subtle hover:text-ink"
              }`}
            >
              <Icon aria-hidden="true" className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
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
        <span className="text-base font-semibold text-brand-700">CMP</span>
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
        <nav id="mobile-nav" aria-label="Primary" className="border-b border-border-subtle bg-surface px-2 py-2 md:hidden">
          {items.map(({ href, label, icon: Icon, exact }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setMobileNavOpen(false)}
              aria-current={isActive(pathname, href, exact) ? "page" : undefined}
              className={`flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium ${
                isActive(pathname, href, exact) ? "bg-brand-100 text-brand-800" : "text-ink-muted hover:bg-surface-subtle"
              }`}
            >
              <Icon aria-hidden="true" className="h-4 w-4" />
              {label}
            </Link>
          ))}
          <button
            type="button"
            onClick={handleSignOut}
            className="flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-sm font-medium text-ink-muted hover:bg-surface-subtle"
          >
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Sign out
          </button>
        </nav>
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
