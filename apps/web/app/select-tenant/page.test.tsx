import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { withQueryClient } from "@/lib/test-utils";

import SelectTenantPage from "./page";

describe("SelectTenantPage", () => {
  it("shows GrowCMP as the product brand, not a fabricated tenant/farm name", async () => {
    render(withQueryClient(<SelectTenantPage />));
    await waitFor(() => expect(screen.getByRole("heading", { name: "GrowCMP" })).toBeInTheDocument());
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
  });

  it("lists the real tenant memberships from data, not a hardcoded tenant name", async () => {
    render(withQueryClient(<SelectTenantPage />));
    await waitFor(() => expect(screen.getByText("Test Tenant")).toBeInTheDocument());
  });
});
