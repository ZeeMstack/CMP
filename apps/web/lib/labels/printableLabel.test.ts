import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildPrintLabelsUrl,
  openLabelPrintWindow,
  parsePrintLabelsFromSearchParams,
  requestPrintAudit,
  type PrintableLabel,
} from "./printableLabel";

const labels: PrintableLabel[] = [
  { token: "tok-1", size: "standard", entityType: "crop_batch", entityTypeLabel: "Batch", code: "B-2026-014", lines: [] },
  {
    token: "tok-2",
    size: "small",
    entityType: "batch_carrier_assignment",
    entityTypeLabel: "Placement",
    code: "PP-0147",
    lines: ["Batch B-2026-014"],
  },
];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("printableLabel (PILOT-SCAN-001B serializable print payload)", () => {
  it("round-trips a list of labels through the URL query param", () => {
    const url = buildPrintLabelsUrl(labels);
    const searchParams = new URLSearchParams(url.split("?")[1]);
    const parsed = parsePrintLabelsFromSearchParams(searchParams);
    expect(parsed).toEqual(labels);
  });

  it("never carries a raw UUID or location/stage fact in the QR-relevant fields -- token stays opaque", () => {
    const url = buildPrintLabelsUrl(labels);
    // The token itself is the only thing the QR encodes (see QrCodeSvg) --
    // it must be a plain opaque string, never a recognizable UUID pattern
    // that could leak entity identity from the printed code alone.
    expect(labels.every((l) => !/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(l.token))).toBe(true);
    expect(url).toContain("tok-1");
  });

  it("parses safely, dropping malformed/non-array/missing-field input rather than throwing", () => {
    expect(parsePrintLabelsFromSearchParams(new URLSearchParams())).toEqual([]);
    expect(parsePrintLabelsFromSearchParams(new URLSearchParams("items=not-json"))).toEqual([]);
    expect(parsePrintLabelsFromSearchParams(new URLSearchParams(`items=${encodeURIComponent(JSON.stringify({ a: 1 }))}`))).toEqual(
      [],
    );
    expect(
      parsePrintLabelsFromSearchParams(new URLSearchParams(`items=${encodeURIComponent(JSON.stringify([{ token: "t" }]))}`)),
    ).toEqual([]);
  });

  it("opens the print document synchronously (same call stack) so popup blockers never intervene", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    openLabelPrintWindow(labels);
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("/print/labels?items="), "_blank", "noopener,noreferrer");
  });

  it("does nothing for an empty label list -- never opens a blank print window", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    openLabelPrintWindow([]);
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("requestPrintAudit fires one POST /qr/{token}/print per label -- N labels produce N print-request audits", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/print")) {
          calls.push(url);
          return jsonResponse({ qr_identifier_id: "qr-x", requested_at: "2026-01-01T00:00:00Z", is_reprint: false });
        }
        return jsonResponse({});
      }),
    );

    requestPrintAudit(labels);
    await vi.waitFor(() => expect(calls).toHaveLength(2));

    expect(calls.some((u) => u.includes("/qr/tok-1/print"))).toBe(true);
    expect(calls.some((u) => u.includes("/qr/tok-2/print"))).toBe(true);
  });

  it("requestPrintAudit sends the entity-type-derived template and no reason (these are always first prints)", async () => {
    let capturedBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/qr/tok-2/print")) {
          capturedBody = JSON.parse(String(init.body));
          return jsonResponse({ qr_identifier_id: "qr-x", requested_at: "2026-01-01T00:00:00Z", is_reprint: false });
        }
        return jsonResponse({});
      }),
    );

    requestPrintAudit([labels[1]]);
    await vi.waitFor(() => expect(capturedBody).not.toBeNull());

    expect(capturedBody).toMatchObject({ template: "batch_carrier_assignment_small", reason: null });
  });

  it("a failed print-request audit call is swallowed -- never thrown, never surfaced to the caller", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
    expect(() => requestPrintAudit(labels)).not.toThrow();
  });
});
