import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

import LoginPage from "./page";

describe("LoginPage", () => {
  it("shows GrowCMP as the product brand, not a fabricated tenant/farm name", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: "GrowCMP" })).toBeInTheDocument();
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
    expect(screen.queryByText(/^CMP$/)).not.toBeInTheDocument();
  });

  it("links sign-in through the Auth0-owned /auth/login route", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /sign in/i });
    expect(link.getAttribute("href")).toMatch(/^\/auth\/login\?returnTo=/);
  });
});
