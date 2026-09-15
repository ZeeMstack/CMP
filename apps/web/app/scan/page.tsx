"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { WorkingLocationBar } from "@/components/scan/WorkingLocationBar";
import { Button } from "@/components/ui/Button";
import { GROWCMP_PRODUCTION_ORIGIN, normalizeScanInput } from "@/lib/scan/normalizeScanInput";
import { useWorkingLocation } from "@/lib/scan/useWorkingLocation";

/** PILOT-SCAN-001E: the manual fallback entry point into the existing scan
 * flow, for an operator whose device camera can't read a damaged/dirty
 * printed label. A physical QR already opens `/q/{token}` directly via the
 * device's own native camera app -- this page adds no camera/barcode
 * scanning of its own (out of scope for this ticket) and no second
 * resolver: it only normalizes whatever the operator pastes or types
 * (`normalizeScanInput`) down to a bare token, then navigates to the SAME
 * existing `/q/[token]` route, which performs the one, only, authoritative
 * resolution. */
export default function ScanEntryPage() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { workingLocation, clearWorkingLocation } = useWorkingLocation();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // The current application origin (accurate in every environment --
    // production, preview, local dev -- without hardcoding any of them)
    // plus the one fixed production origin every printed label's QR is
    // built against, so a token copied from a genuine printed label is
    // still accepted while testing against a different deployment.
    const result = normalizeScanInput(value, [window.location.origin, GROWCMP_PRODUCTION_ORIGIN]);
    if ("error" in result) {
      setError(result.error);
      return;
    }
    setError(null);
    router.push(`/q/${encodeURIComponent(result.token)}`);
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-12">
      {/* PILOT-SCAN-001F: shown here too (never a separate comparison --
          this is display-only), so an operator opening the manual fallback
          mid-session still sees their active working location. */}
      {workingLocation && (
        <WorkingLocationBar workingLocation={workingLocation} onClear={clearWorkingLocation} showScanLink={false} />
      )}

      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-wide text-wl-text-tertiary">growCMP</p>
        <h1 className="mt-1 font-serif text-xl font-semibold text-wl-text">Scan / Enter QR</h1>
      </div>
      <p className="text-sm text-wl-text-secondary">
        Point your device&apos;s camera at a printed GrowCMP label to open it directly. If the camera can&apos;t
        read it, paste or type the code below instead.
      </p>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label htmlFor="scan-token-input" className="text-sm font-medium text-wl-text">
          QR token or scan link
        </label>
        <input
          id="scan-token-input"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. Ab3xY9... or a full growCMP scan link"
          className="h-11 w-full rounded-md border border-wl-border-strong px-3 text-sm text-wl-text"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
        />
        {error && (
          <p role="alert" className="text-sm text-danger-700">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary">
          Open
        </Button>
      </form>
    </div>
  );
}
