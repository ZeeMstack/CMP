import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventoryQualityPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function queueRow(overrides: Record<string, unknown> = {}) {
  return {
    inventory_quantity_cohort_id: "coh-1", inventory_item_id: "item-1", item_name: "Calcium Nitrate",
    base_uom_id: "uom-1", inventory_lot_id: "lot-1", manufacturer_lot_reference: "LOT-1", expiry_date: null,
    received_at_farm_id: "farm-1", source_goods_receipt_line_id: "line-1", receipt_code: "GR-F1-20260907-001",
    receipt_received_at: "2026-09-07T08:00:00Z", balance: "500.000", current_state: "RECEIVED_QUARANTINED",
    current_event_id: "evt-1", last_actor_user_id: null, last_effective_time: null,
    ...overrides,
  };
}

function stubFetch(
  queue: unknown[],
  postHandler?: (url: string, body: unknown) => Response,
  breakdown?: unknown,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init || init.method === undefined) {
      if (url.endsWith("/quality-work-queue")) return jsonResponse(queue);
      if (url.includes("/storage-breakdown")) {
        return jsonResponse(
          breakdown ?? { inventory_quantity_cohort_id: "coh-1", not_put_away_quantity: "500.000", buckets: [] },
        );
      }
      return jsonResponse([]);
    }
    const body = init.body ? JSON.parse(String(init.body)) : {};
    if (postHandler) return postHandler(url, body);
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryQualityPage", () => {
  it("offers Release / Hold / Reject for a RECEIVED_QUARANTINED row, but no correction actions", async () => {
    stubFetch([queueRow()]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hold" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision for part of quantity" })).not.toBeInTheDocument();
  });

  it("offers only Correct decision(s) for a REJECTED row -- no ordinary Release", async () => {
    stubFetch([queueRow({ current_state: "REJECTED" })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hold" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct decision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct decision for part of quantity" })).toBeInTheDocument();
  });

  it("offers Hold Release for a HELD row", async () => {
    stubFetch([queueRow({ current_state: "HELD" })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Hold Release" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("offers 'Apply to part of quantity' for an actionable row", async () => {
    stubFetch([queueRow()]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Apply to part of quantity" })).toBeInTheDocument();
  });

  it("never offers correction actions for implicit RELEASED with no current event", async () => {
    stubFetch([queueRow({ current_state: "RELEASED", current_event_id: null })]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Correct decision" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct decision for part of quantity" })).not.toBeInTheDocument();
  });

  it("submits the row's current_event_id as target_event_id on a correction", async () => {
    let posted: unknown = null;
    stubFetch([queueRow({ current_state: "HELD", current_event_id: "evt-held-42" })], (url, body) => {
      if (url.endsWith("/quality-disposition-corrections")) {
        posted = body;
        return jsonResponse({
          reversal: { id: "rev-1", inventory_quantity_cohort_id: "coh-1", event_kind: "REVERSAL", reverses_event_id: "evt-held-42", effective_time: "2026-09-07T09:00:00Z", recorded_time: "2026-09-07T09:00:00Z", actor_user_id: "u1", reason: "fixed" },
          replacement: null,
        });
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "fixed" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { target_event_id: string }).target_event_id).toBe("evt-held-42");
  });

  it("submits a 'Correct decision for part of quantity' command with quantity and corrected disposition", async () => {
    let posted: unknown = null;
    stubFetch([queueRow({ current_state: "REJECTED", current_event_id: "evt-rejected-7", balance: "100.000" })], (url, body) => {
      if (url.endsWith("/quality-partial-corrections")) {
        posted = body;
        return jsonResponse({
          child_cohort_id: "coh-child", source_cohort_id: "coh-1", target_event_id: "evt-rejected-7",
          quantity: "20", corrected_disposition: "RELEASED",
        });
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision for part of quantity" }));
    fireEvent.change(screen.getByLabelText(/Quantity/), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "wrongly rejected" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posted).not.toBeNull());
    const body = posted as { target_event_id: string; quantity: string; corrected_disposition: string };
    expect(body.target_event_id).toBe("evt-rejected-7");
    expect(body.quantity).toBe("20");
    expect(body.corrected_disposition).toBe("RELEASED");
  });

  it("surfaces a segregation-of-duty conflict with the specific backend message, not a generic denial", async () => {
    stubFetch([queueRow()], (url) => {
      if (url.endsWith("/quality-dispositions")) {
        return jsonResponse(
          { detail: "you received this delivery -- another authorized user must release this quantity" },
          409,
        );
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    const confirmButtons = screen.getAllByRole("button", { name: "Confirm" });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() =>
      expect(screen.getByText(/another authorized user must release this quantity/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/you don't have permission/i)).not.toBeInTheDocument();
  });

  it("surfaces a stale-target correction conflict verbatim", async () => {
    stubFetch([queueRow({ current_state: "HELD" })], (url) => {
      if (url.endsWith("/quality-disposition-corrections")) {
        return jsonResponse(
          { detail: "Quality decision changed since you opened this action. Refresh and review the current decision." },
          409,
        );
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Correct decision" }));
    fireEvent.change(screen.getByLabelText(/Reason \(required\)/), { target: { value: "attempt" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText(/changed since you opened this action/i)).toBeInTheDocument());
  });

  it("STORE-INV-002B: offers an 'Affected location' bucket picker for a partial action with multiple buckets, and threads custody_location_id", async () => {
    let posted: unknown = null;
    stubFetch(
      [queueRow()],
      (url, body) => {
        if (url.endsWith("/quality-partial-dispositions")) {
          posted = body;
          return jsonResponse({ child_cohort_id: "coh-child", source_cohort_id: "coh-1", quantity: "30", disposition: "HELD" });
        }
        return jsonResponse({});
      },
      {
        inventory_quantity_cohort_id: "coh-1", not_put_away_quantity: "200.000",
        buckets: [
          { location_id: null, label: "Not put away", balance: "200.000" },
          { location_id: "bin-1", label: "Main Store / Bin 01", balance: "300.000" },
        ],
      },
    );
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Apply to part of quantity" }));

    await waitFor(() => expect(screen.getByText(/affected location/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/affected location/i), { target: { value: "bin-1" } });
    fireEvent.change(screen.getByLabelText(/^Quantity/), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as { custody_location_id: string | null }).custody_location_id).toBe("bin-1");
  });

  it("shows nothing-to-do message when the queue is empty", async () => {
    stubFetch([]);
    render(withQueryClient(<StoreInventoryQualityPage />));
    await waitFor(() =>
      expect(screen.getByText(/nothing currently needs quality attention/i)).toBeInTheDocument(),
    );
  });
});
