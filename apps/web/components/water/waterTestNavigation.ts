/** Test-only `next/navigation` stand-in for the Water workspace tests:
 * `router.replace` updates a tiny external store that `useSearchParams`
 * subscribes to, so URL-backed view/selection state re-renders exactly as
 * it does in the app. Import it from a `vi.mock("next/navigation", ...)`
 * factory. Never imported by application code. */
import { useSyncExternalStore } from "react";

let current = new URLSearchParams();
const listeners = new Set<() => void>();

export const replaceCalls: string[] = [];

export function setTestSearch(search: string) {
  current = new URLSearchParams(search);
  listeners.forEach((l) => l());
}

export function currentTestSearch(): URLSearchParams {
  return current;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function createNavigationMock(pathname: string, farmId = "farm-1") {
  return {
    useParams: () => ({ farmId }),
    usePathname: () => pathname,
    useSearchParams: () => useSyncExternalStore(subscribe, () => current, () => current),
    useRouter: () => ({
      push: () => undefined,
      replace: (href: string) => {
        replaceCalls.push(href);
        const query = href.includes("?") ? href.slice(href.indexOf("?") + 1) : "";
        setTestSearch(query);
      },
    }),
  };
}
