import { AlertTriangle } from "lucide-react";

import { AppError, ERROR_KIND_COPY } from "@/lib/errors/adapter";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const appError = error instanceof AppError ? error : new AppError("server_error", "Unexpected error");
  const copy = ERROR_KIND_COPY[appError.kind];

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center"
    >
      <AlertTriangle aria-hidden="true" className="h-6 w-6 text-red-600" />
      <p className="text-base font-medium text-red-900">{copy.title}</p>
      <p className="max-w-prose text-sm text-red-800">{appError.message}</p>
      <p className="text-sm text-red-700">{copy.action}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-800 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
        >
          Retry
        </button>
      )}
    </div>
  );
}
