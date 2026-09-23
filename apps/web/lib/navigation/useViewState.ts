"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

/** UX-OPS-001B shared primitive: durable `?view=x&selected=y` URL state for
 * an operational queue workspace (Home, Germination, Seedling, Readiness,
 * Incidents). An invalid or absent `view` value falls back to
 * `defaultView` without breaking the route (never a 404/blank page for a
 * stale/bookmarked URL). `selected` is source-qualified by the caller
 * (e.g. `work-item:abc123`) so IDs from different sources sharing this one
 * queue can never collide -- this hook treats it as an opaque string.
 *
 * Uses `router.replace` (never `push`) so switching views/selection does
 * not pollute browser history with one entry per click, while refresh and
 * Back/Forward still restore the exact view+selection because both live in
 * the URL itself, not component state. */
export function useViewState<V extends string>({
  views,
  defaultView,
  viewParam = "view",
  selectedParam = "selected",
}: {
  views: readonly V[];
  defaultView: V;
  viewParam?: string;
  selectedParam?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const rawView = searchParams.get(viewParam);
  const view = useMemo<V>(() => {
    return rawView && (views as readonly string[]).includes(rawView) ? (rawView as V) : defaultView;
  }, [rawView, views, defaultView]);

  const selected = searchParams.get(selectedParam);

  const replaceParams = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams.toString());
      mutate(next);
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const setView = useCallback(
    (nextView: V) => {
      replaceParams((params) => {
        if (nextView === defaultView) params.delete(viewParam);
        else params.set(viewParam, nextView);
        // Changing view invalidates any prior selection -- a selected row
        // from one view is never silently carried into another view's list.
        params.delete(selectedParam);
      });
    },
    [replaceParams, defaultView, viewParam, selectedParam],
  );

  const setSelected = useCallback(
    (nextSelected: string | null) => {
      replaceParams((params) => {
        if (nextSelected) params.set(selectedParam, nextSelected);
        else params.delete(selectedParam);
      });
    },
    [replaceParams, selectedParam],
  );

  return { view, selected, setView, setSelected };
}
