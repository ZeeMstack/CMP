import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setTestSearch } from "@/components/water/waterTestNavigation";
import { withQueryClient } from "@/lib/test-utils";

vi.mock("next/navigation", async () =>
  (await import("@/components/water/waterTestNavigation")).createNavigationMock("/farms/farm-1/water/measurements"),
);

import WaterMeasurementsPage from "./page";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const SAMPLING_POINT = {
  id: "sp-1", tenant_id: "t", farm_id: "farm-1", code: "SP-1", name: "Tank A sample", point_type: "reservoir",
  water_source_id: null, reservoir_id: "res-1", irrigation_circuit_id: null, water_delivery_point_id: null,
  water_return_point_id: null, status: "active", notes: null,
};

type Post = { url: string; body: string };

function stubFetch(responses: Array<(body: Record<string, unknown>, n: number) => Response>) {
  const posts: Post[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        posts.push({ url, body: String(init.body) });
        const body = JSON.parse(String(init.body));
        const next = responses.shift();
        return next
          ? next(body, posts.length)
          : json({ id: `m-${posts.length}`, ...body, value: String(body.value), effective_at: `2026-09-24T08:0${posts.length}:00Z`, recorded_at: "2026-09-24T08:00:00Z" }, 201);
      }
      if (url.includes("/sampling-points")) return json([SAMPLING_POINT]);
      if (url.includes("/reservoirs")) return json([{ id: "res-1", code: "RES-1", name: "Tank A", reservoir_type: "nutrient_reservoir", status: "active" }]);
      return json([]);
    }),
  );
  return posts;
}

async function fillAndReview(values: Record<string, string>) {
  await waitFor(() => expect(screen.getByRole("option", { name: /SP-1 — Tank A sample/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Sampling Point"), { target: { value: "sp-1" } });
  expect(screen.getByTestId("sampling-point-context")).toHaveTextContent("Reservoir / Tank: RES-1 — Tank A");
  for (const [label, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(new RegExp(`^${label} value`)), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Review measurements" }));
  await screen.findByText("Review before recording");
}

beforeEach(() => setTestSearch(""));
afterEach(() => vi.unstubAllGlobals());

describe("Measurements workspace (UX-OPS-001D)", () => {
  it("defaults to Record without stacking History, and Review lists only the filled rows", async () => {
    stubFetch([]);
    render(withQueryClient(<WaterMeasurementsPage />));
    expect(screen.getByRole("tab", { name: "Record" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("region", { name: "Measurement history" })).not.toBeInTheDocument();

    await fillAndReview({ pH: "6.1", "Dissolved oxygen": "8.2" });
    const selected = within(screen.getByRole("list", { name: "Selected rows" }));
    expect(selected.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("pH: 6.1 pH"),
      expect.stringContaining("Dissolved oxygen: 8.2 mg/L"),
    ]);
    expect(screen.getByText(/Now \(server time\)/)).toBeInTheDocument();
  });

  it("sends one independent command per selected metric with its own stable id and null server-now time", async () => {
    const posts = stubFetch([]);
    render(withQueryClient(<WaterMeasurementsPage />));
    await fillAndReview({ pH: "6.1", EC: "1.8" });
    fireEvent.click(screen.getByRole("button", { name: "Record 2 measurement(s)" }));

    await screen.findByText(/Measurements recorded — 2 of 2 confirmed/);
    expect(posts).toHaveLength(2);
    expect(posts.every((p) => p.url.endsWith("/farms/farm-1/sampling-points/sp-1/measurements"))).toBe(true);
    const bodies = posts.map((p) => JSON.parse(p.body));
    expect(bodies.map((b) => b.metric)).toEqual(["PH", "EC"]);
    expect(bodies.map((b) => b.effective_at)).toEqual([null, null]);
    expect(new Set(bodies.map((b) => b.client_command_id)).size).toBe(2);
    // Receipt lists each authoritative id + server effective time.
    expect(screen.getByText("m-1")).toBeInTheDocument();
    expect(screen.getByText("m-2")).toBeInTheDocument();
  });

  it("partial run: an uncertain row locks the workspace, Retry resends it byte-for-byte, and a confirmed row is never resent", async () => {
    const posts = stubFetch([
      (body, n) => json({ id: `m-${n}`, ...body, value: String(body.value), effective_at: "2026-09-24T08:00:00Z", recorded_at: "x" }, 201),
      () => json({ detail: "upstream down" }, 503),
    ]);
    render(withQueryClient(<WaterMeasurementsPage />));
    await fillAndReview({ pH: "6.1", EC: "1.8", "Solution temperature": "21" });
    fireEvent.click(screen.getByRole("button", { name: "Record 3 measurement(s)" }));

    await screen.findByRole("button", { name: "Retry EC" });
    expect(screen.getByText("1 of 3 confirmed")).toBeInTheDocument();
    expect(within(screen.getByTestId("run-row-PH")).getByText("Confirmed")).toBeInTheDocument();
    expect(within(screen.getByTestId("run-row-EC")).getByText("Unconfirmed — retry")).toBeInTheDocument();
    expect(within(screen.getByTestId("run-row-SOLUTION_TEMPERATURE")).getByText("Not sent")).toBeInTheDocument();
    expect(screen.queryByText(/^Measurements recorded/)).not.toBeInTheDocument();
    // Local mode + sub-nav are locked; no discard/cancel exists.
    expect(screen.getByRole("tab", { name: "History" })).toBeDisabled();
    expect(within(screen.getByRole("navigation", { name: "Water & Nutrients" })).queryByRole("link", { name: "Mixing" })).toBeNull();
    expect(screen.queryByRole("button", { name: /cancel|start over|discard/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry EC" }));
    await screen.findByText(/Measurements recorded — 3 of 3 confirmed/);
    expect(posts).toHaveLength(4);
    expect(posts[2].body).toBe(posts[1].body);
    expect(JSON.parse(posts[3].body).metric).toBe("SOLUTION_TEMPERATURE");
    expect(posts.filter((p) => JSON.parse(p.body).metric === "PH")).toHaveLength(1);
  });

  it("a definitive rejection keeps confirmed rows as a partial receipt and returns only unconfirmed rows to edit", async () => {
    const posts = stubFetch([
      (body, n) => json({ id: `m-${n}`, ...body, value: String(body.value), effective_at: "2026-09-24T08:00:00Z", recorded_at: "x" }, 201),
      () => json({ detail: "metric 'EC' requires unit 'mS/cm'" }, 422),
    ]);
    render(withQueryClient(<WaterMeasurementsPage />));
    await fillAndReview({ pH: "6.1", EC: "1.8" });
    fireEvent.click(screen.getByRole("button", { name: "Record 2 measurement(s)" }));
    await screen.findByRole("button", { name: "Return unconfirmed rows to edit" });
    expect(screen.getByRole("alert")).toHaveTextContent("requires unit");

    fireEvent.click(screen.getByRole("button", { name: "Return unconfirmed rows to edit" }));
    expect(screen.getByText(/Partial result — these rows are recorded/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^pH value/)).toHaveValue(null);
    expect(screen.getByLabelText(/^EC value/)).toHaveValue(1.8);

    fireEvent.click(screen.getByRole("button", { name: "Review measurements" }));
    fireEvent.click(await screen.findByRole("button", { name: "Record 1 measurement(s)" }));
    await screen.findByText(/Measurements recorded — 1 of 1 confirmed/);
    // The resubmitted EC row is a NEW command; pH was never sent again.
    expect(JSON.parse(posts[2].body).client_command_id).not.toBe(JSON.parse(posts[1].body).client_command_id);
    expect(posts.filter((p) => JSON.parse(p.body).metric === "PH")).toHaveLength(1);
    // The partial receipt from the first run is still listed.
    expect(screen.getByText("m-1")).toBeInTheDocument();
  });
});
