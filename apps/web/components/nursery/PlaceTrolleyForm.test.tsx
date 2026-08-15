import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import { PlaceTrolleyForm } from "./PlaceTrolleyForm";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const TROLLEYS = [
  { id: "trolley-1", code: "GT-01", name: "Trolley 1", status: "active" },
  { id: "trolley-2", code: "GT-02", name: "Trolley 2", status: "active" },
];
const CHAMBERS = [
  { id: "chamber-1", code: "GC-01", name: "Germination Chamber 1", trolley_capacity: 2, active_trolley_count: 1, remaining_capacity: 1 },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/germination/chambers/available")) return jsonResponse(overrides.chambers ?? CHAMBERS);
      if (url.includes("/assets")) return jsonResponse(overrides.trolleys ?? TROLLEYS);
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function fillAndReview() {
  await waitFor(() => expect(screen.getByText("GT-01")).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText(/^trolley$/i), { target: { value: "trolley-1" } });
  fireEvent.change(screen.getByLabelText(/germination chamber/i), { target: { value: "chamber-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
}

describe("PlaceTrolleyForm", () => {
  it("shows a zero-eligible-Chamber state", async () => {
    stubFetch({ chambers: [] });
    render(withQueryClient(<PlaceTrolleyForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() =>
      expect(screen.getByText(/no germination chambers are configured/i)).toBeInTheDocument(),
    );
  });

  it("shows remaining capacity in the Chamber picker", async () => {
    stubFetch();
    render(withQueryClient(<PlaceTrolleyForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText(/GC-01 — 1 of 2 remaining/)).toBeInTheDocument());
  });

  it("blocks Review until both Trolley and Chamber are chosen", async () => {
    stubFetch();
    render(withQueryClient(<PlaceTrolleyForm farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("GT-01")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/trolley is required/i)).toBeInTheDocument());
  });

  it("shows a review screen with human-readable codes and capacity context, then submits on confirm", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    render(withQueryClient(<PlaceTrolleyForm farmId="farm-1" onSubmit={onSubmit} onCancel={vi.fn()} isSubmitting={false} />));
    await fillAndReview();

    await waitFor(() => expect(screen.getByText("Review before placing")).toBeInTheDocument());
    expect(screen.getByText("GT-01")).toBeInTheDocument();
    expect(screen.getByText("GC-01")).toBeInTheDocument();
    expect(screen.getByText("Chamber capacity").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Currently placed").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Remaining capacity").nextElementSibling).toHaveTextContent("1");
    // No raw UUID visible anywhere in the review.
    expect(screen.queryByText(/trolley-1|chamber-1/)).not.toBeInTheDocument();
    // No biological Germination outcome field.
    expect(screen.queryByText(/germination (check|percentage|rate|outcome)/i)).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Place Trolley" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.trolley_id).toBe("trolley-1");
    expect(payload.chamber_id).toBe("chamber-1");
    expect(payload.client_command_id).toBeTruthy();
  });

  it("calls onCancel without submitting", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(withQueryClient(<PlaceTrolleyForm farmId="farm-1" onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false} />));
    await waitFor(() => expect(screen.getByText("GT-01")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a server error (e.g. capacity or incompatible target) on the review step", async () => {
    stubFetch();
    render(
      withQueryClient(
        <PlaceTrolleyForm
          farmId="farm-1" onSubmit={vi.fn()} onCancel={vi.fn()} isSubmitting={false}
          serverError="Germination Chamber GC-01 has no remaining capacity."
        />,
      ),
    );
    await fillAndReview();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/no remaining capacity/i));
  });
});
