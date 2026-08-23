import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterableSelect } from "./FilterableSelect";

const OPTIONS = [
  { value: "a", label: "NP-001", description: "Capacity: 200" },
  { value: "b", label: "NP-002", description: "Capacity: 150" },
];

describe("FilterableSelect", () => {
  it("shows an empty state when there are no options", () => {
    render(<FilterableSelect options={[]} value="" onChange={vi.fn()} emptyMessage="Nothing here" />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("filters options by typed text", async () => {
    render(<FilterableSelect options={OPTIONS} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByText("NP-001")).toBeInTheDocument());
    fireEvent.change(input, { target: { value: "002" } });
    await waitFor(() => {
      expect(screen.queryByText("NP-001")).not.toBeInTheDocument();
      expect(screen.getByText("NP-002")).toBeInTheDocument();
    });
  });

  it("shows a no-match state when the filter matches nothing", async () => {
    render(<FilterableSelect options={OPTIONS} value="" onChange={vi.fn()} noMatchMessage="No matches found" />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(() => expect(screen.getByText("No matches found")).toBeInTheDocument());
  });

  it("calls onChange and closes the list when an option is chosen", async () => {
    const onChange = vi.fn();
    render(<FilterableSelect options={OPTIONS} value="" onChange={onChange} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByText("NP-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("NP-001"));
    expect(onChange).toHaveBeenCalledWith("a");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows the selected option's label as a placeholder when closed", () => {
    render(<FilterableSelect options={OPTIONS} value="b" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox")).toHaveAttribute("placeholder", "NP-002");
  });

  it("supports keyboard selection via ArrowDown + Enter", async () => {
    const onChange = vi.fn();
    render(<FilterableSelect options={OPTIONS} value="" onChange={onChange} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByText("NP-001")).toBeInTheDocument());
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("closes on Escape without calling onChange", async () => {
    const onChange = vi.fn();
    render(<FilterableSelect options={OPTIONS} value="" onChange={onChange} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByText("NP-001")).toBeInTheDocument());
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not open when disabled", () => {
    render(<FilterableSelect options={OPTIONS} value="" onChange={vi.fn()} disabled />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows a loading state instead of the empty state while options are still loading", () => {
    render(<FilterableSelect options={[]} value="" onChange={vi.fn()} loading emptyMessage="Nothing here" />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
  });

  it("closes the list on blur to an element outside the control (keyboard Tab-away)", async () => {
    render(
      <div>
        <FilterableSelect options={OPTIONS} value="" onChange={vi.fn()} />
        <button type="button">Elsewhere</button>
      </div>,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());
    fireEvent.blur(input, { relatedTarget: screen.getByRole("button", { name: "Elsewhere" }) });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("remains usable with a few hundred options", async () => {
    const manyOptions = Array.from({ length: 300 }, (_, i) => ({
      value: `plate-${i}`,
      label: `NP-${String(i).padStart(4, "0")}`,
    }));
    render(<FilterableSelect options={manyOptions} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    await waitFor(() => expect(screen.getByText("NP-0000")).toBeInTheDocument());
    fireEvent.change(input, { target: { value: "0157" } });
    await waitFor(() => {
      expect(screen.getByText("NP-0157")).toBeInTheDocument();
      expect(screen.queryByText("NP-0000")).not.toBeInTheDocument();
    });
  });
});
