import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NurseryJourney } from "./NurseryJourney";

describe("NurseryJourney", () => {
  it("renders exactly the five frozen stage labels", () => {
    render(<NurseryJourney farmId="farm-1" current="seeding" />);
    expect(screen.getByRole("link", { name: /Seeding/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Germination/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Seedling/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Transfer to InterVines/ })).toBeInTheDocument();
  });

  it("links every stage to its real, farm-scoped route", () => {
    render(<NurseryJourney farmId="farm-42" current="germination" />);
    expect(screen.getByRole("link", { name: /^Seeding/ })).toHaveAttribute("href", "/farms/farm-42/nursery/sowings/new");
    expect(screen.getByRole("link", { name: /Germination/ })).toHaveAttribute("href", "/farms/farm-42/nursery/germination");
    expect(screen.getByRole("link", { name: /^Seedling/ })).toHaveAttribute("href", "/farms/farm-42/nursery/seedling");
    expect(screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ })).toHaveAttribute(
      "href",
      "/farms/farm-42/nursery/intersalads",
    );
    expect(screen.getByRole("link", { name: /Transfer to InterVines/ })).toHaveAttribute(
      "href",
      "/farms/farm-42/nursery/intervines",
    );
  });

  it("marks only the current stage active, via aria-current and not color alone", () => {
    render(<NurseryJourney farmId="farm-1" current="seedling" />);
    expect(screen.getByRole("link", { name: /Seedling/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("link", { name: /^Seeding/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /Germination/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /Transfer to InterVines/ })).not.toHaveAttribute("aria-current");
    // A visible, non-color cue accompanies the highlighted stage.
    expect(screen.getByText("Current:")).toBeInTheDocument();
  });

  it("displays operator-facing 'Transfer to Inter Leafy Greens' wording while keeping the internal /nursery/intersalads route", () => {
    render(<NurseryJourney farmId="farm-1" current="intersalads" />);
    const link = screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ });
    expect(link).toHaveAttribute("aria-current", "step");
    expect(link).toHaveAttribute("href", "/farms/farm-1/nursery/intersalads");
    expect(screen.queryByRole("link", { name: /^InterSalads$/ })).not.toBeInTheDocument();
  });

  it("marks InterVines active with its own route when current", () => {
    render(<NurseryJourney farmId="farm-1" current="intervines" />);
    const link = screen.getByRole("link", { name: /Transfer to InterVines/ });
    expect(link).toHaveAttribute("aria-current", "step");
    expect(link).toHaveAttribute("href", "/farms/farm-1/nursery/intervines");
  });

  it("is an accessible landmark nav distinct from the page's primary navigation", () => {
    render(<NurseryJourney farmId="farm-1" current="seeding" />);
    expect(screen.getByRole("navigation", { name: "Nursery journey" })).toBeInTheDocument();
  });

  it("PILOT-UX-003: shows InterSalads/InterVines as an 'or'-joined pair, never a further sequential arrow between them", () => {
    render(<NurseryJourney farmId="farm-1" current="seedling" />);
    expect(screen.getByText("or")).toBeInTheDocument();
    // Both live inside the same grouped list item -- one arrow leads into
    // the pair from Seedling, not a separate arrow between the two of them.
    const intersalads = screen.getByRole("link", { name: /Transfer to Inter Leafy Greens/ });
    const intervines = screen.getByRole("link", { name: /Transfer to InterVines/ });
    expect(intersalads.closest("li")).toBe(intervines.closest("li"));
  });
});
