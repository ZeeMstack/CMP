import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdminShell } from "./AdminShell";

describe("AdminShell", () => {
  it("shows the GrowCMP product brand and Platform Administration context, not a fabricated tenant/farm name", () => {
    render(<AdminShell>content</AdminShell>);
    expect(screen.getByText("GrowCMP")).toBeInTheDocument();
    expect(screen.getByText("Platform Administration")).toBeInTheDocument();
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
    expect(screen.queryByText("Crop Management Platform")).not.toBeInTheDocument();
  });

  it("renders with no AuthBootstrapProvider/QueryClientProvider present -- it never reads or fabricates tenant/farm identity", () => {
    // No withQueryClient wrapper here, deliberately: if AdminShell ever
    // started calling useAuthBootstrap() (or any tenant/farm hook), this
    // render would throw ("must be used within an AuthBootstrapProvider")
    // instead of silently passing.
    expect(() => render(<AdminShell>content</AdminShell>)).not.toThrow();
  });

  it("links back to the normal CMP experience", () => {
    render(<AdminShell>content</AdminShell>);
    expect(screen.getByRole("link", { name: /back to cmp/i })).toHaveAttribute("href", "/farms");
  });
});
