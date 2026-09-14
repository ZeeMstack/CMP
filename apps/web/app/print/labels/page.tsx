import { resolveTrustedOrigin } from "@/lib/server/same-origin";

import { PrintLabelsClient } from "./PrintLabelsClient";

/** PILOT-SCAN-001C: this route has no dynamic path segment (unlike the
 * sibling `/farms/[farmId]/labels/[entityType]/[entityId]` route, which
 * Next.js already renders on demand per params), so with no other signal
 * to opt out of static rendering, Next.js 16 prerendered it once at BUILD
 * TIME -- `resolveTrustedOrigin()` below ran during the build, reading
 * whatever `APP_BASE_URL` happened to be set (or not) in the BUILD
 * container/step, then baked that one result into the static HTML served
 * for every later request. In production this meant every visit reused
 * the build-time result regardless of the real, correctly-configured
 * runtime `APP_BASE_URL` -- observed as "APP_BASE_URL is not configured"
 * even though it plainly was, at request time, on the running service.
 * `force-dynamic` forces this route to render fresh per request (the
 * Next.js 16-native, single-line way to opt a route out of static
 * rendering) so `resolveTrustedOrigin()` always reads the live runtime
 * environment. No behavior for a correctly-configured deployment changes
 * beyond that -- this route's whole content is request-derived (`items`)
 * anyway, so there was never a cacheable static payload to lose. */
export const dynamic = "force-dynamic";

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
