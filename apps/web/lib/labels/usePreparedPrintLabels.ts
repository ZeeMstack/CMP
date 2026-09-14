import { useEffect, useRef, useState } from "react";

import { generateQrIdentifier, type QrEntityType } from "@/lib/api/client";

import type { OperationalLabelContext } from "./operationalLabel";
import type { PrintableLabel } from "./printableLabel";

export interface PreparedLabelSpec extends OperationalLabelContext {
  entityType: QrEntityType;
  entityId: string;
}

/** PILOT-SCAN-001B: resolves the (idempotent, backend-generate-or-get) QR
 * token for each label spec in the background, as soon as a workflow
 * success screen renders -- NOT on the "Print Labels" click itself. This
 * is what lets the click handler call `window.open` SYNCHRONOUSLY (see
 * `openLabelPrintWindow`), which every browser's popup blocker requires;
 * an async token fetch inside the click handler would make the resulting
 * `window.open` call async and get silently blocked.
 *
 * Never triggers/depends on printing itself -- this only prepares data.
 * A failure here surfaces as `error` (the "Print Labels" button can
 * disable itself) and never affects the already-succeeded farm
 * operation this hook is attached to. */
export function usePreparedPrintLabels(farmId: string, specs: PreparedLabelSpec[]) {
  const [labels, setLabels] = useState<PrintableLabel[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  // Specs are built fresh (new array/object identities) on every render
  // from a stable underlying command result -- key on their actual
  // identifying content instead of array/object identity.
  const specsKey = JSON.stringify(specs.map((s) => [s.entityType, s.entityId]));
  const requestedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    // Nothing to fetch -- handled directly in the return value below
    // without ever touching state.
    if (specs.length === 0) return;
    if (requestedKeyRef.current === specsKey) return;
    requestedKeyRef.current = specsKey;

    let cancelled = false;
    setLabels(null);
    setError(null);

    Promise.all(specs.map((spec) => generateQrIdentifier(farmId, spec.entityType, spec.entityId)))
      .then((identifiers) => {
        if (cancelled) return;
        setLabels(
          identifiers.map((identifier, index) => ({
            token: identifier.token,
            size: specs[index].size,
            entityType: specs[index].entityType,
            entityTypeLabel: specs[index].entityTypeLabel,
            code: specs[index].code,
            lines: specs[index].lines,
          })),
        );
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId, specsKey]);

  if (specs.length === 0) {
    return { labels: [] as PrintableLabel[], error: null, isLoading: false };
  }
  return { labels, error, isLoading: labels === null && error === null };
}
