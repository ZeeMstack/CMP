/**
 * Maps a failed API call to one of a small set of UI-meaningful error
 * kinds. Never surfaces raw backend payloads or a generic "something went
 * wrong" for a known status -- every kind below should drive a specific,
 * actionable UI state (see components/ErrorState.tsx).
 */
export type AppErrorKind =
  | "not_found"
  | "invalid_request"
  | "conflict"
  | "server_error"
  | "network_error"
  | "identity_error";

export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly status: number | null;

  constructor(kind: AppErrorKind, message: string, status: number | null = null) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

export function errorFromResponse(status: number, detail?: string): AppError {
  switch (status) {
    case 401:
      return new AppError(
        "identity_error",
        detail ?? "The pilot identity configured for this deployment is invalid or inactive.",
        status,
      );
    case 404:
      return new AppError("not_found", detail ?? "That item could not be found.", status);
    case 400:
    case 422:
      return new AppError("invalid_request", detail ?? "The request was invalid.", status);
    case 409:
      return new AppError("conflict", detail ?? "This conflicts with existing data.", status);
    case 502:
      return new AppError("network_error", detail ?? "Could not reach the backend.", status);
    default:
      if (status >= 500) {
        return new AppError("server_error", detail ?? "The server encountered an error.", status);
      }
      return new AppError("server_error", detail ?? `Unexpected response (${status}).`, status);
  }
}

export function errorFromNetworkFailure(cause: unknown): AppError {
  const message = cause instanceof Error ? cause.message : "Network request failed.";
  return new AppError("network_error", message);
}

/** Human-readable guidance per error kind, for ErrorState's default copy. */
export const ERROR_KIND_COPY: Record<AppErrorKind, { title: string; action: string }> = {
  not_found: { title: "Not found", action: "Return to the previous list." },
  invalid_request: { title: "Invalid request", action: "Check the page and try again." },
  conflict: { title: "Conflict", action: "Refresh and try again." },
  server_error: { title: "Server error", action: "Retry, or contact an administrator if this continues." },
  network_error: { title: "Connection problem", action: "Check your connection and retry." },
  identity_error: {
    title: "Pilot configuration problem",
    action: "Contact an administrator about this pilot deployment's configuration.",
  },
};
