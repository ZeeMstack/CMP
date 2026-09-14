import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Renders the exact `value` qrcode.react was asked to encode as plain
// text -- the most direct, implementation-stable way to prove what URL
// was actually handed to the QR renderer, without decoding SVG modules.
vi.mock("qrcode.react", () => ({
  QRCodeSVG: ({ value }: { value: string }) => <svg data-testid="qr-value">{value}</svg>,
}));

import { withQueryClient } from "@/lib/test-utils";

import { LabelPreviewClient } from "./LabelPreviewClient";

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

function renderPreview(canonicalAppOrigin: string | null = "https://growcmp.com") {
  return render(
    withQueryClient(
      <LabelPreviewClient farmId="farm-1" entityType="carrier" entityId="carrier-1" canonicalAppOrigin={canonicalAppOrigin} />,
    ),
  );
}

describe("LabelPreviewClient", () => {
  it("shows a human-readable code alongside the QR", async () => {
    stubFetch();
    renderPreview();

    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());
    expect(screen.getByText("Production Cultivation Plate")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeInTheDocument();
  });

  it("reprinting reuses the same QR identity -- generate is called at most once per entity", async () => {
    const calls = stubFetch();
    renderPreview();
    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /print label/i }));
    await waitFor(() => expect(screen.getByText(/print requested/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /print label/i }));
    await waitFor(() => expect(screen.getByText(/reprint requested/i)).toBeInTheDocument());

    const generateCalls = calls.filter((c) => c.url.includes("/qr/carrier/carrier-1/generate"));
    expect(generateCalls.length).toBe(1);
    const printCalls = calls.filter((c) => c.url.includes("/qr/tok-abc/print"));
    expect(printCalls.length).toBe(2);
  });

  it("the print-recorded message never claims the physical label was actually produced", async () => {
    stubFetch();
    renderPreview();
    await waitFor(() => expect(screen.getByText("PP-0147")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /print label/i }));
    await waitFor(() => expect(screen.getByText(/print requested/i)).toBeInTheDocument());
    expect(screen.queryByText(/print recorded/i)).not.toBeInTheDocument();
  });

  it("PILOT-SCAN-001 FINAL SECURITY CLOSURE: refuses to render a QR when no canonical origin is configured, rather than falling back to the browser's own origin", async () => {
    stubFetch();
    renderPreview(null);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/APP_BASE_URL/)).toBeInTheDocument();
    expect(screen.queryByTestId("qr-value")).not.toBeInTheDocument();
  });

  it("PILOT-SCAN-001 FINAL SECURITY CLOSURE: the printed QR is built from the configured canonical origin, never window.location.origin", async () => {
    // jsdom's default window origin is http://localhost:3000 -- prove the
    // rendered QR ignores it entirely when a different canonical origin is
    // configured (as production, with APP_BASE_URL=https://growcmp.com,
    // always would be).
    expect(window.location.origin).toBe("http://localhost:3000");

    stubFetch();
    renderPreview("https://growcmp.com");

    await waitFor(() => expect(screen.getByTestId("qr-value")).toBeInTheDocument());
    const encoded = screen.getByTestId("qr-value").textContent ?? "";
    expect(encoded).toBe("https://growcmp.com/q/tok-abc");
    expect(encoded).not.toContain("localhost");
  });
});
