import { expect, test } from "@playwright/test";

import * as fixtures from "./fixtures";

/**
 * AUTH-001B3 deterministic E2E coverage for route gating, access states,
 * and business 401/403 recovery. No real Auth0, no live FastAPI --
 * everything is intercepted at the browser boundary, including the BFF's
 * own /api/auth/bootstrap.
 */

test("A: unauthenticated visit to a protected route redirects to /login; protected content never visible", async ({
  page,
}) => {
  await page.route("**/api/auth/bootstrap", (route) =>
    route.fulfill({
      status: 401,
      json: { status: "unauthenticated", user: null, memberships: [], selectedTenantId: null },
    }),
  );
  // Deliberately no mock for /api/farms -- if the gate failed to block
  // navigation, this test would still need to fail on a real assertion,
  // not pass by accident on an empty/erroring response.

  await page.goto("/farms/abc/crop-batches/xyz?view=quality");

  await expect(page).toHaveURL(/\/login\?returnTo=/);
  const returnTo = new URL(page.url()).searchParams.get("returnTo");
  expect(returnTo).toBe("/farms/abc/crop-batches/xyz?view=quality");
  await expect(page.getByRole("heading", { name: "CMP" })).toBeVisible();
  await expect(page.getByText(fixtures.farm.name)).toHaveCount(0);
});

test("B: authenticated zero-membership redirects to /access-denied", async ({ page }) => {
  await page.route("**/api/auth/bootstrap", (route) =>
    route.fulfill({
      json: {
        status: "authenticated",
        user: { id: "u1", email: "person@example.com", displayName: "Person" },
        memberships: [],
        selectedTenantId: null,
      },
    }),
  );

  await page.goto("/farms");

  await expect(page).toHaveURL("/access-denied");
  await expect(page.getByRole("heading", { name: "Access not provisioned" })).toBeVisible();
  await expect(page.getByText("person@example.com")).toBeVisible();
  await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("C: authenticated multi-membership with no selection redirects to /select-tenant", async ({ page }) => {
  await page.route("**/api/auth/bootstrap", (route) =>
    route.fulfill({
      json: {
        status: "authenticated",
        user: { id: "u1", email: "person@example.com", displayName: "Person" },
        memberships: [
          { tenantId: "t1", tenantCode: "A", tenantName: "Alpha Tenant", roleCode: "tenant_admin" },
          { tenantId: "t2", tenantCode: "B", tenantName: "Beta Tenant", roleCode: "read_only" },
        ],
        selectedTenantId: null,
      },
    }),
  );

  await page.goto("/farms");

  await expect(page).toHaveURL("/select-tenant");
  await expect(page.getByText("Alpha Tenant")).toBeVisible();
  await expect(page.getByText("Beta Tenant")).toBeVisible();
});

test("D: a business 401/session_expired after a protected page loaded clears data and redirects to /login with a safe returnTo", async ({
  page,
}) => {
  // PILOT-BLOCKER-008 CTO-review follow-up: a second stale assumption in
  // this fixture, found while fixing the nav selector below -- the
  // `/api/auth/bootstrap` mock previously always reported "authenticated",
  // forever, even after the simulated session expiry. This flag lets the
  // mock truthfully model what a REAL expired session's bootstrap re-check
  // would report, flipping to "unauthenticated" at the same moment the
  // business 401 is armed below, exactly mirroring the real world -- see
  // the FINAL REPORT's root-cause note for why this alone does not yet
  // make the assertion below pass (a confirmed product defect, not a
  // remaining test staleness).
  let sessionExpired = false;
  await page.route("**/api/auth/bootstrap", (route) =>
    route.fulfill({
      json: sessionExpired
        ? { status: "unauthenticated", user: null, memberships: [], selectedTenantId: null }
        : fixtures.authBootstrap,
    }),
  );
  await page.route("**/api/farms", (route) => route.fulfill({ json: [fixtures.farm] }));
  await page.route(`**/api/farms/${fixtures.farm.id}`, (route) => route.fulfill({ json: fixtures.farm }));
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto(`/farms/${fixtures.farm.id}`);
  await expect(page.getByRole("heading", { name: fixtures.farm.name })).toBeVisible();

  // The session "expires": the very next business request comes back
  // with the BFF's stable session_expired body, and any subsequent
  // bootstrap re-check now truthfully reports it too.
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=all`, (route) =>
    route.fulfill({ status: 401, json: { error: "session_expired" } }),
  );
  sessionExpired = true;

  // PILOT-BLOCKER-008 CTO-review follow-up: the top nav no longer has a
  // "Batches" link (aria-label="Primary" doesn't exist either -- AppShell's
  // real nav landmarks are aria-label="Main"/"<Module> navigation", per
  // PILOT-UX-001A2-R2's top-nav-plus-contextual-sidebar redesign; Batches
  // was deliberately moved out of primary navigation, see AppShell.tsx's
  // own module comment). The current, real way an operator reaches the
  // Batch register from a freshly-loaded Home page is the "Active batches"
  // KPI card (`app/farms/[farmId]/page.tsx`'s `SummaryCard`, linking to
  // exactly `/farms/{farmId}/crop-batches`) -- this preserves the test's
  // actual intent (navigating to the page whose `operational-summary?
  // state=all` request the mock above intercepts) via the CURRENT
  // navigation contract, not the removed one.
  await page.getByRole("link", { name: /Active batches/i }).click();

  await expect(page).toHaveURL(/\/login\?returnTo=/);
  const returnTo = new URL(page.url()).searchParams.get("returnTo");
  expect(returnTo).toBe(`/farms/${fixtures.farm.id}/crop-batches`);
  await expect(page.getByText(fixtures.farm.name)).toHaveCount(0);
});

test("E: a business 403 keeps the user on the CMP page with a permission-specific error, no login redirect", async ({
  page,
}) => {
  await page.route("**/api/auth/bootstrap", (route) => route.fulfill({ json: fixtures.authBootstrap }));
  await page.route("**/api/farms", (route) => route.fulfill({ json: [fixtures.farm] }));
  // The farm-scoped layout's own useFarm() call must succeed -- otherwise
  // its unrelated network-error state would pre-empt Home's own 403
  // handling before Home ever gets a chance to render anything.
  await page.route(`**/api/farms/${fixtures.farm.id}`, (route) => route.fulfill({ json: fixtures.farm }));
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ status: 403 }),
  );

  await page.goto(`/farms/${fixtures.farm.id}`);

  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}`);
  await expect(page.getByText("Access denied")).toBeVisible();
  await expect(page.getByText("You don't have access to this operation or workspace context.")).toBeVisible();
});
