"use client";

import { Button } from "@/components/ui/Button";
import type { WorkingLocation } from "@/lib/scan/workingLocation";

/** PILOT-SCAN-001F: the deliberate "establish/replace working location"
 * action shown only when a Location itself is scanned. Never fires
 * automatically -- an already-active working location is never replaced
 * merely because another Location QR happened to be opened; the operator
 * must click. Purely local browser-context state (never a farm record):
 * clicking this stores nothing more than "the operator says I am
 * currently working here." */
export function WorkingLocationEstablishPanel({
  workingLocation,
  scanned,
  onUse,
}: {
  workingLocation: WorkingLocation | null;
  scanned: { locationId: string; farmId: string; code: string; pathString: string };
  onUse: () => void;
}) {
  const alreadyActive =
    workingLocation !== null && workingLocation.locationId === scanned.locationId && workingLocation.farmId === scanned.farmId;

  if (alreadyActive) {
    return <p className="text-sm text-wl-text-secondary">This is your current working location.</p>;
  }

  if (!workingLocation) {
    return (
      <Button variant="primary" onClick={onUse}>
        Use as working location
      </Button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-wl-border-strong bg-wl-surface-raised p-3 text-sm">
      <p>
        <span className="text-wl-text-tertiary">Current working location: </span>
        <span className="font-medium text-wl-text">{workingLocation.pathString}</span>
      </p>
      <p>
        <span className="text-wl-text-tertiary">Scanned location: </span>
        <span className="font-medium text-wl-text">{scanned.pathString}</span>
      </p>
      <Button variant="secondary" onClick={onUse} className="self-start">
        Use {scanned.code} instead
      </Button>
    </div>
  );
}
