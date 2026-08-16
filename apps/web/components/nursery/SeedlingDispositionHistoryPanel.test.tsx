import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { SeedlingDispositionHistoryPanel } from "./SeedlingDispositionHistoryPanel";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const REASONS = [{ code: "WEAK_SEEDLING", name: "Weak seedling" }, { code: "DISEASE", name: "Disease" }];

function stubFetch(history: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/nursery/seedling/dispositions?")) return jsonResponse(history);
      if (url.includes("/nursery/seedling/disposition-reasons")) return jsonResponse(REASONS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedlingDispositionHistoryPanel", () => {
  it("shows a still-uncorrected REDUCTION as correctable, never a REVERSAL, never a REDUCTION already reversed", async () => {
    stubFetch({
      seedling_entry_id: "se-1", starting_living_seedling_count: 196, current_living_seedling_count: 189,
      events: [
        {
          id: "evt-1", command_id: "cmd-1", seedling_entry_id: "se-1", event_kind: "REDUCTION",
          reason_code: "WEAK_SEEDLING", quantity_delta: -4, effective_time: "2026-08-10T09:00:00Z",
          note: null, reverses_event_id: null, corrects_event_id: null, actor_user_id: "user-1",
          recorded_at: "2026-08-10T09:00:01Z",
        },
        {
          id: "evt-2", command_id: "cmd-2", seedling_entry_id: "se-1", event_kind: "REDUCTION",
          reason_code: "DISEASE", quantity_delta: -3, effective_time: "2026-08-11T09:00:00Z",
          note: null, reverses_event_id: null, corrects_event_id: null, actor_user_id: "user-1",
          recorded_at: "2026-08-11T09:00:01Z",
        },
        {
          id: "evt-3", command_id: "cmd-3", seedling_entry_id: "se-1", event_kind: "REVERSAL",
          reason_code: "DISEASE", quantity_delta: 3, effective_time: "2026-08-11T09:00:00Z",
          note: null, reverses_event_id: "evt-2", corrects_event_id: null, actor_user_id: "user-1",
          recorded_at: "2026-08-12T00:00:00Z",
        },
      ],
    });
    render(withQueryClient(<SeedlingDispositionHistoryPanel farmId="farm-1" seedlingEntryId="se-1" onClose={vi.fn()} />));
    await waitFor(() => expect(screen.getByText("189")).toBeInTheDocument());

    // Only evt-1 (an unreversed REDUCTION) offers Correct -- evt-2 was
    // reversed by evt-3, and evt-3 is itself a REVERSAL (never correctable).
    expect(screen.getAllByRole("button", { name: "Correct" })).toHaveLength(1);
    expect(screen.getByText("Reverses a prior entry")).toBeInTheDocument();
  });

  it("opens the correction form for a correctable event and returns to the list view on cancel", async () => {
    stubFetch({
      seedling_entry_id: "se-1", starting_living_seedling_count: 196, current_living_seedling_count: 192,
      events: [
        {
          id: "evt-1", command_id: "cmd-1", seedling_entry_id: "se-1", event_kind: "REDUCTION",
          reason_code: "WEAK_SEEDLING", quantity_delta: -4, effective_time: "2026-08-10T09:00:00Z",
          note: null, reverses_event_id: null, corrects_event_id: null, actor_user_id: "user-1",
          recorded_at: "2026-08-10T09:00:01Z",
        },
      ],
    });
    render(withQueryClient(<SeedlingDispositionHistoryPanel farmId="farm-1" seedlingEntryId="se-1" onClose={vi.fn()} />));
    await waitFor(() => expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    await waitFor(() => expect(screen.getByText("Correct this entry")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByText("Correct this entry")).not.toBeInTheDocument());
  });
});
