"use client";

import { useCallback, useSyncExternalStore } from "react";

import { clearWorkingLocationStorage, readWorkingLocation, writeWorkingLocation, type WorkingLocation } from "@/lib/scan/workingLocation";

/** `useSyncExternalStore` (not `useState` + `useEffect`) is the correct
 * primitive for subscribing to an external mutable store like
 * `localStorage`: it renders the server-safe snapshot (`null`, since
 * `getServerSnapshot` never touches `window`) on the very first client
 * render too, avoiding a hydration mismatch, then re-syncs to the real
 * client value right after -- a hand-rolled `useEffect` that calls
 * `setState` on mount achieves the same end state but re-renders
 * synchronously inside the effect, which is exactly the pattern
 * `react-hooks/set-state-in-effect` flags. */
const listeners = new Set<() => void>();

function notifyListeners() {
  for (const listener of listeners) listener();
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  document.addEventListener("visibilitychange", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
    document.removeEventListener("visibilitychange", callback);
  };
}

// `readWorkingLocation()` parses fresh JSON every call, so two calls with
// identical content are NOT the same object reference -- cached here so
// `getSnapshot` returns a referentially stable value when nothing has
// actually changed (required by `useSyncExternalStore`; otherwise it
// would look like a change, and therefore trigger a re-render, on every
// single render).
let cachedRaw: string | null = null;
let cachedValue: WorkingLocation | null = null;

function getSnapshot(): WorkingLocation | null {
  const value = readWorkingLocation();
  const raw = value ? JSON.stringify(value) : null;
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedValue = value;
  }
  return cachedValue;
}

function getServerSnapshot(): WorkingLocation | null {
  return null;
}

export function useWorkingLocation() {
  const workingLocation = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setWorkingLocation = useCallback(
    (input: { locationId: string; farmId: string; code: string; pathString: string }) => {
      writeWorkingLocation(input);
      // A same-tab `localStorage` write never fires that tab's own
      // `storage` event (only OTHER tabs receive it) -- this is what
      // tells `useSyncExternalStore` this tab's own snapshot changed too.
      notifyListeners();
    },
    [],
  );

  const clearWorkingLocation = useCallback(() => {
    clearWorkingLocationStorage();
    notifyListeners();
  }, []);

  return { workingLocation, setWorkingLocation, clearWorkingLocation };
}
