import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => searchParams,
}));

import type { SowingEventRead } from "@/lib/api/client";
import { withQueryClient } from "@/lib/test-utils";

import NewSowingPage, { SowingReceipt } from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NewSowingPage", () => {
  it("shows the Nursery journey indicator with Seeding as the current stage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<NewSowingPage />));

    await waitFor(() => expect(screen.getByRole("navigation", { name: "Nursery journey" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Seeding/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("heading", { name: "New Sowing" })).toBeInTheDocument();
  });
});

const SOWING_RESULT: SowingEventRead = {
  id: "sow-1",
  tenant_id: "tenant-1",
  farm_id: "farm-1",
  batch_id: "batch-1",
  batch_code: "CB-0001",
  workflow_version_id: "wv-1",
  stage: { id: "stage-1", code: "seeding", name: "Seeding" },
  effective_time: "2026-08-20T09:00:00Z",
  recorded_time: "2026-08-20T09:00:00Z",
  actor_user_id: "user-1",
  client_command_id: "cmd-1",
  note: null,
  seeding_station: null,
  seeding_machine: null,
  seeding_program_line_id: null,
  total_seeds_sown: 400,
  lines: [
    {
      id: "line-1",
      batch_carrier_assignment_id: "bca-1",
      carrier: { id: "tray-1", code: "ST-0001", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
      seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: null },
      sown_site_count: 200,
      seed_count: 200,
      line_note: null,
    },
    {
      id: "line-2",
      batch_carrier_assignment_id: "bca-2",
      carrier: { id: "tray-2", code: "ST-0002", carrier_type: { id: "ct-1", code: "seed_tray", name: "Seed Tray" } },
      seed_lot: { id: "lot-1", code: "LOT-01", supplier_lot_reference: null, crop: { id: "c1", code: "ICE", common_name: "Iceberg" }, variety: null },
      sown_site_count: 200,
      seed_count: 200,
      line_note: null,
    },
  ],
} as unknown as SowingEventRead;

describe("SowingReceipt (PILOT-SCAN-001B Print Batch Label + Print Tray Labels)", () => {
  it("prepares a Batch Master Label and one Tray label per sown tray, prints each on its own click, and records one print-request audit PER label (never one page-level event)", async () => {
    const printRequestCalls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST" && url.includes("/qr/crop_batch/batch-1/generate")) {
          return jsonResponse({ id: "qr-batch-1", entity_type: "crop_batch", token: "tok-batch-1", created_at: "2026-01-01T00:00:00Z" });
        }
        if (init?.method === "POST" && url.includes("/qr/batch_carrier_assignment/bca-1/generate")) {
          return jsonResponse({ id: "qr-tray-1", entity_type: "batch_carrier_assignment", token: "tok-tray-1", created_at: "2026-01-01T00:00:00Z" });
        }
        if (init?.method === "POST" && url.includes("/qr/batch_carrier_assignment/bca-2/generate")) {
          return jsonResponse({ id: "qr-tray-2", entity_type: "batch_carrier_assignment", token: "tok-tray-2", created_at: "2026-01-01T00:00:00Z" });
        }
        if (init?.method === "POST" && url.includes("/print")) {
          printRequestCalls.push(url);
          return jsonResponse({ qr_identifier_id: "qr-x", requested_at: "2026-01-01T00:00:00Z", is_reprint: false });
        }
        return jsonResponse({});
      }),
    );
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(withQueryClient(<SowingReceipt farmId="farm-1" result={SOWING_RESULT} />));

    expect(
      screen.getByText((_, node) => node?.tagName === "P" && node.textContent === "Sowing recorded for Batch CB-0001 -- 400 seeds across 2 trays."),
    ).toBeInTheDocument();

    const batchButton = await screen.findByRole("button", { name: "Print Batch Label" });
    fireEvent.click(batchButton);
    const trayButton = await screen.findByRole("button", { name: "Print Tray Labels (2)" });
    fireEvent.click(trayButton);

    expect(openSpy).toHaveBeenCalledTimes(2);

    function itemsFrom(callIndex: number) {
      const [url] = openSpy.mock.calls[callIndex];
      const encoded = new URL(String(url), "http://localhost").searchParams.get("items") ?? "[]";
      return JSON.parse(encoded) as Array<{ token: string; code: string; entityTypeLabel: string }>;
    }

    const batchItems = itemsFrom(0);
    expect(batchItems).toHaveLength(1);
    expect(batchItems[0]).toMatchObject({ token: "tok-batch-1", code: "CB-0001", entityTypeLabel: "Batch" });

    const trayItems = itemsFrom(1);
    expect(trayItems).toHaveLength(2);
    expect(trayItems.map((i) => i.token).sort()).toEqual(["tok-tray-1", "tok-tray-2"]);
    expect(trayItems.map((i) => i.code).sort()).toEqual(["ST-0001", "ST-0002"]);

    // PILOT-SCAN-001B FINAL CLOSURE: one "Print Batch Label" click (1
    // label) + one "Print Tray Labels (2)" click (2 labels) = 3
    // independent, entity-specific qr_label_print_requested audit calls --
    // never one generic page-level audit event.
    await vi.waitFor(() => expect(printRequestCalls).toHaveLength(3));
    expect(printRequestCalls.some((u) => u.includes("/qr/tok-batch-1/print"))).toBe(true);
    expect(printRequestCalls.some((u) => u.includes("/qr/tok-tray-1/print"))).toBe(true);
    expect(printRequestCalls.some((u) => u.includes("/qr/tok-tray-2/print"))).toBe(true);
  });

  it("a print-token failure never affects the already-successful Sowing -- the receipt stays shown, only labels are unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
    render(withQueryClient(<SowingReceipt farmId="farm-1" result={SOWING_RESULT} />));

    const receiptText = () =>
      screen.getByText((_, node) => node?.tagName === "P" && node.textContent === "Sowing recorded for Batch CB-0001 -- 400 seeds across 2 trays.");
    expect(receiptText()).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Labels could not be prepared\. The sowing itself was recorded successfully\./)).toBeInTheDocument(),
    );
    expect(receiptText()).toBeInTheDocument();
  });
});
