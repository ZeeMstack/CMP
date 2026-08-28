import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import IntersaladsTransplantPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/** UI-OPT-001 Batch C: operator-facing wording changes to "Transfer to
 * Inter Leafy Greens" -- the route (/nursery/intersalads) and every
 * internal identifier (component name, hooks, InterSalads domain
 * vocabulary) stay unchanged; only this page's visible title/breadcrumb
 * and the journey indicator use the new operator-facing label. */
describe("IntersaladsTransplantPage", () => {
  it("shows the operator-facing 'Transfer to Inter Leafy Greens' title, not the internal name", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<IntersaladsTransplantPage />));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Transfer to Inter Leafy Greens" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "InterSalads" })).not.toBeInTheDocument();
  });

  it("shows the Nursery journey indicator with the transfer stage current", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<IntersaladsTransplantPage />));

    await waitFor(() => expect(screen.getByRole("navigation", { name: "Nursery journey" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ })).toHaveAttribute(
      "aria-current",
      "step",
    );
  });
});
