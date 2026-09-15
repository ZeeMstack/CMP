import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import ScanEntryPage from "./page";

afterEach(() => {
  pushMock.mockClear();
});

function submit(value: string) {
  fireEvent.change(screen.getByLabelText(/qr token or scan link/i), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: /open/i }));
}

describe("ScanEntryPage (PILOT-SCAN-001E manual scan fallback)", () => {
  it("routes a raw token to the existing /q/[token] resolver", () => {
    render(<ScanEntryPage />);
    submit("tok-abc123");
    expect(pushMock).toHaveBeenCalledWith("/q/tok-abc123");
  });

  it("routes a full valid GrowCMP scan URL to the same /q/[token] resolver", () => {
    render(<ScanEntryPage />);
    submit("https://growcmp.com/q/tok-abc123");
    expect(pushMock).toHaveBeenCalledWith("/q/tok-abc123");
  });

  it("rejects blank input and never navigates", () => {
    render(<ScanEntryPage />);
    submit("   ");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("rejects a well-formed URL that isn't a scan link and never navigates anywhere, let alone externally", () => {
    render(<ScanEntryPage />);
    submit("https://evil.example.com/not-a-scan-link");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("never pushes anything but an internal /q/<token> destination", () => {
    render(<ScanEntryPage />);
    submit("tok-xyz");
    for (const call of pushMock.mock.calls) {
      expect(String(call[0])).toMatch(/^\/q\//);
    }
  });
});
