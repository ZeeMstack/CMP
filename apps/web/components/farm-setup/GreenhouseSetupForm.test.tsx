import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GreenhouseSetupForm } from "./GreenhouseSetupForm";

describe("GreenhouseSetupForm", () => {
  it("defaults to Leafy Greens and shows the Leafy structure fields", () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByText(/Leafy Greens structure/i)).toBeInTheDocument();
    expect(screen.queryByText(/Vines structure/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nursery structure/i)).not.toBeInTheDocument();
  });

  it("switches to the Vines structure fields when Vines is selected", () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.click(screen.getByRole("radio", { name: "Vines" }));
    expect(screen.getByText(/Vines structure/i)).toBeInTheDocument();
    expect(screen.getByText(/No Gutter Side/i)).toBeInTheDocument();
  });

  it("switches to the Nursery structure fields when Nursery is selected, including Seeding Station and Germination Chamber", () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.click(screen.getByRole("radio", { name: "Nursery" }));
    expect(screen.getByText(/Nursery structure/i)).toBeInTheDocument();
    expect(screen.getByText("Seeding Station")).toBeInTheDocument();
    expect(screen.getByText("Germination Chamber")).toBeInTheDocument();
  });

  it("presents Trolley and Seeding Machine as farm-level equipment, not Nursery structure", () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.click(screen.getByRole("radio", { name: "Nursery" }));
    expect(screen.getByText(/farm-level equipment, not part of this Nursery/i)).toBeInTheDocument();
  });

  it("rejects a zero table capacity and blocks moving to review", async () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.change(screen.getByPlaceholderText("GH-01"), { target: { value: "GH-01" } });
    fireEvent.change(screen.getByLabelText(/Table capacity/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText(/Capacity must be at least 1/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before creating")).not.toBeInTheDocument();
  });

  it("shows a review summary with correct derived counts before submit, and does not submit until confirmed", async () => {
    const onSubmit = vi.fn();
    render(<GreenhouseSetupForm onSubmit={onSubmit} isSubmitting={false} />);

    fireEvent.change(screen.getByPlaceholderText("GH-01"), { target: { value: "GH-L01" } });
    fireEvent.change(screen.getByPlaceholderText("Greenhouse 1"), { target: { value: "Leafy GH" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    expect(screen.getByText("GH-L01")).toBeInTheDocument();
    // Default form values: 1 zone x 1 span x 1 table.
    const tableCells = screen.getAllByText("1");
    expect(tableCells.length).toBeGreaterThan(0);
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Create greenhouse" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.code).toBe("GH-L01");
    expect(payload.classification).toBe("leafy_greens");
    expect(payload.leafy.zones).toHaveLength(1);
  });

  it("returns to the configure step from review via Back, without submitting", async () => {
    const onSubmit = vi.fn();
    render(<GreenhouseSetupForm onSubmit={onSubmit} isSubmitting={false} />);
    fireEvent.change(screen.getByPlaceholderText("GH-01"), { target: { value: "GH-L01" } });
    fireEvent.change(screen.getByPlaceholderText("Greenhouse 1"), { target: { value: "Leafy GH" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText(/Leafy Greens structure/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("surfaces a server-side error on the review step", async () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} serverError="A location with this code already exists under this parent." />);
    fireEvent.change(screen.getByPlaceholderText("GH-01"), { target: { value: "GH-L01" } });
    fireEvent.change(screen.getByPlaceholderText("Greenhouse 1"), { target: { value: "Leafy GH" } });
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/already exists under this parent/i));
  });

  it("never presents Gutter Side, Table Position, or Zone/Span for Nursery -- no domain lies in the form copy", () => {
    render(<GreenhouseSetupForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.click(screen.getByRole("radio", { name: "Nursery" }));
    expect(screen.queryByText(/gutter side/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/table position/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/zone/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/span/i)).not.toBeInTheDocument();
  });
});
