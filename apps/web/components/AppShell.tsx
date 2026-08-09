"use client";

import { Boxes, LayoutGrid, Map, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { ReactNode } from "react";

import { FarmSelector } from "@/components/FarmSelector";
import { NetworkStatusIndicator } from "@/components/NetworkStatusIndicator";
import { useFarms } from "@/lib/query/hooks";

function navItems(farmId: string) {
  return [
    { href: `/farms/${farmId}`, label: "Home", icon: LayoutGrid, exact: true },
    { href: `/farms/${farmId}/locations`, label: "Locations", icon: Map, exact: false },
    { href: `/farms/${farmId}/crop-batches`, label: "Batches", icon: Boxes, exact: false },
  ];
}

function isActive(pathname: string, href: string, exact: boolean) {
  return exact ? pathname === href : pathname.startsWith(href);
}

export function AppShell({ farmId, children }: { farmId: string; children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pathname = usePathname();
  const { data: farms } = useFarms();
  const items = navItems(farmId);

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
        {farms && <FarmSelector farms={farms} currentFarmId={farmId} />}
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
        </nav>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Desktop top bar: farm context + network status */}
        <header className="hidden items-center justify-between border-b border-border-subtle bg-surface px-6 py-3 md:flex">
          {farms && <FarmSelector farms={farms} currentFarmId={farmId} />}
          <NetworkStatusIndicator />
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
