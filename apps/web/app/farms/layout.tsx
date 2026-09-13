import type { ReactNode } from "react";

/**
 * PILOT-UI-002 closure: /farms (the farm picker) and /farms/new sit outside
 * AppShell (no farmId exists yet to mount it with), so neither inherited the
 * approved operator brand tokens -- only `/farms/[farmId]/**` did, via its
 * own nested layout's `AppShell`. This segment-level layout scopes the same
 * `data-app-shell` attribute (see globals.css's `[data-app-shell]` block)
 * around this whole subtree instead, so both pre-farm-context screens pick
 * up the approved palette exactly like every other operator screen -- no
 * new token values, no wrapping in AppShell/StandaloneShell chrome that
 * would be semantically wrong here (a "Back to Farms" link on /farms
 * itself, for instance). `display: contents` keeps this purely a token
 * scope with zero layout footprint; `/farms/[farmId]/layout.tsx` nests
 * inside this one and is unaffected (the same attribute simply appears
 * twice, which is harmless).
 */
export default function FarmsLayout({ children }: { children: ReactNode }) {
  return (
    <div data-app-shell="true" className="contents">
      {children}
    </div>
  );
}
