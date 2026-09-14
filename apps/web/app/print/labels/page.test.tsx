import { render, screen } from "@testing-library/react";
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

import PrintLabelsPage from "./page";

const label: PrintableLabel = {
  token: "tok-1",
  size: "standard",
  entityType: "crop_batch",
  entityTypeLabel: "Batch",
  code: "B-2026-014",
  lines: [],
};

function setItems(labels: PrintableLabel[]) {
  const url = buildPrintLabelsUrl(labels);
  searchParams = new URLSearchParams(url.split("?")[1]);
}

const ORIGINAL_APP_BASE_URL = process.env.APP_BASE_URL;

afterEach(() => {
  if (ORIGINAL_APP_BASE_URL === undefined) delete process.env.APP_BASE_URL;
  else process.env.APP_BASE_URL = ORIGINAL_APP_BASE_URL;
  searchParams = new URLSearchParams();
});

/** PILOT-SCAN-001C: `PrintLabelsPage` is the async Server Component
 * itself (not `PrintLabelsClient`, already covered by its own test with a
 * directly-supplied prop) -- these tests prove the Server Component
 * actually calls `resolveTrustedOrigin()` at render time and reads
 * whatever `APP_BASE_URL` is live in `process.env` at that moment, rather
 * than a value baked in earlier (e.g. at build time, the production
 * defect this ticket fixes by adding `export const dynamic =
 * "force-dynamic"` to page.tsx). */
describe("PrintLabelsPage (PILOT-SCAN-001C: canonical origin resolved at request time)", () => {
  it("with a configured APP_BASE_URL, resolves and passes the canonical origin through to the rendered QR", async () => {
    process.env.APP_BASE_URL = "https://growcmp.com";
    setItems([label]);

    const element = await PrintLabelsPage();
    render(element);

    const encoded = screen.getByTestId("qr-value").textContent ?? "";
    expect(encoded).toBe("https://growcmp.com/q/tok-1");
  });

  it("never falls back to the browser/jsdom origin, even though window.location.origin is localhost", async () => {
    // jsdom's default window origin -- prove the rendered QR ignores it
    // entirely when APP_BASE_URL is configured to something else, exactly
    // as production (browser host, Render host, or localhost may all
    // differ from the one canonical APP_BASE_URL).
    expect(window.location.origin).toBe("http://localhost:3000");
    process.env.APP_BASE_URL = "https://growcmp.com";
    setItems([label]);

    const element = await PrintLabelsPage();
    render(element);

    const encoded = screen.getByTestId("qr-value").textContent ?? "";
    expect(encoded).toBe("https://growcmp.com/q/tok-1");
    expect(encoded).not.toContain("localhost");
  });

  it("fails closed -- no QR rendered -- when APP_BASE_URL is missing", async () => {
    delete process.env.APP_BASE_URL;
    setItems([label]);

    const element = await PrintLabelsPage();
    render(element);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/APP_BASE_URL/)).toBeInTheDocument();
    expect(screen.queryByTestId("qr-value")).not.toBeInTheDocument();
  });

  it("fails closed -- no QR rendered -- when APP_BASE_URL is present but not a valid web URL", async () => {
    process.env.APP_BASE_URL = "not-a-url";
    setItems([label]);

    const element = await PrintLabelsPage();
    render(element);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("qr-value")).not.toBeInTheDocument();
  });
});
