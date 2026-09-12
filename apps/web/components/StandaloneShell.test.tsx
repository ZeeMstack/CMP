import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { StandaloneShell } from "./StandaloneShell";

describe("StandaloneShell", () => {
  it("shows the growCMP Waterline wordmark, not a fabricated tenant/farm name", async () => {
    render(withQueryClient(<StandaloneShell>content</StandaloneShell>));
    // PILOT-UX-001A2-R2 (WaterlineWordmark): the wordmark is two styled
    // spans, "grow" (Canopy) + "CMP" (Deepwater), with no separate tagline
    // element -- the old "GrowCMP" single-text-node + "Crop Management
    // Platform" tagline this test originally asserted predates that
    // rebrand.
    await waitFor(() => expect(screen.getByText("grow")).toBeInTheDocument());
    expect(screen.getByText("CMP")).toBeInTheDocument();
    expect(screen.queryByText("Crop Management Platform")).not.toBeInTheDocument();
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
