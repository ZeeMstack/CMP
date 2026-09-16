import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { HarvestablePlateRead } from "@/lib/api/client";

import { LeafyHarvestForm } from "./LeafyHarvestForm";

const PLATE: HarvestablePlateRead = {
  production_plate_id: "plate-1",
  production_plate_code: "PCP-0001",
  batch_id: "batch-1",
  batch_code: "LG-2026-001",
  crop_common_name: "Iceberg Lettuce",
  variety_name: "Mamutik",
  current_living_heads: 200,
  current_batch_carrier_assignment_id: "bca-1",
  location: null,
  has_location_warning: false,
  quality_hold_open: false,
};

function fillLineAndGoToReview() {
  fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "50" } });
  fireEvent.blur(screen.getByLabelText(/heads harvested/i));
  fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
}

// HOTFIX-TIME-002: "Record Harvest" must never depend on the browser clock --
// the default path omits effective_time entirely, mirroring the Sowing
// hotfix's own established design (SowingForm.test.tsx).
describe("LeafyHarvestForm HOTFIX-TIME-002: server-authoritative harvest time", () => {
  it("default mode never shows an uncommitted browser timestamp as though it is already authoritative -- shows Now instead", async () => {
    render(
      <LeafyHarvestForm
        plates={[PLATE]}
        onRemovePlate={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );
    fillLineAndGoToReview();

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText(/LG-2026-001/).parentElement).toHaveTextContent("Now");
  });

  it("default 'Record Harvest' submits with no client-generated effective_time at all", async () => {
    const onSubmit = vi.fn();
    render(
      <LeafyHarvestForm
        plates={[PLATE]}
        onRemovePlate={vi.fn()}
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
      <LeafyHarvestForm
        plates={[PLATE]}
        onRemovePlate={vi.fn()}
        onSubmit={onSubmit}
        isSubmitting={false}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /use a specific date\/time instead of now/i }));
    fireEvent.change(screen.getByLabelText(/^date$/i), { target: { value: "2026-01-15" } });
    fireEvent.change(screen.getByLabelText(/^time$/i), { target: { value: "09:30" } });
    fillLineAndGoToReview();

    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText(/LG-2026-001/).parentElement).toHaveTextContent("2026-01-15 09:30");
    expect(screen.getByText(/LG-2026-001/).parentElement).not.toHaveTextContent("Now");

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].effective_time).toBe(new Date("2026-01-15T09:30").toISOString());
  });

  it("does not require a Date/Time entry at all when in default Now mode", () => {
    render(
      <LeafyHarvestForm
        plates={[PLATE]}
        onRemovePlate={vi.fn()}
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
