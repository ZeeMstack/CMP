import type { ReactNode } from "react";

/**
 * PILOT-UI-002 closure: /select-tenant is authenticated (post sign-in,
 * pre-tenant-selection) but sits outside any farm/tenant-scoped shell, so it
 * did not inherit the approved operator brand tokens. Scopes the same
 * `data-app-shell` attribute AppShell/StandaloneShell/`/farms` use (see
 * globals.css's `[data-app-shell]` block) rather than wrapping this page in
 * either shell's own chrome, which would be semantically wrong here (e.g.
 * StandaloneShell's own TenantSelector duplicating the very choice this page
 * exists to make). `display: contents` keeps this purely a token scope with
 * zero layout footprint.
 */
export default function SelectTenantLayout({ children }: { children: ReactNode }) {
  return (
    <div data-app-shell="true" className="contents">
      {children}
    </div>
  );
}
