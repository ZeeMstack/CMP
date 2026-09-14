import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Same pattern as the generic label preview route's own test: assert what
// value qrcode.react was actually asked to encode, without decoding SVG.
vi.mock("qrcode.react", () => ({
  QRCodeSVG: ({ value }: { value: string }) => <svg data-testid="qr-value">{value}</svg>,
}));

let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
}));

import { buildPrintLabelsUrl, type PrintableLabel } from "@/lib/labels/printableLabel";

import { PrintLabelsClient } from "./PrintLabelsClient";

function setItems(labels: PrintableLabel[]) {
  const url = buildPrintLabelsUrl(labels);
  searchParams = new URLSearchParams(url.split("?")[1]);
}

afterEach(() => {
  vi.restoreAllMocks();
  searchParams = new URLSearchParams();
});

const trayLabel: PrintableLabel = {
  token: "tok-tray-1",
  size: "standard",
  entityType: "batch_carrier_assignment",
  entityTypeLabel: "Seed Tray",
  code: "TR-001",
  lines: ["Batch B-2026-014", "Germination"],
};
const batchLabel: PrintableLabel = {
  token: "tok-batch-1",
  size: "standard",
  entityType: "crop_batch",
  entityTypeLabel: "Batch",
  code: "B-2026-014",
  lines: [],
};

describe("PrintLabelsClient (PILOT-SCAN-001B label-only print document)", () => {
  it("renders only the label content -- no nav, breadcrumbs, or page chrome", () => {
    setItems([trayLabel]);
    render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    expect(screen.getByText("TR-001")).toBeInTheDocument();
    // No navigation/breadcrumb/app-shell landmarks -- this document has none.
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders one label per item for a multi-label print job, in one document", () => {
    const trays = Array.from({ length: 4 }, (_, i) => ({ ...trayLabel, token: `tok-${i}`, code: `TR-00${i}` }));
    setItems(trays);
    render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    for (const t of trays) {
      expect(screen.getByText(t.code)).toBeInTheDocument();
    }
  });

  it("triggers the browser print dialog exactly once after the labels are rendered", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    setItems([batchLabel, trayLabel]);
    render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    await waitFor(() => expect(printSpy).toHaveBeenCalledTimes(1));
  });

  it("mixed STANDARD and SMALL labels each get their own physical page size (named @page rules)", () => {
    setItems([
      batchLabel,
      { token: "tok-carrier-1", size: "small", entityType: "carrier", entityTypeLabel: "Carrier", code: "PP-0147", lines: [] },
    ]);
    const { container } = render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    expect(container.querySelector(".print-label-item.size-standard")).toBeInTheDocument();
    expect(container.querySelector(".print-label-item.size-small")).toBeInTheDocument();
    expect(container.innerHTML).toContain("@page label-standard");
    expect(container.innerHTML).toContain("@page label-small");
  });

  it("the encoded QR payload is the canonical origin + opaque token only -- never location/stage/quantity", () => {
    setItems([trayLabel]);
    render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    const encoded = screen.getByTestId("qr-value").textContent ?? "";
    expect(encoded).toBe("https://growcmp.com/q/tok-tray-1");
    expect(encoded).not.toContain("Germination");
    expect(encoded).not.toContain("B-2026-014");
  });

  it("refuses to render a QR when no canonical origin is configured", () => {
    setItems([trayLabel]);
    render(<PrintLabelsClient canonicalAppOrigin={null} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("qr-value")).not.toBeInTheDocument();
  });

  it("shows an error rather than a blank page when no labels were provided", () => {
    searchParams = new URLSearchParams();
    render(<PrintLabelsClient canonicalAppOrigin="https://growcmp.com" />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
