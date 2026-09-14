import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildPrintLabelsUrl,
  openLabelPrintWindow,
  parsePrintLabelsFromSearchParams,
  type PrintableLabel,
} from "./printableLabel";

const labels: PrintableLabel[] = [
  { token: "tok-1", size: "standard", entityTypeLabel: "Batch", code: "B-2026-014", lines: [] },
  { token: "tok-2", size: "small", entityTypeLabel: "Carrier", code: "PP-0147", lines: ["Batch B-2026-014"] },
];

afterEach(() => {
  vi.restoreAllMocks();
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
});
