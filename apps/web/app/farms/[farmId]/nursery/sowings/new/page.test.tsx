import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

import { withQueryClient } from "@/lib/test-utils";

import NewSowingPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NewSowingPage", () => {
  it("shows the Nursery journey indicator with Seeding as the current stage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<NewSowingPage />));

    await waitFor(() => expect(screen.getByRole("navigation", { name: "Nursery journey" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Seeding/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("heading", { name: "New Sowing" })).toBeInTheDocument();
  });
});
