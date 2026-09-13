import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

import LoginPage from "./page";

describe("LoginPage", () => {
  it("shows the canonical GrowCMP wordmark (default/light variant), not a fabricated tenant/farm name", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    // The canonical WaterlineWordmark lockup (same component AppShell/
    // StandaloneShell use) splits "grow"/"CMP" into two spans for two-tone
    // coloring -- assert both are present rather than a single "GrowCMP"
    // string, which this component never renders.
    expect(screen.getByText("grow")).toBeInTheDocument();
    expect(screen.getByText("CMP")).toBeInTheDocument();
    // Light auth panel -> the wordmark's default variant, not inverse.
    expect(screen.getByText("grow")).toHaveClass("text-wl-canopy");
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
  });

  it("renders the UX-004 auth copy", () => {
    render(<LoginPage />);
    expect(screen.getByText("Sign in to continue to GrowCMP.")).toBeInTheDocument();
    expect(screen.getByText("Secure sign-in managed by your organization.")).toBeInTheDocument();
    // No technical returnTo text visible anywhere on the page.
    expect(screen.queryByText(/returnTo/i)).not.toBeInTheDocument();
  });

  it("renders exactly one Google action and one organization-account action, no duplicates", () => {
    render(<LoginPage />);
    const googleLinks = screen.getAllByRole("link", { name: /google/i });
    const organizationLinks = screen.getAllByRole("link", { name: /organization account/i });
    expect(googleLinks).toHaveLength(1);
    expect(organizationLinks).toHaveLength(1);
  });

  it("does not label the generic route as 'work email' -- it doesn't force any specific connection", () => {
    render(<LoginPage />);
    expect(screen.queryByText(/work email/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with organization account" })).toBeInTheDocument();
  });

  it("routes the organization-account action through the unmodified sign-in route, preserving sanitized returnTo", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /organization account/i });
    expect(link.getAttribute("href")).toBe("/auth/login?returnTo=%2Ffarms");
  });

  it("routes Google through the same /auth/login route with only the verified connection param added", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /google/i });
    expect(link.getAttribute("href")).toBe("/auth/login?connection=google-oauth2&returnTo=%2Ffarms");
  });

  it("never renders email/password inputs, a form, or a checkbox -- credential-auth stop condition honored", () => {
    // The current @auth0/nextjs-auth0@4.26.0 integration has no supported
    // embedded username/password mechanism (verified against the
    // installed SDK -- see the module doc comment in page.tsx), so this
    // page must never render fake/nonfunctional credential controls.
    const { container } = render(<LoginPage />);
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/forgot password/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/keep me signed in/i)).not.toBeInTheDocument();
  });

  it("renders the approved hero copy -- no dashboard/metrics/fake-activity content", () => {
    render(<LoginPage />);
    expect(screen.getByText("Nursery, production, quality and post-harvest in one traceable system.")).toBeInTheDocument();
    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Track")).toBeInTheDocument();
    expect(screen.getByText("Ensure")).toBeInTheDocument();
    expect(screen.getByText("Grow")).toBeInTheDocument();
    // Content from the rejected dashboard-style right panel (earlier
    // rounds) must never reappear.
    expect(screen.queryByText("Illustrative operational view")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample operational activity")).not.toBeInTheDocument();
    expect(screen.queryByText(/germination/i)).not.toBeInTheDocument();
  });

  it("uses the real local greenhouse asset, never a remote/hotlinked image", () => {
    const { container } = render(<LoginPage />);
    const images = Array.from(container.querySelectorAll("img"));
    expect(images.length).toBeGreaterThan(0);
    for (const img of images) {
      const src = img.getAttribute("src") ?? "";
      expect(src).not.toMatch(/^https?:\/\//);
    }
    // next/image's local optimizer path still encodes the original local
    // source URL -- confirms this is genuinely the supplied local asset,
    // not merely "any local-looking string".
    expect(images.some((img) => (img.getAttribute("src") ?? "").includes("growcmp-greenhouse"))).toBe(true);
  });

  it("introduces no data-fetching hook -- the hero panel is static markup", () => {
    // No QueryClientProvider is set up for this render; if any component
    // called useQuery/useSuspenseQuery it would throw before this
    // assertion is reached at all.
    expect(() => render(<LoginPage />)).not.toThrow();
  });
});
