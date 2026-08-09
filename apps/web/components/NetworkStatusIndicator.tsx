"use client";

import { WifiOff } from "lucide-react";
import { useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

/**
 * `navigator.onLine` is a hint, not proof the API is reachable -- a failed
 * request is still the authoritative signal for network error state (see
 * lib/errors/adapter.ts). This only tells the operator "your device thinks
 * it has no connection," which is still useful context on a farm floor.
 */
export function NetworkStatusIndicator() {
  const isOnline = useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );

  if (isOnline) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900"
    >
      <WifiOff aria-hidden="true" className="h-3.5 w-3.5" />
      Offline
    </div>
  );
}
