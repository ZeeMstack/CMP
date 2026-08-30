import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import FarmSetupReadinessPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function readinessPayload() {
  return {
    farm_id: "farm-1",
    overall: "incomplete",
    milestones: [
      {
        code: "sowing",
        label: "Sowing Readiness",
        status: "ready",
        items: [
          { code: "farm_exists", label: "Farm exists", status: "pass", detail: "" },
          { code: "crop_configured", label: "Crop configured", status: "pass", detail: "" },
          {
            code: "seed_tray_specification",
            label: "Seed Tray Carrier Specification registered",
            status: "not_applicable",
            detail: "the coherent Workflow's start stage declares no required carrier type",
          },
        ],
      },
      {
        code: "production",
        label: "Production Readiness",
        status: "incomplete",
        items: [
          {
            code: "nursery_intersalads_structure",
            label: "Nursery Inter Leafy Greens (InterSalads) structure",
            status: "missing",
            detail: "",
          },
          {
            code: "leafy_production_structure",
            label: "Leafy Production greenhouse with Zone -> Span -> Grow Table",
            status: "warning",
            detail: "structure exists but is minimal",
          },
        ],
      },
      {
        code: "post_harvest",
        label: "Post-Harvest Readiness",
        status: "incomplete",
        items: [
          { code: "packing_hall_location", label: "Packing Hall location configured", status: "missing", detail: "" },
        ],
      },
      {
        code: "full_pilot",
        label: "Full Pilot Readiness",
        status: "incomplete",
        items: [
          { code: "farm_exists", label: "Farm exists", status: "pass", detail: "" },
          { code: "packing_hall_location", label: "Packing Hall location configured", status: "missing", detail: "" },
        ],
      },
    ],
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FarmSetupReadinessPage", () => {
  it("renders one section per milestone with its READY/INCOMPLETE status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(readinessPayload())));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByText("Sowing Readiness")).toBeInTheDocument());
    expect(screen.getByText("Production Readiness")).toBeInTheDocument();
    expect(screen.getByText("Post-Harvest Readiness")).toBeInTheDocument();
    expect(screen.getByText("Full Pilot Readiness")).toBeInTheDocument();

    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Incomplete").length).toBeGreaterThanOrEqual(3);
  });

  it("shows a passing item accessibly, without a fix link", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(readinessPayload())));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByText("Crop configured")).toBeInTheDocument());
    const row = screen.getByText("Crop configured").closest("li");
    expect(row).not.toBeNull();
    expect(row!.textContent).toMatch(/Configured/);
    expect(screen.queryAllByRole("link", { name: "Fix" }).length).toBeGreaterThan(0); // exists elsewhere, not on this row
    const fixLinksInRow = row!.querySelectorAll("a");
    expect(fixLinksInRow.length).toBe(0);
  });

  it("shows a missing item accessibly and links to the correct existing setup route", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(readinessPayload())));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getAllByText("Packing Hall location configured").length).toBeGreaterThan(0));
    const rows = screen.getAllByText("Packing Hall location configured").map((el) => el.closest("li")!);
    for (const row of rows) {
      expect(row.textContent).toMatch(/Missing/);
      const link = row.querySelector("a");
      expect(link).not.toBeNull();
      expect(link).toHaveAttribute("href", "/farms/farm-1/locations");
    }
  });

  it("never renders a manual completion control", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(readinessPayload())));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByText("Sowing Readiness")).toBeInTheDocument());
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/mark complete/i)).not.toBeInTheDocument();
    // No tenant override / platform-admin affordance on this page.
    expect(screen.queryByText(/platform admin|tenant override|X-CMP-Tenant-Id/i)).not.toBeInTheDocument();
  });

  it("supports a manual refresh that re-fetches readiness", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(readinessPayload()));
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByText("Sowing Readiness")).toBeInTheDocument());
    const callsBefore = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("renders a safe error state when the backend request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "boom" }, 500)));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("keeps every fix link present regardless of viewport width (no CSS visually hides them)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(readinessPayload())));
    render(withQueryClient(<FarmSetupReadinessPage />));

    await waitFor(() => expect(screen.getByText("Sowing Readiness")).toBeInTheDocument());
    const fixLinks = screen.getAllByRole("link", { name: "Fix" });
    expect(fixLinks.length).toBeGreaterThan(0);
    for (const link of fixLinks) {
      expect(link).not.toHaveClass("hidden");
      expect(link).toBeVisible();
    }
  });
});
