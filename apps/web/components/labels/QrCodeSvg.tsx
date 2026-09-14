"use client";

import { QRCodeSVG } from "qrcode.react";

/** PILOT-SCAN-001: the QR payload is `<origin>/q/<opaque-token>` -- built
 * from `window.location.origin` (the one authoritative "what host am I
 * being served from" value a browser already has) rather than a new,
 * separately-maintained base-URL config/hardcoded domain. Vector/SVG
 * rendering (never a rasterized screenshot) for sharp thermal printing;
 * dark-on-light only -- QR modules are never styled with brand colors. */
export function qrScanUrl(token: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/q/${encodeURIComponent(token)}`;
}

export function QrCodeSvg({ token, sizeMm }: { token: string; sizeMm: number }) {
  return (
    <QRCodeSVG
      value={qrScanUrl(token)}
      size={sizeMm * 8}
      level="M"
      bgColor="#ffffff"
      fgColor="#000000"
      marginSize={1}
      style={{ width: `${sizeMm}mm`, height: `${sizeMm}mm` }}
    />
  );
}
