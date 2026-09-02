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

function topNav() {
  return screen.getByRole("navigation", { name: "Main" });
}

const GROUP_LABELS = [
  "Nursery Operations",
  "Production Operations",
  "Harvest & Post-Harvest",
  "Dispatch & Traceability",
  "Farm Setup & Master Data",
];

const GROUP_FIRST_CHILD: Record<string, string> = {
  "Nursery Operations": "/farms/farm-1/nursery/sowings/new",
  "Production Operations": "/farms/farm-1/leafy-production",
  "Harvest & Post-Harvest": "/farms/farm-1/leafy-production/harvest",
  "Dispatch & Traceability": "/farms/farm-1/processing/dispatch",
  "Farm Setup & Master Data": "/farms/farm-1/farm-setup",
};

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
});

describe("AppShell branding", () => {
  it("uses the official product name in the identity bar", () => {
    renderShell("/farms/farm-1");
    expect(screen.getAllByText("grow").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CMP").length).toBeGreaterThan(0);
  });

  it("never displays a superseded or rejected product name", () => {
    renderShell("/farms/farm-1");
    expect(screen.queryByText(/Cultivation Management Platform/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/ImperialFarms CMP/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Imperial Farms CMP/i)).not.toBeInTheDocument();
  });
});

describe("AppShell top navigation (main modules)", () => {
  it("renders Home and every frozen top-level module heading from the approved nav config", () => {
    renderShell("/farms/farm-1");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/farms/farm-1");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("does not render routes removed from primary navigation as top-nav headings", () => {
    renderShell("/farms/farm-1");
    const nav = topNav();
    expect(within(nav).queryByRole("link", { name: "Processing" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Seed Lots" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Locations" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Batches" })).not.toBeInTheDocument();
  });

  it("introduces no fabricated route: every module heading points to its first existing child", () => {
    renderShell("/farms/farm-1");
    const nav = topNav();
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", GROUP_FIRST_CHILD[label]);
    }
  });

  it("current pathname identifies the correct active top module", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Harvest & Post-Harvest" })).toHaveAttribute("aria-current", "true");
    expect(within(nav).getByRole("link", { name: "Production Operations" })).not.toHaveAttribute("aria-current");
  });

  it("activates Dispatch & Traceability, not a fabricated module, for the Recall Cases detail route", () => {
    renderShell("/farms/farm-1/processing/recall-cases/case-1");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Dispatch & Traceability" })).toHaveAttribute("aria-current", "true");
  });

  it("marks Home active and no module active on the farm home route", () => {
    renderShell("/farms/farm-1");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("link", { name: label })).not.toHaveAttribute("aria-current");
    }
  });

  it("marks no module active for a route with no dedicated nav entry (e.g. removed Seed Lots)", () => {
    renderShell("/farms/farm-1/seed-lots");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole("link", { name: label })).not.toHaveAttribute("aria-current");
    }
  });
});

describe("AppShell contextual sidebar", () => {
  function sidebar() {
    return screen.getByRole("complementary");
  }

  it("shows ONLY the active module's children when Farm Setup is active", () => {
    renderShell("/farms/farm-1/farm-setup");
    const aside = sidebar();
    expect(within(aside).getByRole("link", { name: "Greenhouse & Locations" })).toBeInTheDocument();
    expect(within(aside).getByRole("link", { name: "Crops & Varieties" })).toBeInTheDocument();
    expect(within(aside).queryByRole("link", { name: "Seeding" })).not.toBeInTheDocument();
    expect(within(aside).queryByRole("link", { name: "Leafy Production" })).not.toBeInTheDocument();
  });

  it("shows ONLY Nursery's children when Nursery Operations is active", () => {
    renderShell("/farms/farm-1/nursery/germination");
    const aside = sidebar();
    expect(within(aside).getByRole("link", { name: "Seeding" })).toBeInTheDocument();
    expect(within(aside).getByRole("link", { name: "Germination" })).toBeInTheDocument();
    expect(within(aside).queryByRole("link", { name: "Greenhouse & Locations" })).not.toBeInTheDocument();
  });

  it("marks the correct active child with aria-current", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const aside = sidebar();
    expect(within(aside).getByRole("link", { name: "Harvest" })).toHaveAttribute("aria-current", "page");
    expect(within(aside).getByRole("link", { name: "Grading" })).not.toHaveAttribute("aria-current");
  });

  it("renders no contextual sidebar on Home", () => {
    renderShell("/farms/farm-1");
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("renders no contextual sidebar for a route with no dedicated nav entry", () => {
    renderShell("/farms/farm-1/seed-lots");
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });
});

describe("AppShell accessibility", () => {
  it("preserves the skip-to-content link", () => {
    renderShell("/farms/farm-1");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
  });

  it("indicates the active top-level module with more than color: an aria-current attribute", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    const nav = topNav();
    expect(within(nav).getByRole("link", { name: "Harvest & Post-Harvest" })).toHaveAttribute("aria-current");
  });
});

describe("AppShell mobile navigation", () => {
  it("is closed by default and opens via the hamburger toggle", () => {
    renderShell("/farms/farm-1");
    expect(document.getElementById("mobile-nav")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    expect(document.getElementById("mobile-nav")).toBeInTheDocument();
  });

  it("auto-expands the active module and shows its children in the mobile drawer", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    expect(within(mobileNav).getByRole("button", { name: /Harvest & Post-Harvest/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(mobileNav).getByRole("link", { name: "Harvest" })).toHaveAttribute("aria-current", "page");
  });

  it("lets the operator collapse and expand a module group in the mobile drawer", () => {
    renderShell("/farms/farm-1/leafy-production/harvest");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    const toggle = within(mobileNav).getByRole("button", { name: /Harvest & Post-Harvest/ });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("closes the mobile menu after following a leaf link", () => {
    renderShell("/farms/farm-1");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    fireEvent.click(within(mobileNav).getByRole("link", { name: "Home" }));
    expect(document.getElementById("mobile-nav")).not.toBeInTheDocument();
  });

  it("keeps every existing href correct inside the mobile drawer", () => {
    renderShell("/farms/farm-1");
    fireEvent.click(screen.getByRole("button", { name: /toggle navigation/i }));
    const mobileNav = document.getElementById("mobile-nav") as HTMLElement;
    fireEvent.click(within(mobileNav).getByRole("button", { name: /Farm Setup & Master Data/ }));
    expect(within(mobileNav).getByRole("link", { name: "Carrier Specifications" })).toHaveAttribute(
      "href",
      "/carrier-specifications",
    );
  });
});
