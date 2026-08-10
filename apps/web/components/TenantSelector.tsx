"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { humanizeEnumCode } from "@/lib/format/humanize";
import type { TenantMembership } from "@/lib/auth/types";

/**
 * A CMP tenant selector -- represents `tenant_memberships`, NOT Auth0
 * Organizations (AUTH-001B2). Mirrors FarmSelector's compact/dropdown
 * pattern, but selection is an async server round-trip (POST
 * /api/tenant/select, fresh-verified membership), not a plain navigation
 * Link, so `onSelect` is invoked rather than rendering an <a href>.
 * Never displays a raw tenant UUID.
 */
export function TenantSelector({
  memberships,
  selectedTenantId,
  onSelect,
  disabled,
}: {
  memberships: TenantMembership[];
  selectedTenantId: string | null;
  onSelect: (tenantId: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const current = memberships.find((m) => m.tenantId === selectedTenantId);

  if (memberships.length <= 1) {
    return <span className="truncate text-sm font-medium text-ink">{current?.tenantName ?? "…"}</span>;
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex min-h-11 items-center gap-1 rounded-md px-2 text-sm font-medium text-ink hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:opacity-60"
      >
        <span className="truncate">{current?.tenantName ?? "Select tenant"}</span>
        <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0" />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label="Tenants"
          className="absolute left-0 z-10 mt-1 min-w-56 rounded-md border border-border-subtle bg-surface py-1 shadow-lg"
        >
          {memberships.map((membership) => (
            <li key={membership.tenantId} role="option" aria-selected={membership.tenantId === selectedTenantId}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  onSelect(membership.tenantId);
                }}
                className={`flex w-full min-h-11 flex-col items-start px-3 py-2 text-left text-sm hover:bg-surface-subtle ${
                  membership.tenantId === selectedTenantId ? "font-medium text-brand-700" : "text-ink"
                }`}
              >
                <span>{membership.tenantName}</span>
                <span className="text-xs text-ink-muted">
                  {membership.tenantCode} · {humanizeEnumCode(membership.roleCode)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
