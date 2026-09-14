import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-123" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import ScanPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubFetch(handler: (url: string) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => handler(String(input))),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const carrierScanContext = {
  entity_type: "carrier",
  qr_identifier_id: "qr-1",
  farm_id: "farm-1",
  code: "PP-0147",
  carrier_type_name: "Production Cultivation Plate",
  status: "active",
  current_batch: { id: "batch-1", code: "B-LET-2026-014", crop: { code: "ICE", common_name: "Iceberg" }, variety: { code: "MAM", name: "Mamutik" } },
  current_location: { path_string: "GH-01 / Zone 2 / Span 4 / Table 07", codes: ["GH-01", "Z02", "S04", "T07"] },
  unresolved_reason: null,
  actions: [{ label: "Record Observation", href: "/farms/farm-1/observations?crop_batch_id=batch-1" }],
  work_items: [{ id: "wi-1", code: "WI-0001", title: "Check EC/pH", status: "open", priority: "normal" }],
};

describe("ScanPage (/q/[token])", () => {
  it("shows readable entity identity -- never a raw UUID as the primary label", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(carrierScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());
    expect(screen.queryByText("qr-1")).not.toBeInTheDocument();
    expect(screen.getByText("Production Cultivation Plate")).toBeInTheDocument();
  });

  it("shows current Batch/location dynamically for a Carrier scan", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(carrierScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());
    expect(screen.getByText(/B-LET-2026-014/)).toBeInTheDocument();
    expect(screen.getByText("GH-01 / Zone 2 / Span 4 / Table 07")).toBeInTheDocument();
  });

  it("exposes prepared action links", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(carrierScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByRole("link", { name: "Record Observation" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Record Observation" })).toHaveAttribute(
      "href",
      "/farms/farm-1/observations?crop_batch_id=batch-1",
    );
  });

  it("shows matching Work Items", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(carrierScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Check EC/pH")).toBeInTheDocument());
  });

  it("renders a failed resolve as a distinct error state -- never as an empty/not-assigned entity", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse({ detail: "Not found" }, 404) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/not assigned/i)).not.toBeInTheDocument();
    expect(screen.queryByText("PP-0147")).not.toBeInTheDocument();
  });
});
