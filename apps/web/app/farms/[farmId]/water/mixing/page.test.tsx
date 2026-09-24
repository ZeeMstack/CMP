import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setTestSearch } from "@/components/water/waterTestNavigation";
import { withQueryClient } from "@/lib/test-utils";

vi.mock("next/navigation", async () =>
  (await import("@/components/water/waterTestNavigation")).createNavigationMock("/farms/farm-1/water/mixing"),
);

import WaterMixingPage, { mixVolumeVariance } from "./page";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const UOMS = [
  { id: "u-l", code: "L", name: "Litre", quantity_kind: "volume", conversion_family: null },
  { id: "u-ml", code: "mL", name: "Millilitre", quantity_kind: "volume", conversion_family: null },
];

function stubFetch(mixResponses: Array<() => Response>) {
  const posts: { url: string; body: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        posts.push({ url, body: String(init.body) });
        const next = mixResponses.shift();
        if (next) return next();
        return json({
          id: "mix-1", tenant_id: "t", farm_id: "farm-1", reservoir_id: "res-1", nutrient_recipe_version_id: "ver-1",
          effective_at: "2026-09-24T08:00:00Z", recorded_at: "2026-09-24T08:00:00Z", target_volume: "500",
          actual_volume: "480", notes: null,
        }, 201);
      }
      if (url.includes("/nutrient-mixes/mix-1/inputs")) {
        return json([{ id: "in-1", tenant_id: "t", nutrient_mix_id: "mix-1", inventory_item_id: null, component_label: "Part A", actual_quantity: "2.4", actual_quantity_uom_id: "u-l", sequence_number: 1, note: null }]);
      }
      if (url.includes("/nutrient-recipe-versions/ver-1/components")) {
        return json([{ id: "c-1", component_label: "Part A", target_quantity: "2.5", target_quantity_uom_id: "u-l" }]);
      }
      if (url.includes("/nutrient-recipes/rec-1/versions")) {
        return json([{ id: "ver-1", nutrient_recipe_id: "rec-1", version_number: 3, state: "active", target_ec: "1.8", target_ph: "5.9" }]);
      }
      if (url.includes("/nutrient-recipes")) return json([{ id: "rec-1", code: "NR-1", name: "Lettuce base", status: "active" }]);
      if (url.includes("/units-of-measure") || url.includes("/uoms")) return json(UOMS);
      if (url.includes("/reservoirs")) return json([{ id: "res-1", code: "RES-1", name: "Tank A", reservoir_type: "nutrient_reservoir", status: "active" }]);
      return json([]);
    }),
  );
  return posts;
}

async function configure() {
  await waitFor(() => expect(screen.getByRole("option", { name: /RES-1 — Tank A/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Reservoir / Tank"), { target: { value: "res-1" } });
  await waitFor(() => expect(screen.getByRole("option", { name: "NR-1 — Lettuce base" })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Recipe (optional, guidance only)"), { target: { value: "rec-1" } });
  await waitFor(() => expect(screen.getByRole("option", { name: /v3/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Recipe Version"), { target: { value: "ver-1" } });
  await screen.findByRole("region", { name: "Recipe target guidance" });
  await waitFor(() => expect(screen.getAllByRole("option", { name: "L" }).length).toBeGreaterThan(0));
}

beforeEach(() => setTestSearch(""));
afterEach(() => vi.unstubAllGlobals());

describe("mixVolumeVariance", () => {
  it("is calculated only for directly identical units, with exact decimals", () => {
    expect(mixVolumeVariance("500", "u-l", "480.5", "u-l")).toBe("−19.5");
    expect(mixVolumeVariance("500", "u-l", "480", "u-ml")).toBeNull();
    expect(mixVolumeVariance(null, "u-l", "480", "u-l")).toBeNull();
  });
});

describe("Mixing workspace (UX-OPS-001D)", () => {
  it("keeps the Recipe target as separate guidance and never prefills actual inputs from it", async () => {
    stubFetch([]);
    render(withQueryClient(<WaterMixingPage />));
    await configure();
    const guidance = screen.getByRole("region", { name: "Recipe target guidance" });
    await within(guidance).findByText(/Part A: target 2.5/);
    const inputs = within(screen.getByRole("region", { name: "Actual inputs" }));
    expect(inputs.getByLabelText("Input 1 component")).toHaveValue("");
    expect(inputs.getByLabelText("Input 1 actual quantity")).toHaveValue("");
    expect(screen.queryByRole("region", { name: "Recent mixes" })).not.toBeInTheDocument();
  });

  it("Review carries the whole ordered input array; an uncertain Retry resends it byte-for-byte, then shows the receipt", async () => {
    const posts = stubFetch([() => json({ detail: "gateway" }, 502)]);
    render(withQueryClient(<WaterMixingPage />));
    await configure();
    fireEvent.change(screen.getByLabelText("Target volume"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("Target unit"), { target: { value: "u-l" } });
    fireEvent.change(screen.getByLabelText("Actual volume"), { target: { value: "480" } });
    fireEvent.change(screen.getByLabelText("Actual unit"), { target: { value: "u-l" } });
    expect(screen.getByText("Variance: −20 L")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Add input row" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add input row" }));
    const rows = [
      ["Part A", "2.4", "u-l", ""],
      ["Part B", "1500", "u-ml", "after A"],
      ["Acid", "0.2", "u-l", ""],
    ];
    rows.forEach(([label, qty, uom, note], i) => {
      fireEvent.change(screen.getByLabelText(`Input ${i + 1} component`), { target: { value: label } });
      fireEvent.change(screen.getByLabelText(`Input ${i + 1} actual quantity`), { target: { value: qty } });
      fireEvent.change(screen.getByLabelText(`Input ${i + 1} unit`), { target: { value: uom } });
      fireEvent.change(screen.getByLabelText(`Input ${i + 1} note`), { target: { value: note } });
    });
    fireEvent.click(screen.getByRole("button", { name: "Review mix" }));
    const reviewed = within(await screen.findByRole("list", { name: "Actual inputs" }));
    expect(reviewed.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("1. Part A: 2.4 L"),
      expect.stringContaining("2. Part B: 1500 mL"),
      expect.stringContaining("3. Acid: 0.2 L"),
    ]);
    expect(screen.getByText("NR-1 — Lettuce base · v3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Record mix" }));
    await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByRole("button", { name: "Back to edit" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Recent mixes" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Mix recorded — confirmed by the server.");
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toBe(posts[0].body);
    expect(posts[0].url).toContain("/farms/farm-1/reservoirs/res-1/nutrient-mixes");
    const body = JSON.parse(posts[0].body);
    expect(body).toMatchObject({
      nutrient_recipe_version_id: "ver-1", effective_at: null, target_volume: "500", target_volume_uom_id: "u-l",
      actual_volume: "480", actual_volume_uom_id: "u-l", notes: null,
    });
    expect(body.inputs).toEqual([
      { component_label: "Part A", inventory_item_id: null, actual_quantity: "2.4", actual_quantity_uom_id: "u-l", sequence_number: 1, note: null },
      { component_label: "Part B", inventory_item_id: null, actual_quantity: "1500", actual_quantity_uom_id: "u-ml", sequence_number: 2, note: "after A" },
      { component_label: "Acid", inventory_item_id: null, actual_quantity: "0.2", actual_quantity_uom_id: "u-l", sequence_number: 3, note: null },
    ]);
    // Receipt: confirmed mix, server time, recipe, recorded inputs, next links.
    expect(screen.getByText("mix-1")).toBeInTheDocument();
    await screen.findByText(/1\. Part A: 2.4 L/);
    expect(screen.getByRole("link", { name: "Record a measurement" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Record a delivery" })).toBeInTheDocument();
  });
});
