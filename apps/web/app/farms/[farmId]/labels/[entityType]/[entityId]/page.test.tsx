import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", entityType: "carrier", entityId: "carrier-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import LabelPreviewPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type FetchCall = { url: string; init?: RequestInit };

const qrIdentifier = { id: "qr-1", entity_type: "carrier", token: "tok-abc", created_at: "2026-01-01T00:00:00Z" };
const carrierScanContext = {
  entity_type: "carrier",
  qr_identifier_id: "qr-1",
  farm_id: "farm-1",
  code: "PP-0147",
  carrier_type_name: "Production Cultivation Plate",
  status: "active",
  current_batch: null,
  current_location: null,
  unresolved_reason: "occupant has no active occupancy",
  actions: [],
  work_items: [],
};

function stubFetch(onPost?: (call: FetchCall) => Response | undefined) {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (init?.method === "POST") {
        if (url.includes("/api/farms/farm-1/qr/carrier/carrier-1/generate")) return jsonResponse(qrIdentifier);
        if (url.includes("/api/qr/tok-abc/print")) {
          const wasReprinted = calls.filter((c) => c.url.includes("/print")).length > 1;
          return jsonResponse({ qr_identifier_id: "qr-1", printed_at: "2026-01-01T00:00:00Z", is_reprint: wasReprinted });
        }
        const overridden = onPost?.({ url, init });
        if (overridden) return overridden;
      }
      if (url.includes("/api/qr/tok-abc")) return jsonResponse(carrierScanContext);
      return jsonResponse({});
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LabelPreviewPage", () => {
  it("shows a human-readable code alongside the QR", async () => {
    stubFetch();
    render(withQueryClient(<LabelPreviewPage />));

    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());
    expect(screen.getByText("Production Cultivation Plate")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeInTheDocument();
  });

  it("reprinting reuses the same QR identity -- generate is called at most once per entity", async () => {
    const calls = stubFetch();
    render(withQueryClient(<LabelPreviewPage />));
    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /print label/i }));
    await waitFor(() => expect(screen.getByText(/print recorded/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /print label/i }));
    await waitFor(() => expect(screen.getByText(/reprint recorded/i)).toBeInTheDocument());

    const generateCalls = calls.filter((c) => c.url.includes("/qr/carrier/carrier-1/generate"));
    expect(generateCalls.length).toBe(1);
    const printCalls = calls.filter((c) => c.url.includes("/qr/tok-abc/print"));
    expect(printCalls.length).toBe(2);
  });
});
