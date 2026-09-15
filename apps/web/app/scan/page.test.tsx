import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { writeWorkingLocation } from "@/lib/scan/workingLocation";

import ScanEntryPage from "./page";

afterEach(() => {
  pushMock.mockClear();
  window.localStorage.clear();
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

  it("routes a full valid GrowCMP production scan URL to the same /q/[token] resolver", () => {
    render(<ScanEntryPage />);
    submit("https://growcmp.com/q/tok-abc123");
    expect(pushMock).toHaveBeenCalledWith("/q/tok-abc123");
  });

  it("routes a scan URL on the current application origin (dev/test) to the same /q/[token] resolver", () => {
    expect(window.location.origin).toBe("http://localhost:3000");
    render(<ScanEntryPage />);
    submit("http://localhost:3000/q/tok-abc123");
    expect(pushMock).toHaveBeenCalledWith("/q/tok-abc123");
  });

  it("rejects a third-party absolute URL even though its path is exactly /q/<token>, and never navigates", () => {
    render(<ScanEntryPage />);
    submit("https://evil.example/q/tok-abc123");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
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

describe("ScanEntryPage PILOT-SCAN-001F: working-location display", () => {
  it("shows the active working location when one is set, with no separate comparison logic", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    render(<ScanEntryPage />);

    expect(await screen.findByText("Working location")).toBeInTheDocument();
    expect(screen.getByText("GH-01 / Table 07")).toBeInTheDocument();
  });

  it("shows nothing extra when no working location is active", () => {
    render(<ScanEntryPage />);
    expect(screen.queryByText("Working location")).not.toBeInTheDocument();
  });

  it("Clear removes the working location from this page too", async () => {
    writeWorkingLocation({ locationId: "table-07", farmId: "farm-1", code: "T07", pathString: "GH-01 / Table 07" });
    render(<ScanEntryPage />);

    await screen.findByText("Working location");
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(screen.queryByText("Working location")).not.toBeInTheDocument();
  });
});
