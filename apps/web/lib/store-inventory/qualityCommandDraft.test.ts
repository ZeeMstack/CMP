/** PILOT-BLOCKER-008 A2: uncertain-command lifecycle guards for
 * `useQualityCommandDraft` -- Cancel/Close must not discard a frozen
 * command while its outcome is uncertain, and a late response from an
 * abandoned command must never mutate a newer draft's state. */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { useQualityCommandDraft } from "@/lib/store-inventory/qualityCommandDraft";

const CONTEXT_A = {
  cohortId: "cohort-a", kind: "ORDINARY" as const, targetEventId: null, observedState: "RELEASED", disposition: "HELD",
};
const CONTEXT_B = {
  cohortId: "cohort-b", kind: "ORDINARY" as const, targetEventId: null, observedState: "RELEASED", disposition: "HELD",
};

describe("useQualityCommandDraft", () => {
  it("close() is a no-op while outcome is uncertain -- the frozen command survives an ordinary Cancel", () => {
    const { result } = renderHook(() => useQualityCommandDraft());

    act(() => result.current.open(CONTEXT_A));
    act(() => {
      result.current.submit({ inventory_quantity_cohort_id: "cohort-a", disposition: "HELD" });
    });
    act(() => {
      result.current.handleError(new AppError("network_error", "Failed to fetch"), 1);
    });
    expect(result.current.outcome).toBe("uncertain");

    act(() => result.current.close());

    // Still open, still uncertain, context untouched -- close() refused to act.
    expect(result.current.isOpen).toBe(true);
    expect(result.current.outcome).toBe("uncertain");
    expect(result.current.context?.cohortId).toBe("cohort-a");
  });

  it("close() succeeds once outcome resolves to editing (definitive rejection)", () => {
    const { result } = renderHook(() => useQualityCommandDraft());

    act(() => result.current.open(CONTEXT_A));
    act(() => {
      result.current.submit({ inventory_quantity_cohort_id: "cohort-a", disposition: "HELD" });
    });
    act(() => {
      result.current.handleError(new AppError("invalid_request", "not a valid transition"), 1);
    });
    expect(result.current.outcome).toBe("editing");

    act(() => result.current.close());
    expect(result.current.isOpen).toBe(false);
  });

  it("a late success response from an abandoned command (stale generation) never mutates a newer draft", () => {
    const { result } = renderHook(() => useQualityCommandDraft());

    // Command A opens and submits, but is abandoned by a definitive
    // rejection (outcome -> "editing"), which makes it closable...
    act(() => result.current.open(CONTEXT_A));
    let submittedA!: ReturnType<typeof result.current.submit>;
    act(() => {
      submittedA = result.current.submit({ inventory_quantity_cohort_id: "cohort-a", disposition: "HELD" });
    });
    act(() => {
      result.current.handleError(new AppError("invalid_request", "rejected"), submittedA.generation);
    });
    act(() => result.current.close());

    // ...a completely different command B is now open.
    act(() => result.current.open(CONTEXT_B));
    act(() => {
      result.current.submit({ inventory_quantity_cohort_id: "cohort-b", disposition: "HELD" });
    });
    expect(result.current.outcome).toBe("submitting");
    expect(result.current.context?.cohortId).toBe("cohort-b");

    // A's stale success callback finally arrives, carrying A's OLD generation.
    act(() => result.current.handleSuccess(submittedA.generation));

    // B's draft must be completely untouched by A's stale response.
    expect(result.current.isOpen).toBe(true);
    expect(result.current.outcome).toBe("submitting");
    expect(result.current.context?.cohortId).toBe("cohort-b");
  });

  it("a late error response from an abandoned command (stale generation) never mutates a newer draft", () => {
    const { result } = renderHook(() => useQualityCommandDraft());

    act(() => result.current.open(CONTEXT_A));
    let submittedA!: ReturnType<typeof result.current.submit>;
    act(() => {
      submittedA = result.current.submit({ inventory_quantity_cohort_id: "cohort-a", disposition: "HELD" });
    });
    act(() => {
      result.current.handleError(new AppError("invalid_request", "rejected"), submittedA.generation);
    });
    act(() => result.current.close());

    act(() => result.current.open(CONTEXT_B));
    let submittedB!: ReturnType<typeof result.current.submit>;
    act(() => {
      submittedB = result.current.submit({ inventory_quantity_cohort_id: "cohort-b", disposition: "HELD" });
    });

    // A's stale network-error callback arrives late, carrying A's OLD generation.
    act(() => {
      result.current.handleError(new AppError("network_error", "Failed to fetch"), submittedA.generation);
    });

    // B's draft is untouched -- still "submitting", not flipped to "uncertain".
    expect(result.current.outcome).toBe("submitting");
    expect(result.current.context?.cohortId).toBe("cohort-b");

    // B's own (current-generation) response still applies normally.
    act(() => {
      result.current.handleError(new AppError("network_error", "Failed to fetch"), submittedB.generation);
    });
    expect(result.current.outcome).toBe("uncertain");
  });

  it("retry() reuses the exact frozen payload and client_command_id, and keeps the same generation", () => {
    const { result } = renderHook(() => useQualityCommandDraft());

    act(() => result.current.open(CONTEXT_A));
    let submitted!: ReturnType<typeof result.current.submit>;
    act(() => {
      submitted = result.current.submit({ inventory_quantity_cohort_id: "cohort-a", disposition: "HELD" });
    });
    act(() => {
      result.current.handleError(new AppError("network_error", "Failed to fetch"), submitted.generation);
    });

    let retried!: ReturnType<typeof result.current.retry>;
    act(() => {
      retried = result.current.retry();
    });

    expect(retried).not.toBeNull();
    expect(retried?.payload).toEqual(submitted.payload);
    expect(retried?.generation).toBe(submitted.generation);
  });
});
