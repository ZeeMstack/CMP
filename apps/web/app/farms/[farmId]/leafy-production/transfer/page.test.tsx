import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import ProductionTransferPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProductionTransferPage breadcrumb", () => {
  it("breadcrumbs under Production Operations using the approved grouped-nav label Transfer to Production", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<ProductionTransferPage />));

    const breadcrumbNav = await waitFor(() => screen.getByRole("navigation", { name: "Breadcrumb" }));
    expect(within(breadcrumbNav).getByText("Production Operations")).toBeInTheDocument();
    expect(within(breadcrumbNav).getByText("Transfer to Production")).toBeInTheDocument();
    expect(within(breadcrumbNav).queryByText("Batches")).not.toBeInTheDocument();
  });
});
