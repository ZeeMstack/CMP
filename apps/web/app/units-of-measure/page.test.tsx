import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import UnitsOfMeasurePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const UOMS = [
  { id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" },
  { id: "uom-2", code: "SEED", name: "Seed", quantity_kind: "count", conversion_family: null },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UnitsOfMeasurePage", () => {
  it("renders the exact seeded catalog, read-only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(UOMS)));
    render(withQueryClient(<UnitsOfMeasurePage />));

    await waitFor(() => expect(screen.getByText("kg")).toBeInTheDocument());
    expect(screen.getByText("Kilogram")).toBeInTheDocument();
    expect(screen.getByText("SEED")).toBeInTheDocument();
  });

  it("never renders a create/edit/delete control", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(UOMS)));
    render(withQueryClient(<UnitsOfMeasurePage />));
    await waitFor(() => expect(screen.getByText("kg")).toBeInTheDocument());

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
