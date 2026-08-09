import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CropBatchRead } from "@/lib/api/client";

import { ResponsiveBatchList } from "./ResponsiveBatchList";

function makeBatch(overrides: Partial<CropBatchRead> = {}): CropBatchRead {
  return {
    id: "batch-1",
    tenant_id: "tenant-1",
    farm_id: "farm-1",
    code: "BATCH-001",
    workflow: { id: "wf-1", code: "WF", name: "Leafy Greens" },
    workflow_version_id: "wfv-1",
    version_number: 1,
    crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
    variety: { id: "var-1", code: "ICE", name: "Iceberg" },
    production_system: { id: "ps-1", code: "PS", name: "NFT" },
    state: "active",
    current_stage: { id: "stage-1", code: "GROW", name: "Growing", is_terminal: false },
    created_effective_time: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    closed_effective_time: null,
    superseded_effective_time: null,
    superseded_by_batch_derivation_event_id: null,
    created_by_batch_derivation_event_id: null,
    ...overrides,
  };
}

describe("ResponsiveBatchList", () => {
  it("renders a link to each batch's detail page with its code", () => {
    const batches = [makeBatch({ id: "b1", code: "BATCH-001" }), makeBatch({ id: "b2", code: "BATCH-002" })];
    render(<ResponsiveBatchList batches={batches} farmId="farm-1" />);

    const links = screen.getAllByRole("link", { name: /BATCH-00/ });
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(links.some((l) => l.getAttribute("href") === "/farms/farm-1/crop-batches/b1")).toBe(true);
  });

  it("shows crop and variety for each batch", () => {
    render(<ResponsiveBatchList batches={[makeBatch()]} farmId="farm-1" />);
    expect(screen.getAllByText(/Lettuce/).length).toBeGreaterThan(0);
  });
});
