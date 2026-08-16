import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { RecordOutcomeForm } from "./RecordOutcomeForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CARRIER_TYPE = { id: "ct-1", code: "seed_tray", name: "Seed Tray" };
const SEED_LOT = {
  id: "lot-1", code: "LOT-01", supplier_lot_reference: null,
  crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: { id: "v1", code: "MAM", name: "Mamutik" },
};
const TRAYS = [
  {
    batch_id: "batch-1", batch_code: "CB-0001", seed_lot: SEED_LOT,
    tray: { id: "tray-1", code: "ST-0001", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "assignment-1", seeds_sown: 200, state: "in_germination",
    placement: { trolley: { id: "t9", code: "GT-01", name: "Trolley" }, chamber: { id: "c9", code: "GC-01", name: "Chamber" }, slot: { id: "s9", code: "S01", name: "Slot", shelf_code: "L1" } },
  },
  {
    batch_id: "batch-2", batch_code: "CB-0002", seed_lot: SEED_LOT,
    tray: { id: "tray-2", code: "ST-0002", carrier_type: CARRIER_TYPE },
    batch_carrier_assignment_id: "assignment-2", seeds_sown: 180, state: "elsewhere", placement: null,
  },
];

const CURRENT_EMPTY = {
  batch_id: "batch-1", batch_code: "CB-0001", trays: [
    {
      batch_carrier_assignment_id: "assignment-1", tray: TRAYS[0].tray, batch_id: "batch-1", batch_code: "CB-0001",
      seeds_sown: 200, sown_site_count: null, current_placement: "in_germination", latest_snapshot: null,
      latest_completed_snapshot: null, current_normal_seedling_count: null, current_abnormal_seedling_count: null,
      current_living_seedling_count: null, current_seed_to_living_gap_count: null, living_seedling_yield_percent: null,
      assessment_complete: false, authoritative_living_seedling_count: null, latest_effective_time: null,
      historical_snapshot_count: 0,
    },
  ],
  authoritative_living_seedling_total: 0, completed_tray_count: 0, unresolved_tray_count: 1, all_resolved: false,
};

function makeSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: "snap-1", observation_event_id: "event-1", tray: TRAYS[0].tray, batch_carrier_assignment_id: "assignment-1",
    normal_seedling_count: 150, abnormal_seedling_count: 5, living_seedling_count: 155, assessment_complete: false,
    note: null, effective_time: "2026-08-10T09:00:00Z", recorded_time: "2026-08-10T09:00:00Z", actor_user_id: "user-1",
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/germination-outcomes")) {
        if (overrides.postError) return jsonResponse({ detail: overrides.postError }, 422);
        return jsonResponse(
          overrides.postResponse ?? {
            observation_event_id: "event-2", client_command_id: "cmd-1", batch_id: "batch-1",
            effective_time: "2026-08-15T09:00:00Z", note: null, snapshots: [makeSnapshot({ assessment_complete: true })],
          },
          201,
        );
      }
      if (url.includes("/germination/trays")) return jsonResponse(overrides.trays ?? TRAYS);
      if (url.includes("/germination-outcomes/current")) return jsonResponse(overrides.current ?? CURRENT_EMPTY);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectFirstTray() {
  await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "assignment-1" } });
  await waitFor(() => expect(screen.getByText("Seeds sown")).toBeInTheDocument());
}

describe("RecordOutcomeForm", () => {
  it("lists Seed Trays with human-readable codes and current placement state, no raw UUIDs", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    expect(screen.getByText(/CB-0002 — ST-0002/)).toBeInTheDocument();
    expect(screen.queryByText(/assignment-1|assignment-2|tray-1|tray-2/)).not.toBeInTheDocument();
  });

  it("shows a zero-eligible-Tray empty message", async () => {
    stubFetch({ trays: [] });
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await waitFor(() =>
      expect(screen.getByText(/no sown seed trays are eligible for a germination outcome/i)).toBeInTheDocument(),
    );
  });

  it("shows Seeds Sown, honestly-nullable Sown Sites, and current placement once a Tray is selected", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    expect(screen.getByText("200")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Not recorded")).toBeInTheDocument());
    expect(screen.getByText("In Germination")).toBeInTheDocument();
  });

  it("does not hard-block a Tray that is currently outside Germination", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await waitFor(() => expect(screen.getByText(/CB-0002 — ST-0002/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/seed tray/i), { target: { value: "assignment-2" } });
    await waitFor(() => expect(screen.getByText("Elsewhere")).toBeInTheDocument());
    // Entry fields still render -- no hard block.
    expect(screen.getByLabelText(/^normal seedlings$/i)).toBeInTheDocument();
  });

  it("shows previous observation and previous handoff context when history exists", async () => {
    stubFetch({
      current: {
        ...CURRENT_EMPTY,
        trays: [
          {
            ...CURRENT_EMPTY.trays[0],
            latest_snapshot: makeSnapshot({ id: "snap-2", normal_seedling_count: 185, abnormal_seedling_count: 7, living_seedling_count: 192 }),
            latest_completed_snapshot: makeSnapshot({ id: "snap-0", assessment_complete: true, normal_seedling_count: 150, abnormal_seedling_count: 5, living_seedling_count: 155 }),
            historical_snapshot_count: 2,
          },
        ],
      },
    });
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    await waitFor(() => expect(screen.getByText(/192 living \(provisional\)/)).toBeInTheDocument());
    expect(screen.getByText(/155 living/)).toBeInTheDocument();
  });

  it("computes live Living total and seed-to-living gap as Normal/Abnormal are entered", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    fireEvent.change(screen.getByLabelText(/^normal seedlings$/i), { target: { value: "190" } });
    fireEvent.change(screen.getByLabelText(/^abnormal seedlings$/i), { target: { value: "6" } });
    await waitFor(() => expect(screen.getByText(/Living seedlings: 196/)).toBeInTheDocument());
    expect(screen.getByText(/Seeds not represented by living seedlings:\s*4/)).toBeInTheDocument();
  });

  it("shows a provisional review with no final-loss language, then submits", async () => {
    stubFetch();
    const onSuccess = vi.fn();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={onSuccess} onCancel={vi.fn()} />));
    await selectFirstTray();
    fireEvent.change(screen.getByLabelText(/^normal seedlings$/i), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText(/^abnormal seedlings$/i), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review provisional observation")).toBeInTheDocument());
    expect(screen.getByText(/not a final categorized loss/i)).toBeInTheDocument();
    expect(screen.queryByText(/non-germination loss/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save Observation" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  });

  it("shows a completed review establishing the handoff quantity", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    fireEvent.change(screen.getByLabelText(/^normal seedlings$/i), { target: { value: "190" } });
    fireEvent.change(screen.getByLabelText(/^abnormal seedlings$/i), { target: { value: "6" } });
    fireEvent.click(screen.getByLabelText(/assessment complete/i));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before completing")).toBeInTheDocument());
    expect(screen.getByText(/establish the current germination handoff quantity/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete Outcome" })).toBeInTheDocument();
  });

  it("shows a backend error on the review step", async () => {
    stubFetch({ postError: "assignment already has a completed Germination outcome at or after this effective time" });
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    fireEvent.change(screen.getByLabelText(/^normal seedlings$/i), { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review provisional observation")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Save Observation" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already has a completed/i));
  });

  it("never shows legacy site-based fields or a loss-category catalog", async () => {
    stubFetch();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={vi.fn()} onCancel={vi.fn()} />));
    await selectFirstTray();
    expect(screen.queryByLabelText(/inspected site|sown site count|failed site/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/non.?germination|weak seedling|disease|pest damage|mortality|qc rejection/i)).not.toBeInTheDocument();
  });

  it("calls onCancel without submitting", async () => {
    stubFetch();
    const onSuccess = vi.fn();
    const onCancel = vi.fn();
    render(withQueryClient(<RecordOutcomeForm farmId="farm-1" onSuccess={onSuccess} onCancel={onCancel} />));
    await waitFor(() => expect(screen.getByText(/CB-0001 — ST-0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
