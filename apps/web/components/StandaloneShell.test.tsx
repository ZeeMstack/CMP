import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { StandaloneShell } from "./StandaloneShell";

describe("StandaloneShell", () => {
  it("shows the GrowCMP product brand and tagline, not a fabricated tenant/farm name", async () => {
    render(withQueryClient(<StandaloneShell>content</StandaloneShell>));
    await waitFor(() => expect(screen.getByText("GrowCMP")).toBeInTheDocument());
    expect(screen.getByText("Crop Management Platform")).toBeInTheDocument();
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
  });

  it("shows real Tenant context sourced from useAuthBootstrap, not a hardcoded name", async () => {
    render(withQueryClient(<StandaloneShell>content</StandaloneShell>));
    await waitFor(() => expect(screen.getByText("Test Tenant")).toBeInTheDocument());
  });

  it("links back to the farm picker", async () => {
    render(withQueryClient(<StandaloneShell>content</StandaloneShell>));
    await waitFor(() => expect(screen.getByRole("link", { name: /back to farms/i })).toHaveAttribute("href", "/farms"));
  });

  it("renders its children", async () => {
    render(withQueryClient(<StandaloneShell>unique-child-content</StandaloneShell>));
    await waitFor(() => expect(screen.getByText("unique-child-content")).toBeInTheDocument());
  });
});
