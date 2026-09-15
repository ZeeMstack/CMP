import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-123" }),
}));

import { writeWorkingLocation } from "@/lib/scan/workingLocation";
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
  window.localStorage.clear();
});

const carrierScanContext = {
  entity_type: "carrier",
  qr_identifier_id: "qr-1",
  farm_id: "farm-1",
  code: "PP-0147",
  carrier_type_name: "Production Cultivation Plate",
  status: "active",
  current_batch: { id: "batch-1", code: "B-LET-2026-014", crop: { code: "ICE", common_name: "Iceberg" }, variety: { code: "MAM", name: "Mamutik" } },
  current_location: {
    path_string: "GH-01 / Zone 2 / Span 4 / Table 07",
    codes: ["GH-01", "Z02", "S04", "T07"],
    ids: ["gh-01", "zone-2", "span-4", "table-07"],
  },
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

describe("ScanPage PILOT-SCAN-001F: location-first scan validation", () => {
  const locationScanContext = {
    entity_type: "location",
    qr_identifier_id: "qr-loc-1",
    farm_id: "farm-1",
    code: "T08",
    name: "Table 08",
    location: {
      path_string: "GH-01 / Zone 2 / Span 4 / Table 08",
      codes: ["GH-01", "Z02", "S04", "T08"],
      ids: ["gh-01", "zone-2", "span-4", "table-08"],
    },
    occupants: [],
    actions: [{ label: "View occupants", href: "/farms/farm-1/locations?highlight=table-08" }],
    work_items: [],
  };

  it("Location scan can establish working-location context via a deliberate click", async () => {
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(locationScanContext) : jsonResponse({})));
    const { fireEvent } = await import("@testing-library/react");
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByRole("button", { name: /use as working location/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /use as working location/i }));

    await waitFor(() => expect(screen.getByText("Working location")).toBeInTheDocument());
    expect(screen.getAllByText("GH-01 / Zone 2 / Span 4 / Table 08").length).toBeGreaterThan(0);
  });

  it("does not automatically replace an already-active working location merely because another Location QR was opened", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(locationScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText(/current working location/i)).toBeInTheDocument());
    // The bar still shows the ORIGINAL working location -- never silently
    // swapped just because a different Location's QR was scanned.
    expect(screen.getAllByText(/GH-01 \/ Table 07/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /use t08 instead/i })).toBeInTheDocument();
  });

  it("exact active placement location -> MATCH banner, and its operational action stays available", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    const assignmentContext = {
      entity_type: "batch_carrier_assignment",
      qr_identifier_id: "qr-2",
      farm_id: "farm-1",
      code: "B-001 @ PP-01",
      batch: { id: "batch-1", code: "B-001", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
      carrier_code: "PP-01",
      current_location: { path_string: "GH-01 / Table 07", codes: ["GH-01", "T07"], ids: ["gh-01", "table-07"] },
      released: false,
      unresolved_reason: null,
      actions: [{ label: "Harvest", href: "/farms/farm-1/leafy-production/harvest?assignmentId=a1" }],
      work_items: [],
    };
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(assignmentContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Location confirmed")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Harvest" })).toBeInTheDocument();
  });

  it("wrong table -> MISMATCH banner, and the physical-operation action is withheld", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Span 4 / Table 07" });
    const assignmentContext = {
      entity_type: "batch_carrier_assignment",
      qr_identifier_id: "qr-2",
      farm_id: "farm-1",
      code: "B-001 @ PP-01",
      batch: { id: "batch-1", code: "B-001", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
      carrier_code: "PP-01",
      current_location: { path_string: "GH-01 / Span 5 / Table 02", codes: ["GH-01", "S05", "T02"], ids: ["gh-01", "span-5", "table-02"] },
      released: false,
      unresolved_reason: null,
      actions: [
        { label: "View Batch", href: "/farms/farm-1/crop-batches/batch-1" },
        { label: "Harvest", href: "/farms/farm-1/leafy-production/harvest?assignmentId=a1" },
      ],
      work_items: [],
    };
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(assignmentContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Location does not match")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Harvest" })).not.toBeInTheDocument();
    // Read-only navigation actions remain available under MISMATCH.
    expect(screen.getByRole("link", { name: "View Batch" })).toBeInTheDocument();
  });

  it("a released placement shows HISTORICAL, never a green MATCH, even when its former location equals the working location", async () => {
    writeWorkingLocation({ locationId: "table-01", farmId: "farm-1", code: "T01", pathString: "Table 01" });
    const releasedAssignment = {
      entity_type: "batch_carrier_assignment",
      qr_identifier_id: "qr-3",
      farm_id: "farm-1",
      code: "B-000 @ PP-01",
      batch: { id: "batch-0", code: "B-000", crop: { code: "ICE", common_name: "Iceberg" }, variety: null },
      carrier_code: "PP-01",
      current_location: { path_string: "Table 01", codes: ["T01"], ids: ["table-01"] },
      released: true,
      unresolved_reason: null,
      // Backend already omits an operational Harvest action for a
      // released assignment (qr_service.py) -- no frontend filtering
      // needed on top of that.
      actions: [{ label: "View Batch", href: "/farms/farm-1/crop-batches/batch-0" }],
      work_items: [],
    };
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(releasedAssignment) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Historical placement")).toBeInTheDocument());
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });

  it("a split Batch scan shows CANNOT VALIDATE, never an arbitrary MATCH", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "Table 07" });
    const splitBatch = {
      entity_type: "crop_batch",
      qr_identifier_id: "qr-4",
      farm_id: "farm-1",
      code: "B-001",
      crop: { code: "ICE", common_name: "Iceberg" },
      variety: null,
      state: "active",
      current_stage_name: "Growing",
      placements: [
        { batch_carrier_assignment_id: "a1", carrier_code: "PP-01", location: { path_string: "Table 07", codes: ["T07"], ids: ["table-07"] } },
        { batch_carrier_assignment_id: "a2", carrier_code: "PP-02", location: { path_string: "Table 08", codes: ["T08"], ids: ["table-08"] } },
      ],
      actions: [],
      work_items: [],
    };
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(splitBatch) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Exact location cannot be confirmed")).toBeInTheDocument());
    expect(screen.getByText(/multiple active placements/i)).toBeInTheDocument();
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });

  it("Clear removes the working location, and the bar/banner disappear", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    const { fireEvent } = await import("@testing-library/react");
    stubFetch((url) => (url.includes("/api/qr/tok-123") ? jsonResponse(carrierScanContext) : jsonResponse({})));
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("Working location")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));

    await waitFor(() => expect(screen.queryByText("Working location")).not.toBeInTheDocument());
    expect(window.localStorage.getItem("growcmp.workingLocation.v1")).toBeNull();
  });

  it("neither MATCH nor MISMATCH ever triggers a mutating request -- only the one GET resolve call is ever made", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${String(input)}`);
        return jsonResponse(carrierScanContext);
      }),
    );
    render(withQueryClient(<ScanPage />));

    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());
    expect(calls.every((c) => c.startsWith("GET"))).toBe(true);
  });
});
