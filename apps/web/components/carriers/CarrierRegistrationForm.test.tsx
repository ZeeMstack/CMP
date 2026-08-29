import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CarrierSpecificationRead } from "@/lib/api/client";

import { CarrierRegistrationForm } from "./CarrierRegistrationForm";

function spec(overrides: Partial<CarrierSpecificationRead> = {}): CarrierSpecificationRead {
  return {
    id: "spec-1",
    tenant_id: "t1",
    carrier_type_id: "ct-1",
    carrier_type_code: "nursery_cultivation_plate",
    biological_position_label: "Cells",
    code: "PLATE-200",
    name: "200-hole nursery plate",
    length_mm: 500,
    width_mm: 300,
    height_mm: null,
    biological_position_count: 200,
    status: "active",
    is_structurally_locked: false,
    ...overrides,
  };
}

const noop = () => {};

describe("CarrierRegistrationForm -- legacy cultivation_plate exclusion", () => {
  it("never renders a legacy generic cultivation_plate specification as a selectable option, even if the caller passes it in unfiltered", () => {
    // Deliberately does NOT pre-filter -- simulates a future caller (e.g. a
    // preselected/query-param specification id flow) that forgets to apply
    // the page-level filter. The form must enforce this on its own.
    const specifications = [
      spec({ id: "spec-legacy", code: "PLATE-LEGACY", carrier_type_code: "cultivation_plate" }),
      spec({ id: "spec-nursery", code: "PLATE-NURSERY", carrier_type_code: "nursery_cultivation_plate" }),
      spec({ id: "spec-production", code: "PLATE-PRODUCTION", carrier_type_code: "production_cultivation_plate" }),
    ];

    render(
      <CarrierRegistrationForm
        specifications={specifications}
        isSubmitting={false}
        onCancel={noop}
        onSubmitSingle={noop}
        onSubmitBulk={noop}
      />,
    );

    expect(screen.queryByRole("option", { name: /PLATE-LEGACY/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /PLATE-NURSERY/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /PLATE-PRODUCTION/ })).toBeInTheDocument();
  });

  it("never shows specification context for a legacy spec even if its id is force-selected", () => {
    const specifications = [spec({ id: "spec-legacy", code: "PLATE-LEGACY", carrier_type_code: "cultivation_plate" })];
    render(
      <CarrierRegistrationForm
        specifications={specifications}
        isSubmitting={false}
        onCancel={noop}
        onSubmitSingle={noop}
        onSubmitBulk={noop}
      />,
    );

    // There is no rendered <option> for the legacy spec, so a native
    // <select> cannot be driven to that value through the UI at all --
    // confirmed here by asserting the value change is simply a no-op.
    const select = screen.getByLabelText("Specification") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "spec-legacy" } });
    expect(select.value).not.toBe("spec-legacy");
    expect(screen.queryByText("PLATE-LEGACY")).not.toBeInTheDocument();
  });

  it("still allows nursery and production cultivation plates through unchanged", () => {
    const specifications = [
      spec({ id: "spec-nursery", code: "PLATE-NURSERY", carrier_type_code: "nursery_cultivation_plate" }),
    ];
    render(
      <CarrierRegistrationForm
        specifications={specifications}
        isSubmitting={false}
        onCancel={noop}
        onSubmitSingle={noop}
        onSubmitBulk={noop}
      />,
    );

    fireEvent.change(screen.getByLabelText("Specification"), { target: { value: "spec-nursery" } });
    expect(screen.getByText("nursery_cultivation_plate")).toBeInTheDocument();
  });
});
