import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { currentTestSearch, setTestSearch } from "@/components/water/waterTestNavigation";
import { withQueryClient } from "@/lib/test-utils";

vi.mock("next/navigation", async () =>
  (await import("@/components/water/waterTestNavigation")).createNavigationMock("/farms/farm-1/water/delivery"),
);

import WaterDeliveryPage from "./page";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ONGOING = {
  id: "del-open", tenant_id: "t", farm_id: "farm-1", reservoir_id: "res-1", irrigation_circuit_id: "ic-1",
  effective_start: "2026-09-24T05:00:00Z", effective_end: null, delivered_volume: null, delivered_volume_uom_id: null,
  nutrient_mix_id: null, notes: null, end_source: null, water_delivery_end_event_id: null, end_note: null,
};
const ENDED = {
  ...ONGOING, id: "del-ended", effective_start: "2026-09-23T05:00:00Z", effective_end: "2026-09-23T06:00:00Z",
  delivered_volume: "120", delivered_volume_uom_id: "u-l", end_source: "RECORDED_AT_CREATION",
};
const ENDED_BY_COMMAND = {
  ...ONGOING, effective_end: "2026-09-24T07:30:00Z", end_source: "END_EVENT", water_delivery_end_event_id: "end-evt-1", end_note: "pump off",
};

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function stubFetch(handlers: { create?: Array<() => Response>; end?: Array<() => Response>; detail?: () => Response; list?: () => Response } = {}) {
  const posts: { url: string; body: string }[] = [];
  const gets: string[] = [];
  const route: Handler = (url, init) => {
    if (init?.method === "POST") {
      posts.push({ url, body: String(init.body) });
      if (url.endsWith("/end")) return handlers.end?.shift()?.() ?? json(ENDED_BY_COMMAND, 201);
      if (url.endsWith("/water-delivery-events")) {
        return handlers.create?.shift()?.() ?? json({ ...ONGOING, id: "del-new", effective_start: "2026-09-24T09:00:00Z" }, 201);
      }
      if (url.includes("/events")) return json({ id: "rev-1", event_type: "FLUSH", effective_at: "2026-09-24T09:00:00Z", reservoir_id: "res-1" }, 201);
    }
    gets.push(url);
    if (url.includes("/water-delivery-events/del-open")) return handlers.detail?.() ?? json(ONGOING);
    if (url.endsWith("/farms/farm-1/water-delivery-events")) return handlers.list?.() ?? json([ENDED, ONGOING]);
    if (url.includes("/reservoir-circuit")) {
      return json([{ id: "l-1", reservoir_id: "res-1", irrigation_circuit_id: "ic-1", effective_from: "2026-01-01T00:00:00Z", effective_to: null }]);
    }
    if (url.includes("/irrigation-circuits")) return json([{ id: "ic-1", code: "IC-1", name: "Zone A drip", status: "active" }]);
    if (url.includes("/reservoirs")) return json([{ id: "res-1", code: "RES-1", name: "Tank A", reservoir_type: "nutrient_reservoir", status: "active" }]);
    if (url.includes("/uoms")) return json([{ id: "u-l", code: "L", name: "Litre", quantity_kind: "volume" }]);
    return json([]);
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => route(String(input), init) as Response));
  return { posts, gets };
}

beforeEach(() => setTestSearch(""));
afterEach(() => vi.unstubAllGlobals());

async function listRows() {
  const region = await screen.findByRole("region", { name: "Irrigation deliveries" });
  return within(region).getAllByRole("listitem");
}

describe("Delivery workspace modes (UX-OPS-001D)", () => {
  it("defaults to Irrigation deliveries, ongoing first, and never renders both modes' forms or histories together", async () => {
    stubFetch();
    render(withQueryClient(<WaterDeliveryPage />));
    const rows = await listRows();
    expect(rows[0]).toHaveTextContent("RES-1 — Tank A → IC-1 — Zone A drip");
    expect(rows[0]).toHaveTextContent("Ongoing");
    expect(rows[0]).toHaveTextContent("Not measured");
    expect(rows[1]).toHaveTextContent("Ended");
    expect(screen.queryByRole("region", { name: "Recent reservoir events" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Record reservoir event" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Reservoir events" }));
    expect(currentTestSearch().get("view")).toBe("reservoir-events");
    await screen.findByRole("region", { name: "Record reservoir event" });
    expect(screen.queryByRole("region", { name: "Irrigation deliveries" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New delivery" })).not.toBeInTheDocument();
  });

  it("restores the mode and selected row from the URL", async () => {
    setTestSearch("selected=del-open");
    stubFetch();
    render(withQueryClient(<WaterDeliveryPage />));
    expect(await screen.findByRole("button", { name: "End Delivery" })).toBeInTheDocument();
  });
});

describe("New Delivery command", () => {
  it("retries an uncertain create with the exact frozen payload: null server-now start, null volume/UOM, notes, command id", async () => {
    const { posts } = stubFetch({ create: [() => json({ detail: "boom" }, 500)] });
    render(withQueryClient(<WaterDeliveryPage />));
    await listRows();
    fireEvent.click(screen.getByRole("button", { name: "New delivery" }));
    const form = within(screen.getByRole("region", { name: "New delivery" }));
    await waitFor(() => expect(form.getByRole("option", { name: "RES-1 — Tank A" })).toBeInTheDocument());
    fireEvent.change(form.getByLabelText("Source Reservoir / Tank"), { target: { value: "res-1" } });
    fireEvent.change(form.getByLabelText("Irrigation Circuit"), { target: { value: "ic-1" } });
    await waitFor(() => expect(screen.getByTestId("connection-status")).toHaveTextContent(/Configured connection/));
    fireEvent.change(form.getByLabelText("Notes (optional)"), { target: { value: "night cycle" } });
    fireEvent.click(form.getByRole("button", { name: "Review delivery" }));

    const review = within(await screen.findByRole("region", { name: "Review new delivery" }));
    expect(review.getByText("Not measured")).toBeInTheDocument();
    expect(review.getByText("Now (server time)")).toBeInTheDocument();
    fireEvent.click(review.getByRole("button", { name: "Record delivery" }));

    await screen.findByRole("button", { name: "Retry" });
    // Locked: mode tabs, list selection, and New are unavailable; no Cancel.
    expect(screen.getByRole("tab", { name: "Reservoir events" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "New delivery" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Delivery recorded — confirmed by the server.");
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toBe(posts[0].body);
    expect(JSON.parse(posts[0].body)).toEqual({
      reservoir_id: "res-1", irrigation_circuit_id: "ic-1", effective_start: null, effective_end: null,
      delivered_volume: null, delivered_volume_uom_id: null, nutrient_mix_id: null, notes: "night cycle",
      client_command_id: expect.any(String),
    });
  });
});

describe("End Delivery command", () => {
  async function openEndReview(note = "pump off") {
    await listRows();
    fireEvent.click(screen.getAllByRole("button", { name: /RES-1 — Tank A → IC-1/ })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "End Delivery" }));
    const flow = within(screen.getByRole("region", { name: "End Delivery" }));
    // Proposed once, visible, editable.
    const endInput = flow.getByLabelText(/End time \(required/);
    fireEvent.change(endInput, { target: { value: "2026-09-24T07:30" } });
    fireEvent.change(flow.getByLabelText("Note (optional)"), { target: { value: note } });
    fireEvent.click(flow.getByRole("button", { name: "Review End Delivery" }));
    return within(await screen.findByRole("region", { name: "Review End Delivery" }));
  }

  it("sends only end, note, and command id, and renders the resolved D0 fields from the 201 response", async () => {
    const { posts } = stubFetch();
    render(withQueryClient(<WaterDeliveryPage />));
    const review = await openEndReview();
    expect(review.getByText(/original Delivery record stays unchanged/)).toBeInTheDocument();
    expect(review.getByText(/No final volume is being recorded/)).toBeInTheDocument();
    fireEvent.click(review.getByRole("button", { name: "End Delivery" }));

    const receipt = within(await screen.findByRole("region", { name: "End Delivery receipt" }));
    expect(posts).toHaveLength(1);
    expect(posts[0].url).toContain("/farms/farm-1/water-delivery-events/del-open/end");
    const body = JSON.parse(posts[0].body);
    expect(Object.keys(body).sort()).toEqual(["client_command_id", "effective_end", "note"]);
    expect(body.effective_end).toBe(new Date("2026-09-24T07:30").toISOString());
    expect(body.note).toBe("pump off");
    expect(receipt.getByText(/END_EVENT/)).toBeInTheDocument();
    expect(receipt.getByText("end-evt-1")).toBeInTheDocument();
    expect(receipt.getByText("pump off")).toBeInTheDocument();
  });

  it("an uncertain End locks target and mode, and Retry resends the exact frozen request", async () => {
    const { posts } = stubFetch({ end: [() => json({ detail: "x" }, 503)] });
    render(withQueryClient(<WaterDeliveryPage />));
    const review = await openEndReview();
    fireEvent.click(review.getByRole("button", { name: "End Delivery" }));
    await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByRole("tab", { name: "Reservoir events" })).toBeDisabled();
    for (const row of screen.getAllByRole("button", { name: /RES-1 — Tank A → IC-1/ })) expect(row).toBeDisabled();
    expect(screen.getByRole("button", { name: "Back to edit" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("region", { name: "End Delivery receipt" });
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toBe(posts[0].body);
  });

  it("a stale 409 refreshes and shows the authoritative ended state without submitting anything new", async () => {
    let ended = false;
    const { posts, gets } = stubFetch({
      end: [() => { ended = true; return json({ detail: "water delivery event del-open is already ended" }, 409); }],
      detail: () => json(ended ? ENDED_BY_COMMAND : ONGOING),
      list: () => json(ended ? [ENDED, ENDED_BY_COMMAND] : [ENDED, ONGOING]),
    });
    render(withQueryClient(<WaterDeliveryPage />));
    const review = await openEndReview();
    const detailGetsBefore = gets.filter((g) => g.includes("/water-delivery-events/del-open")).length;
    fireEvent.click(review.getByRole("button", { name: "End Delivery" }));

    await screen.findByText(/already ended\. Showing the delivery's current recorded state/);
    await waitFor(() => expect(screen.getByText("End Delivery command")).toBeInTheDocument());
    expect(gets.filter((g) => g.includes("/water-delivery-events/del-open")).length).toBeGreaterThan(detailGetsBefore);
    expect(screen.queryByRole("button", { name: "End Delivery" })).not.toBeInTheDocument();
    expect(posts).toHaveLength(1);
  });

  it("a definitive 422 returns to edit and the next submission is a new command", async () => {
    const { posts } = stubFetch({ end: [() => json({ detail: "effective_end cannot be before the delivery's effective_start" }, 422)] });
    render(withQueryClient(<WaterDeliveryPage />));
    const review = await openEndReview();
    fireEvent.click(review.getByRole("button", { name: "End Delivery" }));
    await screen.findByText(/cannot be before the delivery's effective_start/);
    const flow = within(screen.getByRole("region", { name: "End Delivery" }));
    fireEvent.click(flow.getByRole("button", { name: "Review End Delivery" }));
    fireEvent.click(within(await screen.findByRole("region", { name: "Review End Delivery" })).getByRole("button", { name: "End Delivery" }));
    await screen.findByRole("region", { name: "End Delivery receipt" });
    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[1].body).client_command_id).not.toBe(JSON.parse(posts[0].body).client_command_id);
  });
});
