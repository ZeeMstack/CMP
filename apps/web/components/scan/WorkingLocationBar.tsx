"use client";

import Link from "next/link";

import type { WorkingLocation } from "@/lib/scan/workingLocation";

/** PILOT-SCAN-001F: the one compact, reused "you are working here"
 * indicator -- shown on `/q/[token]`, `/scan`, and Today on the Farm.
 * Deliberately tiny (no dashboard): a path, a Clear, and (except on
 * `/scan` itself, where it would be redundant) a link into the same
 * manual scan entry point. */
export function WorkingLocationBar({
  workingLocation,
  onClear,
  showScanLink = true,
  scanLinkLabel = "Scan / Enter next QR",
}: {
  workingLocation: WorkingLocation;
  onClear: () => void;
  showScanLink?: boolean;
  scanLinkLabel?: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-wl-border-strong bg-wl-surface-raised px-3 py-2">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">Working location</p>
        <p className="truncate text-sm font-medium text-wl-text">{workingLocation.pathString}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {showScanLink && (
          <Link href="/scan" className="text-sm font-medium text-wl-brand hover:underline">
            {scanLinkLabel}
          </Link>
        )}
        <button type="button" onClick={onClear} className="text-sm font-medium text-wl-text-secondary hover:underline">
          Clear
        </button>
      </div>
    </div>
  );
}
