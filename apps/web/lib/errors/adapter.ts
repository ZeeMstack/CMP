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
  | "identity_error"
  | "permission_error";

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
      return new AppError("identity_error", detail ?? "You are not signed in, or your session has expired.", status);
    case 403:
      // A 403 is never an authentication failure -- the caller is still
      // signed in. Never worded like a session/network problem, and
      // never distinguished further (which resource, why) -- that would
      // reveal hidden resources or internal authorization detail.
      return new AppError(
        "permission_error",
        detail ?? "You don't have access to this operation or workspace context.",
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
    title: "Not signed in",
    action: "Sign in to continue.",
  },
  permission_error: {
    title: "Access denied",
    action: "Contact an administrator if you believe this is a mistake.",
  },
};

const UUID_ONLY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Classifies purely on `error.status`/`error.kind` -- both structured,
 * never a regex over backend prose -- and returns copy appropriate for a
 * command-style mutation (e.g. InterSalads Transplant). Several distinct
 * domain errors legitimately share one HTTP status with no further
 * backend-supplied discriminator (e.g. "source released", "Plate already
 * assigned", and "Table full" are all plain 409s), so this intentionally
 * does not fabricate per-case wording it cannot honestly back -- it names
 * the class of problem and the correct recovery action instead. The one
 * exception: `error.message` is shown verbatim only when it is not a bare
 * UUID (some backend exceptions carry only a raw id as their message,
 * e.g. `DestinationCarrierAlreadyAssignedError(str(carrier_id))` -- a raw
 * id is never operator-facing regardless of kind). This is a structural
 * check (does the string look like a UUID), not a semantic parse of the
 * message's wording. */
export function friendlyMutationErrorMessage(error: AppError): string {
  switch (error.kind) {
    case "permission_error":
      return "You don't have permission to do this. Contact an administrator if you believe this is a mistake.";
    case "not_found":
      return "One of the items in this transaction could no longer be found. Refresh and try again.";
    case "conflict":
      return "This conflicts with a change made elsewhere -- a source, Plate, or Table involved may have just been used. Review the refreshed information below before submitting again.";
    case "invalid_request":
      return UUID_ONLY.test(error.message.trim())
        ? "This transaction isn't valid -- check quantities, Plate capacity, and that the Batch is still open."
        : error.message;
    case "identity_error":
      return "You are not signed in, or your session has expired.";
    case "network_error":
      return "Could not reach the server. Check your connection and try again.";
    case "server_error":
    default:
      return "Something went wrong on the server. Try again, or contact an administrator if this continues.";
  }
}
