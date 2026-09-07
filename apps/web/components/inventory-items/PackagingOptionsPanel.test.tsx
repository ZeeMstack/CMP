import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { PackagingOptionsPanel } from "./PackagingOptionsPanel";

const hooks = vi.hoisted(() => ({
  useInventoryItemPackaging: vi.fn(),
  useCreateInventoryItemPackaging: vi.fn(),
  useUpdateInventoryItemPackaging: vi.fn(),
  useDeactivateInventoryItemPackaging: vi.fn(),
  useReactivateInventoryItemPackaging: vi.fn(),
}));

vi.mock("@/lib/query/hooks", () => hooks);

function mutationStub(overrides: Partial<{ isPending: boolean; mutate: ReturnType<typeof vi.fn> }> = {}) {
  return { isPending: false, mutate: vi.fn(), ...overrides };
}

const ACTIVE_ROW = {
  id: "pkg-1",
  code: "BAG-25KG",
  display_name: "25kg Bag",
  package_quantity: "25",
  status: "active" as const,
};

const INACTIVE_ROW = { ...ACTIVE_ROW, id: "pkg-2", code: "BAG-10KG", display_name: "10kg Bag", status: "inactive" as const };

describe("PackagingOptionsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useInventoryItemPackaging.mockReturnValue({ data: [], isLoading: false });
    hooks.useCreateInventoryItemPackaging.mockReturnValue(mutationStub());
    hooks.useUpdateInventoryItemPackaging.mockReturnValue(mutationStub());
    hooks.useDeactivateInventoryItemPackaging.mockReturnValue(mutationStub());
    hooks.useReactivateInventoryItemPackaging.mockReturnValue(mutationStub());
  });

  it("renders existing packaging rows with quantity expressed in the item's base UOM", () => {
    hooks.useInventoryItemPackaging.mockReturnValue({ data: [ACTIVE_ROW], isLoading: false });
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    expect(screen.getByText("BAG-25KG")).toBeInTheDocument();
    expect(screen.getByText("25kg Bag")).toBeInTheDocument();
    expect(screen.getByText("25 kg")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an empty state and no separate entity-driven navigation when no packaging exists", () => {
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    expect(screen.getByText("No packaging options configured for this item yet.")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("opens the create form and submits a new packaging option", () => {
    const mutate = vi.fn();
    hooks.useCreateInventoryItemPackaging.mockReturnValue(mutationStub({ mutate }));
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    fireEvent.click(screen.getByRole("button", { name: "Add packaging" }));
    fireEvent.change(screen.getByPlaceholderText("BAG-25KG"), { target: { value: "BAG-50KG" } });
    fireEvent.change(screen.getByPlaceholderText("25kg Bag"), { target: { value: "50kg Bag" } });
    fireEvent.change(screen.getByPlaceholderText("25"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const [payload] = mutate.mock.calls[0];
    expect(payload).toMatchObject({ inventory_item_id: "item-1", code: "BAG-50KG", display_name: "50kg Bag", package_quantity: "50" });
  });

  it("rejects a non-positive quantity client-side without calling the mutation", () => {
    const mutate = vi.fn();
    hooks.useCreateInventoryItemPackaging.mockReturnValue(mutationStub({ mutate }));
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    fireEvent.click(screen.getByRole("button", { name: "Add packaging" }));
    fireEvent.change(screen.getByPlaceholderText("BAG-25KG"), { target: { value: "BAG-0" } });
    fireEvent.change(screen.getByPlaceholderText("25kg Bag"), { target: { value: "Zero Bag" } });
    fireEvent.change(screen.getByPlaceholderText("25"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Quantity must be a positive number.")).toBeInTheDocument();
  });

  it("shows the reversible active/inactive lifecycle controls for each state", () => {
    hooks.useInventoryItemPackaging.mockReturnValue({ data: [ACTIVE_ROW, INACTIVE_ROW], isLoading: false });
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
  });

  it("surfaces a backend error from the create mutation", () => {
    const mutate = vi.fn((_payload, opts) => opts.onError(new AppError("conflict", "code already used", 409)));
    hooks.useCreateInventoryItemPackaging.mockReturnValue(mutationStub({ mutate }));
    render(<PackagingOptionsPanel itemId="item-1" baseUomCode="kg" />);

    fireEvent.click(screen.getByRole("button", { name: "Add packaging" }));
    fireEvent.change(screen.getByPlaceholderText("BAG-25KG"), { target: { value: "BAG-1" } });
    fireEvent.change(screen.getByPlaceholderText("25kg Bag"), { target: { value: "1kg Bag" } });
    fireEvent.change(screen.getByPlaceholderText("25"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByText("code already used")).toBeInTheDocument();
  });
});
