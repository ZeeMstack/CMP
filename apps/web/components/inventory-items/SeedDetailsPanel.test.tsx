import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppError } from "@/lib/errors/adapter";
import { SeedDetailsPanel } from "./SeedDetailsPanel";

const hooks = vi.hoisted(() => ({
  useSeedProfileForItem: vi.fn(),
  useCrops: vi.fn(),
  useVarieties: vi.fn(),
  useCreateSeedProfile: vi.fn(),
  useUpdateSeedProfile: vi.fn(),
  useRemoveSeedProfile: vi.fn(),
}));

vi.mock("@/lib/query/hooks", () => hooks);

function mutationStub(overrides: Partial<{ isPending: boolean; mutate: ReturnType<typeof vi.fn> }> = {}) {
  return { isPending: false, mutate: vi.fn(), ...overrides };
}

const CROPS = [{ id: "crop-1", common_name: "Lettuce" }];
const VARIETIES = [{ id: "variety-1", name: "Salanova" }];

const PROFILE = { id: "profile-1", inventory_item_id: "item-1", crop_id: "crop-1", variety_id: "variety-1" };

describe("SeedDetailsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useSeedProfileForItem.mockReturnValue({ data: null, isLoading: false });
    hooks.useCrops.mockReturnValue({ data: CROPS });
    hooks.useVarieties.mockReturnValue({ data: VARIETIES });
    hooks.useCreateSeedProfile.mockReturnValue(mutationStub());
    hooks.useUpdateSeedProfile.mockReturnValue(mutationStub());
    hooks.useRemoveSeedProfile.mockReturnValue(mutationStub());
  });

  it("renders the no-Seed-Details state and offers to mark the item as seed", () => {
    render(<SeedDetailsPanel itemId="item-1" />);

    expect(screen.getByText("This item is not configured as seed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark as seed" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("renders the configured crop/variety state with pre-use edit/remove controls", () => {
    hooks.useSeedProfileForItem.mockReturnValue({ data: PROFILE, isLoading: false });
    render(<SeedDetailsPanel itemId="item-1" />);

    expect(screen.getByText("Lettuce", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("submits a new Seed Details profile with the selected crop/variety", () => {
    const mutate = vi.fn();
    hooks.useCreateSeedProfile.mockReturnValue(mutationStub({ mutate }));
    render(<SeedDetailsPanel itemId="item-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Mark as seed" }));
    fireEvent.change(screen.getByLabelText("Crop"), { target: { value: "crop-1" } });
    fireEvent.change(screen.getByLabelText("Variety"), { target: { value: "variety-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const [payload] = mutate.mock.calls[0];
    expect(payload).toMatchObject({ inventory_item_id: "item-1", crop_id: "crop-1", variety_id: "variety-1" });
  });

  it("removes an existing Seed Details profile", () => {
    const mutate = vi.fn();
    hooks.useSeedProfileForItem.mockReturnValue({ data: PROFILE, isLoading: false });
    hooks.useRemoveSeedProfile.mockReturnValue(mutationStub({ mutate }));
    render(<SeedDetailsPanel itemId="item-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const [payload] = mutate.mock.calls[0];
    expect(payload).toMatchObject({ profileId: "profile-1", itemId: "item-1" });
  });

  it("translates the backend structural-lock error into an understandable, non-technical message", () => {
    const mutate = vi.fn((_payload, opts) =>
      opts.onError(new AppError("conflict", "Seed Details are structurally locked once the item has any posted Goods Receipt", 409)),
    );
    hooks.useSeedProfileForItem.mockReturnValue({ data: PROFILE, isLoading: false });
    hooks.useRemoveSeedProfile.mockReturnValue(mutationStub({ mutate }));
    render(<SeedDetailsPanel itemId="item-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    expect(
      screen.getByText(
        "This item has already been received into inventory and can no longer change its seed configuration. Deactivate this item and create a replacement if this needs correcting.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/structurally locked/i)).not.toBeInTheDocument();
  });

  it("never exposes the internal entity name or 'active Seed Details/profile' wording", () => {
    hooks.useSeedProfileForItem.mockReturnValue({ data: PROFILE, isLoading: false });
    render(<SeedDetailsPanel itemId="item-1" />);

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/InventoryItemSeedProfile/i);
    expect(text).not.toMatch(/active seed details/i);
    expect(text).not.toMatch(/active.{0,10}profile/i);
    expect(screen.getByText("Seed Details")).toBeInTheDocument();
  });
});
