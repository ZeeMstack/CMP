"use client";

import { QRCodeSVG } from "qrcode.react";

/** PILOT-SCAN-001 FINAL SECURITY CLOSURE: the QR payload is
 * `<canonical app origin>/q/<opaque-token>` -- `canonicalAppOrigin` MUST
 * come from the server-resolved `APP_BASE_URL` (see
 * `lib/server/same-origin.ts::resolveTrustedOrigin`, the same value
 * Auth0's own callback/redirect URLs already trust), passed down from the
 * label preview route's Server Component boundary. This is a PERMANENT
 * PRINTED LABEL -- it must never be built from `window.location.origin`
 * (whatever hostname the operator happened to open: a Render preview URL,
 * a LAN IP, localhost) or the printed QR could point somewhere that isn't
 * the one canonical GrowCMP web origin for its whole physical lifetime.
 * Vector/SVG rendering (never a rasterized screenshot) for sharp thermal
 * printing; dark-on-light only -- QR modules are never styled with brand
 * colors. */
export function qrScanUrl(canonicalAppOrigin: string, token: string): string {
  return `${canonicalAppOrigin}/q/${encodeURIComponent(token)}`;
}

export function QrCodeSvg({
  canonicalAppOrigin,
  token,
  sizeMm,
}: {
  canonicalAppOrigin: string;
  token: string;
  sizeMm: number;
}) {
  return (
    <QRCodeSVG
      value={qrScanUrl(canonicalAppOrigin, token)}
      size={sizeMm * 8}
      level="M"
      bgColor="#ffffff"
      fgColor="#000000"
      marginSize={1}
      style={{ width: `${sizeMm}mm`, height: `${sizeMm}mm` }}
    />
  );
}
