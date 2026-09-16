import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BatchOperationalContext, ObservationDefinitionRead } from "@/lib/api/client";

import { RecordObservationForm } from "./RecordObservationForm";

const BATCH: BatchOperationalContext = {
  id: "batch-1", code: "LET-001", crop: { id: "crop-1", code: "LET", common_name: "Iceberg" },
  variety: { id: "var-1", code: "MAM", name: "Mamutik" }, state: "active",
  current_stage: { id: "stage-1", code: "PROD", name: "Production", is_terminal: false, stage_category: "production" },
  sowing_origins: [], sown_effective_time: "2026-08-01T00:00:00Z",
  placement: {
    active_carrier_count: 1, placed_carrier_count: 1, unplaced_carrier_count: 0,
    placements: [], common_ancestor_path: null,
  },
  open_quality_hold_count: 0,
};

const DEFINITIONS: ObservationDefinitionRead[] = [
  {
    id: "def-height", tenant_id: "t-1", code: "PLANT-HEIGHT", name: "Plant Height", description: null,
    value_type: "decimal", unit: "cm", target_scope: "crop_batch", min_value: null, max_value: null,
    status: "active", created_by_user_id: "u-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
];

function renderForm(onSubmit = vi.fn()) {
  const utils = render(
    <RecordObservationForm
      batch={BATCH}
      definitions={DEFINITIONS}
      definitionsLoading={false}
      targets={[]}
      targetsLoading={false}
      onSubmit={onSubmit}
      onCancel={vi.fn()}
      isSubmitting={false}
    />,
  );
  return { onSubmit, container: utils.container };
}

// HOTFIX-TIME-002: "Record observation" must never depend on the browser
// clock -- the default path omits effective_time entirely, mirroring
// `LeafyHarvestForm.test.tsx`'s and the original Sowing hotfix's own
// established design.
describe("RecordObservationForm HOTFIX-TIME-002: server-authoritative observation time", () => {
  it("default mode never shows an uncommitted browser timestamp as though it is already authoritative -- shows Now instead", () => {
    renderForm();
    const occurredAt = screen.getByText(
      (_, element) => element?.tagName.toLowerCase() === "p" && Boolean(element.textContent?.startsWith("Occurred at")),
    );
    expect(occurredAt).toHaveTextContent("Now");
  });

  it("default 'Record observation' submits with no client-generated effective_time at all", () => {
    const { onSubmit } = renderForm();
    fireEvent.change(screen.getByLabelText(/plant height/i), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: /record 1 observation/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].effective_time).toBeNull();
  });

  it("an operator who explicitly opts into a custom time submits that exact selected timestamp, never Now", () => {
    const { onSubmit, container } = renderForm();
    fireEvent.click(screen.getByRole("checkbox", { name: /use a specific date\/time instead of now/i }));
    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
    const timeInput = container.querySelector('input[type="time"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-01-15" } });
    fireEvent.change(timeInput, { target: { value: "09:30" } });

    const occurredAt = screen.queryByText(
      (_, element) => element?.tagName.toLowerCase() === "p" && Boolean(element.textContent?.startsWith("Occurred at")),
    );
    expect(occurredAt).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/plant height/i), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: /record 1 observation/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].effective_time).toBe(new Date("2026-01-15T09:30").toISOString());
  });
});
