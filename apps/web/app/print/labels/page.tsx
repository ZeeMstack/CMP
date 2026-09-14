import { resolveTrustedOrigin } from "@/lib/server/same-origin";

import { PrintLabelsClient } from "./PrintLabelsClient";

/** PILOT-SCAN-001B: label-only print document. Deliberately lives OUTSIDE
 * the `/farms/[farmId]/*` route tree (mirroring `/q/[token]`, `/farms/
 * [farmId]/labels/[entityType]/[entityId]`) so it never inherits
 * `AppShell` chrome (nav, breadcrumbs, header) -- a dedicated print-only
 * layout, not fragile `@media print` selector-hiding of an app page.
 *
 * A Server Component boundary for the same reason as the existing label
 * preview route: `APP_BASE_URL` is server-only and must never reach
 * client-bundled code, so the canonical QR origin is resolved here and
 * handed down as a plain prop. */
export default async function PrintLabelsPage() {
  const canonicalAppOrigin = resolveTrustedOrigin();
  return <PrintLabelsClient canonicalAppOrigin={canonicalAppOrigin} />;
}
