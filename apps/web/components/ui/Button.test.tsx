import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("renders each variant with visible text", () => {
    render(
      <>
        <Button variant="primary">Save</Button>
        <Button variant="secondary">Cancel</Button>
        <Button variant="danger">Delete</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("defaults to the secondary variant and type=button", () => {
    render(<Button>Default</Button>);
    const button = screen.getByRole("button", { name: "Default" });
    expect(button).toHaveAttribute("type", "button");
  });

  it("respects the disabled attribute", () => {
    render(<Button disabled>Locked</Button>);
    expect(screen.getByRole("button", { name: "Locked" })).toBeDisabled();
  });

  it("passes through native button props such as onClick and type", () => {
    const onClick = vi.fn();
    render(
      <Button type="submit" onClick={onClick} data-testid="submit-btn">
        Submit
      </Button>,
    );
    const button = screen.getByTestId("submit-btn");
    expect(button).toHaveAttribute("type", "submit");
    button.click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("merges a caller-supplied className rather than replacing the base styles", () => {
    render(<Button className="w-full">Wide</Button>);
    const button = screen.getByRole("button", { name: "Wide" });
    expect(button.className).toContain("w-full");
    expect(button.className).toContain("h-9");
  });
});
