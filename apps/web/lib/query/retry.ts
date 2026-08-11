import { AppError } from "@/lib/errors/adapter";

const MAX_RETRIES = 3;

/**
 * React Query's default retry policy retries every failed query up to 3
 * times regardless of status code. For a definitive 4xx client error
 * (invalid request, not authenticated, forbidden, not found, conflict,
 * tenant-selection-required) the identical request can never succeed by
 * retrying it -- doing so only delays the user seeing an accurate error
 * state (AUTH-001B3: a 403 should render its permission-specific error
 * promptly, not after several seconds of pointless retries). Genuine
 * transient failures (network errors, 5xx) still get bounded retries.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof AppError && error.status !== null && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < MAX_RETRIES;
}
