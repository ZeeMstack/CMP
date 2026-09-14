import { resolveTrustedOrigin } from "@/lib/server/same-origin";

import { LabelPreviewClient } from "./LabelPreviewClient";

/** PILOT-SCAN-001 FINAL SECURITY CLOSURE: a Server Component boundary,
 * deliberately -- `APP_BASE_URL` is server-only (never `NEXT_PUBLIC_*`,
 * see apps/web/.env.example) and must never be read from client-bundled
 * code. This is the one place the canonical printed-QR origin is resolved
 * (`resolveTrustedOrigin`, the same helper Auth0's own trusted-redirect
 * logic already uses -- see `lib/server/same-origin.ts`), then handed
 * down as a plain prop to the Client Component that actually renders the
 * label/QR. `null` (APP_BASE_URL unset/invalid) is passed through
 * unchanged -- `LabelPreviewClient` fails closed rather than ever
 * substituting a request- or browser-derived origin. */
export default async function LabelPreviewPage({
  params,
}: {
  params: Promise<{ farmId: string; entityType: string; entityId: string }>;
}) {
  const { farmId, entityType, entityId } = await params;
  const canonicalAppOrigin = resolveTrustedOrigin();
  return (
    <LabelPreviewClient
      farmId={farmId}
      entityType={entityType}
      entityId={entityId}
      canonicalAppOrigin={canonicalAppOrigin}
    />
  );
}
