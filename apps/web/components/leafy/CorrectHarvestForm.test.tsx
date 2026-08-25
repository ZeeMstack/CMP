import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LeafyHarvestSourceLineRead } from "@/lib/api/client";

import { CorrectHarvestForm, signed } from "./CorrectHarvestForm";

function sourceLine(overrides: Partial<LeafyHarvestSourceLineRead> = {}): LeafyHarvestSourceLineRead {
  return {
    id: "line-1", batch_carrier_assignment_id: "bca-1",
    carrier: { id: "carrier-1", code: "PP-001", carrier_type: { id: "ct-1", code: "production_cultivation_plate", name: "Production Plate" } },
    harvest_location: null,
    original_harvested_weight_kg: "2.5", original_whole_unit_count: 5,
    current_harvested_weight_kg: "2.5", current_whole_unit_count: 5, state: "ACTIVE",
    correction_tip_id: null, correction_history: [],
    ...overrides,
  } as LeafyHarvestSourceLineRead;
}

function fillReasonAndNote() {
  fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
  fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Recount" } });
}

function goToReview() {
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
}

/** HARVEST-OPS-001 BROWSER QA CORRECTION -- DEFECT 1: the Correction
 * Review panel's biological-population wording must be direction-aware
 * from HEAD COUNT alone (never weight), covering consume/restore/no-change
 * for ordinary corrections, VOID, and weight-only corrections. */
describe("CorrectHarvestForm biological population wording", () => {
  it("current 5 -> corrected 4: restores 1 plant", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "2.500" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.000" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will restore 1 Production plant on the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });

  it("current 4 -> corrected 6: consumes 2 additional plants", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 4, current_harvested_weight_kg: "2.000" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "3.000" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will consume 2 additional Production plants from the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });

  it("current 0 (already void) -> corrected 3: consumes 3 additional plants", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 0, current_harvested_weight_kg: "0", state: "VOID" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "1.500" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will consume 3 additional Production plants from the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });

  it("current 6 -> VOID: restores 6 plants (singular/plural, and the pre-Review VOID hint agrees)", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 6, current_harvested_weight_kg: "3.000" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.click(screen.getByLabelText(/void harvest contribution/i));
    // The pre-Review static hint must already agree with the eventual Review wording.
    await waitFor(() =>
      expect(
        screen.getByText(/This correction will restore 6 Production plants on the source Plate\./),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Wrong Plate" } });
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will restore 6 Production plants on the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });

  it("current 1 -> VOID: singular wording (\"1 Production plant\", not \"plants\")", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 1, current_harvested_weight_kg: "0.500" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.click(screen.getByLabelText(/void harvest contribution/i));
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "miscounted" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Wrong Plate" } });
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will restore 1 Production plant on the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });

  it("same heads, changed weight only: no biological population change", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "2.500" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    // Heads left at the current effective value (5); only weight changes.
    // 3.000 - 2.500 = 0.5 exactly (IEEE-754 exact), so the weight-delta
    // assertion below isn't sensitive to unrelated floating-point display
    // rounding -- this test is only about the biology sentence.
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "3.000" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction does not change Production population. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
    // Never determined from weight -- the commercial adjustment shows the
    // weight delta, but the biology sentence must still say "no change".
    expect(screen.getByText(/Net commercial adjustment: 0 heads · \+0\.5 kg/)).toBeInTheDocument();
  });

  it("repeated correction: a second correction (current 4 -> corrected 6) still reports its own delta, not against the original", async () => {
    // Simulates the SECOND correction in a chain: `current_*` already
    // reflects the first correction's own effective tuple (predecessor),
    // never the line's original values.
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({
          current_whole_unit_count: 4, current_harvested_weight_kg: "2.000",
          original_whole_unit_count: 5, original_harvested_weight_kg: "2.500",
          correction_tip_id: "corr-1",
        })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "3.000" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() =>
      expect(
        screen.getByText("This correction will consume 2 additional Production plants from the source Plate. The physical Plate itself does not move."),
      ).toBeInTheDocument(),
    );
  });
});

/** HARVEST-OPS-001 FINAL BROWSER QA POLISH: the "Net commercial adjustment"
 * weight delta must never render a raw IEEE-754 float artifact (e.g.
 * `+0.7000000000000002 kg`) -- display rounded to this UI's own 3-decimal
 * weight precision, trailing zeros stripped, no bare `-0 kg`. The
 * underlying correction payload/arithmetic is untouched by this -- these
 * tests assert only what's rendered in the Review panel. */
describe("CorrectHarvestForm weight-delta display formatting", () => {
  it("1.2 - 0.5 displays +0.7 kg, never a floating-point artifact", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "0.500" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "1.2" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() => expect(screen.getByText(/Net commercial adjustment: 0 heads · \+0\.7 kg/)).toBeInTheDocument());
    expect(screen.queryByText(/0\.7000000000000002/)).not.toBeInTheDocument();
  });

  it("0.5 - 1.2 displays -0.7 kg", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "1.2" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "0.5" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() => expect(screen.getByText(/Net commercial adjustment: 0 heads · -0\.7 kg/)).toBeInTheDocument());
  });

  it("equal weights displays 0 kg when heads differ", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "2.500" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "2.500" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() => expect(screen.getByText(/Net commercial adjustment: -1 heads · 0 kg/)).toBeInTheDocument());
    expect(screen.queryByText(/[+-]0 kg/)).not.toBeInTheDocument();
  });

  it("a 3-decimal result such as 1.234 remains 1.234 kg, no extra/trailing digits", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "2.000" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "3.234" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() => expect(screen.getByText(/Net commercial adjustment: 0 heads · \+1\.234 kg/)).toBeInTheDocument());
  });

  it("never displays a negative zero (component-level: unchanged weight, heads differ so it's not a no-op)", async () => {
    render(
      <CorrectHarvestForm
        sourceLine={sourceLine({ current_whole_unit_count: 5, current_harvested_weight_kg: "1.100" })}
        onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
      />,
    );
    fireEvent.change(screen.getByLabelText(/heads harvested/i), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/raw harvested weight/i), { target: { value: "1.1" } });
    fillReasonAndNote();
    goToReview();
    await waitFor(() => expect(screen.getByText(/Net commercial adjustment: -1 heads · 0 kg/)).toBeInTheDocument());
    expect(screen.queryByText(/-0 kg/)).not.toBeInTheDocument();
  });
});

/** Direct unit tests for the exported `signed` formatter -- covers the
 * genuine JS `-0` literal directly (a real bare `-0` is impractical to
 * force through two typed decimal form inputs, since equal-valued decimal
 * strings parse to the identical float and subtract to a plain `+0`),
 * plus a few more float-noise/precision cases at the function level. */
describe("signed", () => {
  it("collapses a true -0 to a bare zero, never '-0 kg'", () => {
    expect(signed(-0, " kg")).toBe("0 kg");
  });

  it("collapses float noise that rounds to -0 (e.g. -0.00004) to a bare zero", () => {
    expect(signed(-0.00004, " kg")).toBe("0 kg");
  });

  it("rounds 0.7000000000000002 to +0.7 kg", () => {
    expect(signed(0.7000000000000002, " kg")).toBe("+0.7 kg");
  });

  it("rounds -0.7000000000000002 to -0.7 kg", () => {
    expect(signed(-0.7000000000000002, " kg")).toBe("-0.7 kg");
  });

  it("keeps a genuine 3-decimal value intact (1.234)", () => {
    expect(signed(1.234, " kg")).toBe("+1.234 kg");
  });

  it("strips a whole-number trailing .000 (2.0 -> +2 kg)", () => {
    expect(signed(2.0, " kg")).toBe("+2 kg");
  });

  it("strips one trailing zero (1.250 -> +1.25 kg)", () => {
    expect(signed(1.25, " kg")).toBe("+1.25 kg");
  });

  it("exact zero displays 0 kg with no sign", () => {
    expect(signed(0, " kg")).toBe("0 kg");
  });

  it("still formats an ordinary integer heads delta correctly (unaffected by the weight fix)", () => {
    expect(signed(-4, " heads")).toBe("-4 heads");
    expect(signed(2, " heads")).toBe("+2 heads");
    expect(signed(0, " heads")).toBe("0 heads");
  });
});
