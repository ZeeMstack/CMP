import type { ReactNode } from "react";

/** UX-IA-001 scope-communication wording (docs/domain/STORE_INVENTORY_MODEL.md
 * §19): a small, consistent tag under each workspace section so a user can
 * tell what's farm-specific vs. tenant-wide vs. global without learning
 * database terminology -- never technical language ("tenant_id", "farm
 * scoped"). */
export function ScopeLabel({ children }: { children: ReactNode }) {
  return <p className="mb-4 text-[11px] font-medium uppercase tracking-wide text-wl-text-tertiary">{children}</p>;
}
