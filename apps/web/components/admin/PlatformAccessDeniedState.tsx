import { AlertTriangle } from "lucide-react";

/** The specific 403 state for platform-admin screens (PILOT-SETUP-001B3) --
 * distinct from the generic ErrorState so the exact required copy always
 * renders, regardless of the backend's own `detail` text. Same visual
 * language as ErrorState (role="alert", not color-only: an icon + explicit
 * "Access denied" label alongside the red styling). */
export function PlatformAccessDeniedState() {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center"
    >
      <AlertTriangle aria-hidden="true" className="h-6 w-6 text-red-600" />
      <p className="text-base font-medium text-red-900">Access denied</p>
      <p className="max-w-prose text-sm text-red-800">You do not have platform administrator access.</p>
    </div>
  );
}
