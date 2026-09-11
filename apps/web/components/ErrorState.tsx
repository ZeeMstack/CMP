import { AlertTriangle } from "lucide-react";

import { AppError, ERROR_KIND_COPY } from "@/lib/errors/adapter";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const appError = error instanceof AppError ? error : new AppError("server_error", "Unexpected error");
  const copy = ERROR_KIND_COPY[appError.kind];

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-1.5 rounded-lg border border-wl-border-strong bg-wl-flag-bg px-6 py-6 text-center"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0 text-wl-flag-fg" />
        <p className="text-sm font-semibold text-wl-flag-fg">{copy.title}</p>
      </div>
      <p className="max-w-prose text-sm text-wl-flag-fg">{appError.message}</p>
      <p className="text-xs text-wl-flag-fg">{copy.action}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1.5 rounded-md border border-wl-border-strong bg-wl-surface-raised px-3 py-1.5 text-sm font-medium text-wl-text hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
        >
          Retry
        </button>
      )}
    </div>
  );
}
