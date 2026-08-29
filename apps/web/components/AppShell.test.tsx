import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let currentPathname = "/farms/farm-1";
const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
  useRouter: () => ({ push: pushMock }),
}));

import { withQueryClient } from "@/lib/test-utils";

import { AppShell, findActiveHref } from "./AppShell";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  currentPathname = "/farms/farm-1";
  pushMock.mockClear();
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderShell(pathname: string) {
  currentPathname = pathname;
  render(withQueryClient(<AppShell farmId="farm-1">page content</AppShell>));
}

/** The desktop <aside> is always mounted (hidden via CSS below `md:`), and
 * the mobile nav only mounts once the hamburger is opened -- so by default
 * exactly one nav[aria-label="Primary"] exists and this is safe to use
 * unqualified. */
function primaryNav() {
  return screen.getByRole("navigation", { name: "Primary" });
}

const GROUP_LABELS = [
  "Nursery Operations",
  "Production Operations",
  "Harvest & Post-Harvest",
  "Dispatch & Traceability",
  "Farm Setup & Master Data",
];

function openAllGroups(nav: HTMLElement) {
  for (const label of GROUP_LABELS) {
    const toggle = within(nav).getByRole("button", { name: new RegExp(label) });
    if (toggle.getAttribute("aria-expanded") === "false") {
      fireEvent.click(toggle);
    }
  }
}

describe("findActiveHref (most-specific matching)", () => {
  const hrefs = [
    "/farms/farm-1",
    "/farms/farm-1/leafy-production",
    "/farms/farm-1/leafy-production/transfer",
    "/farms/farm-1/leafy-production/harvest",
    "/farms/farm-1/processing/graded-lots",
    "/farms/farm-1/processing/recall-cases",
  ];

  it("picks Harvest over the shorter Leafy Production prefix", () => {
    expect(findActiveHref("/farms/farm-1/leafy-production/harvest", hrefs)).toBe(
      "/farms/farm-1/leafy-production/harvest",
    );
  });

  it("picks Transfer to Production over the shorter Leafy Production prefix", () => {
    expect(findActiveHref("/farms/farm-1/leafy-production/transfer", hrefs)).toBe(
      "/farms/farm-1/leafy-production/transfer",
    );
  });

  it("picks the bare Leafy Production route when nothing more specific matches", () => {
    expect(findActiveHref("/farms/farm-1/leafy-production", hrefs)).toBe("/farms/farm-1/leafy-production");
  });

  it("matches a detail route under a list route (Graded Produce)", () => {
    expect(findActiveHref("/farms/farm-1/processing/graded-lots/gpl-123", hrefs)).toBe(
      "/farms/farm-1/processing/graded-lots",
    );
  });

  it("matches a detail route under a list route (Recall Cases)", () => {
    expect(findActiveHref("/farms/farm-1/processing/recall-cases/case-1", hrefs)).toBe(
      "/farms/farm-1/processing/recall-cases",
    );
  });

  it("returns null when nothing matches, not even Home, for a route outside the farm namespace", () => {
    expect(findActiveHref("/login", hrefs)).toBeNull();
  });

  it("falls back to Home for a farm route with no more specific nav match (e.g. removed Seed Lots)", () => {
    expect(findActiveHref("/farms/farm-1/seed-lots", hrefs)).toBe("/farms/farm-1");
  });

  it("does not treat Home as active for a farm sub-route", () => {
    expect(findActiveHref("/farms/farm-1/leafy-production/harvest", hrefs)).not.toBe("/farms/farm-1");
  });
});

describe("AppShell branding", () => {
  it("uses the official product name and tagline", () => {
    renderShell("/farms/farm-1");
    expect(screen.getAllByText("ImperialFarms CMP").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Crop Management Platform").length).toBeGreaterThan(0);
  });

  it("never displays the rejected product name", () => {
    renderShell("/farms/farm-1");
    expect(screen.queryByText(/Cultivation Management Platform/i)).not.toBeInTheDocument();
  });
});

describe("AppShell frozen navigation tree", () => {
  it("renders Home and every frozen top-level group", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/farms/farm-1");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("does not render routes removed from primary navigation as nav links", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    openAllGroups(nav);
    expect(within(nav).queryByRole("link", { name: "Processing" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Seed Lots" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Locations" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Batches" })).not.toBeInTheDocument();
  });

  it("renders the correct href for every frozen leaf", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    openAllGroups(nav);

    const expectations: [string, string][] = [
      ["Seeding", "/farms/farm-1/nursery/sowings/new"],
      ["Germination", "/farms/farm-1/nursery/germination"],
      ["Seedling", "/farms/farm-1/nursery/seedling"],
      ["Transfer to Inter Leafy Greens", "/farms/farm-1/nursery/intersalads"],
      ["Leafy Production", "/farms/farm-1/leafy-production"],
      ["Transfer to Production", "/farms/farm-1/leafy-production/transfer"],
      ["Harvest", "/farms/farm-1/leafy-production/harvest"],
      ["Grading", "/farms/farm-1/processing/grading"],
      ["Graded Produce", "/farms/farm-1/processing/graded-lots"],
      ["Packing", "/farms/farm-1/processing/packing"],
      ["Finished Goods", "/farms/farm-1/processing/finished-goods"],
      ["Cold Storage", "/farms/farm-1/processing/cold-storage"],
      ["Dispatch", "/farms/farm-1/processing/dispatch"],
      ["Traceability", "/farms/farm-1/traceability"],
      ["Recall Cases", "/farms/farm-1/processing/recall-cases"],
      ["Greenhouse & Locations", "/farms/farm-1/farm-setup"],
      ["Carrier Specifications", "/carrier-specifications"],
      ["Crops & Varieties", "/crops"],
      ["Production Systems", "/production-systems"],
      ["Workflows", "/workflows"],
      ["Grade Definitions", "/grade-definitions"],
      ["Packaging Units", "/packaging-units"],
      ["Pack Specifications", "/pack-specifications"],
    ];
    for (const [label, href] of expectations) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("keeps Greenhouse & Locations and Carrier Specifications as distinct, unmerged leaves", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    openAllGroups(nav);
    // Two separate links, not one combined destination.
    expect(within(nav).getByRole("link", { name: "Greenhouse & Locations" })).toHaveAttribute(
      "href",
      "/farms/farm-1/farm-setup",
    );
    expect(within(nav).getByRole("link", { name: "Carrier Specifications" })).toHaveAttribute(
      "href",
      "/carrier-specifications",
    );
  });
});

describe("AppShell active-route matching and auto-expand", () => {
  it("does not fall back to Home for a route with no dedicated nav entry (e.g. removed Seed Lots)", () => {
    renderShell("/farms/farm-1/seed-lots");
    const nav = primaryNav();
    expect(within(nav).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("button", { name: new RegExp(label) })).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("marks Home active and no group active on the farm home route", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("button", { name: new RegExp(label) })).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("activates Harvest, not Leafy Production, and auto-expands Harvest & Post-Harvest", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const nav = primaryNav();
    const harvestGroupToggle = within(nav).getByRole("button", { name: /Harvest & Post-Harvest/ });
    expect(harvestGroupToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("link", { name: "Harvest" })).toHaveAttribute("aria-current", "page");

    const productionGroupToggle = within(nav).getByRole("button", { name: /Production Operations/ });
    if (productionGroupToggle.getAttribute("aria-expanded") === "false") {
      fireEvent.click(productionGroupToggle);
    }
    expect(within(nav).getByRole("link", { name: "Leafy Production" })).not.toHaveAttribute("aria-current");
  });

  it("activates Transfer to Production, not Leafy Production, on the transfer route", () => {
    renderShell("/farms/farm-1/leafy-production/transfer");
    const nav = primaryNav();
    expect(within(nav).getByRole("button", { name: /Production Operations/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Transfer to Production" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Leafy Production" })).not.toHaveAttribute("aria-current");
  });

  it("activates Graded Produce for a graded-lot detail route", () => {
    renderShell("/farms/farm-1/processing/graded-lots/gpl-123");
    const nav = primaryNav();
    expect(within(nav).getByRole("button", { name: /Harvest & Post-Harvest/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Graded Produce" })).toHaveAttribute("aria-current", "page");
  });

  it("activates Recall Cases for a recall-case detail route", () => {
    renderShell("/farms/farm-1/processing/recall-cases/case-1");
    const nav = primaryNav();
    expect(within(nav).getByRole("button", { name: /Dispatch & Traceability/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Recall Cases" })).toHaveAttribute("aria-current", "page");
  });

  it("respects a manual collapse of a non-active group -- it does not spring back open", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const nav = primaryNav();
    const nurseryToggle = within(nav).getByRole("button", { name: /Nursery Operations/ });
    // Nursery starts collapsed since it isn't the active group; open then
    // close it explicitly, and it must stay closed.
    fireEvent.click(nurseryToggle);
    expect(nurseryToggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(nurseryToggle);
    expect(nurseryToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("lets the operator collapse even the active group", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const nav = primaryNav();
    const harvestToggle = within(nav).getByRole("button", { name: /Harvest & Post-Harvest/ });
    expect(harvestToggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(harvestToggle);
    expect(harvestToggle).toHaveAttribute("aria-expanded", "false");
  });
});

describe("AppShell accessibility", () => {
  it("uses aria-expanded/aria-controls on group toggles", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    const toggle = within(nav).getByRole("button", { name: /Nursery Operations/ });
    expect(toggle).toHaveAttribute("aria-expanded");
    expect(toggle).toHaveAttribute("aria-controls");
  });

  it("preserves the skip-to-content link", () => {
    renderShell("/farms/farm-1");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
  });

  it("renders no clickable divs for navigation -- groups are real buttons, leaves are real links", () => {
    renderShell("/farms/farm-1");
    const nav = primaryNav();
    for (const label of GROUP_LABELS) {
      const toggle = within(nav).getByRole("button", { name: new RegExp(label) });
      expect(toggle.tagName).toBe("BUTTON");
    }
    expect(within(nav).getByRole("link", { name: "Home" }).tagName).toBe("A");
  });
});

describe("AppShell mobile navigation", () => {
  it("is closed by default and opens via the hamburger toggle", () => {
    renderShell("/farms/farm-1");
    expect(document.getElementById("mobile-nav")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    expect(document.getElementById("mobile-nav")).toBeInTheDocument();
  });

  it("supports grouped navigation inside the mobile menu and auto-expands the active group", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    expect(within(mobileNav).getByRole("button", { name: /Harvest & Post-Harvest/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(mobileNav).getByRole("link", { name: "Harvest" })).toHaveAttribute("aria-current", "page");
  });

  it("collapsing one group in the mobile menu does not remove sign out or other groups", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    const harvestToggle = within(mobileNav).getByRole("button", { name: /Harvest & Post-Harvest/ });
    fireEvent.click(harvestToggle);
    expect(harvestToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(mobileNav).getByRole("button", { name: /Nursery Operations/ })).toBeInTheDocument();
    expect(within(mobileNav).getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("closes the mobile menu after following a leaf link", () => {
    renderShell("/farms/farm-1");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    fireEvent.click(within(mobileNav).getByRole("link", { name: "Home" }));
    expect(document.getElementById("mobile-nav")).not.toBeInTheDocument();
  });
});
