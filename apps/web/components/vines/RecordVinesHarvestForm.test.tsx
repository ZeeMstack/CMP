import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VinesHarvestableSourceRead } from "@/lib/api/client";

import { RecordVinesHarvestForm } from "./RecordVinesHarvestForm";

const SOURCE: VinesHarvestableSourceRead = {
  batch_id: "batch-1",
  batch_code: "VN-2026-001",
  crop_common_name: "Cherry Tomato",
  variety_name: null,
  greenhouse_id: "gh-1",
  greenhouse_code: "VIN-01",
  gutter_id: "gutter-1",
  gutter_code: "GUT-0001",
  living_plant_count: 40,
  last_harvest_effective_time: null,
  quality_hold_open: false,
};

function fillLineAndGoToReview() {
  fireEvent.change(screen.getByLabelText(/raw weight \(kg\)/i), { target: { value: "3.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Review harvest" }));
}

// HOTFIX-TIME-002: "Record harvest" must never depend on the browser clock --
// the default path omits effective_time entirely, mirroring
// `LeafyHarvestForm.test.tsx`'s and the original Sowing hotfix's own
// established design.
describe("RecordVinesHarvestForm HOTFIX-TIME-002: server-authoritative harvest time", () => {
  it("default mode never shows an uncommitted browser timestamp as though it is already authoritative -- shows Now instead", async () => {
    render(
      <RecordVinesHarvestForm
        sources={[SOURCE]}
        onRemoveSource={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );
    fillLineAndGoToReview();

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText(/VN-2026-001/).parentElement).toHaveTextContent("Now");
  });

  it("default 'Record harvest' submits with no client-generated effective_time at all", async () => {
    const onSubmit = vi.fn();
    render(
      <RecordVinesHarvestForm
        sources={[SOURCE]}
        onRemoveSource={vi.fn()}
        onSubmit={onSubmit}
        isSubmitting={false}
      />,
    );
    fillLineAndGoToReview();
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].effective_time).toBeNull();
  });

  it("an operator who explicitly opts into a custom time sees and submits that exact selected timestamp, never Now", async () => {
    const onSubmit = vi.fn();
    render(
      <RecordVinesHarvestForm
        sources={[SOURCE]}
        onRemoveSource={vi.fn()}
        onSubmit={onSubmit}
        isSubmitting={false}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /use a specific date\/time instead of now/i }));
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-01-15" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:30" } });
    fillLineAndGoToReview();

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText(/VN-2026-001/).parentElement).toHaveTextContent("2026-01-15 09:30");
    expect(screen.getByText(/VN-2026-001/).parentElement).not.toHaveTextContent("Now");

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].effective_time).toBe(new Date("2026-01-15T09:30").toISOString());
  });

  it("does not require a Date/Time entry at all when in default Now mode", () => {
    render(
      <RecordVinesHarvestForm
        sources={[SOURCE]}
        onRemoveSource={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );
    fillLineAndGoToReview();
    // Reaching Review at all (with no date/time ever touched) proves the
    // schema's date/time requirement is conditional on use_custom_time.
    expect(screen.queryByText("Date is required")).not.toBeInTheDocument();
    expect(screen.queryByText("Time is required")).not.toBeInTheDocument();
  });
});
