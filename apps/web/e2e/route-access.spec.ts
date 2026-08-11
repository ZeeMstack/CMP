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
  await page.route("**/api/auth/bootstrap", (route) => route.fulfill({ json: fixtures.authBootstrap }));
  await page.route("**/api/farms", (route) => route.fulfill({ json: [fixtures.farm] }));
  await page.route(`**/api/farms/${fixtures.farm.id}`, (route) => route.fulfill({ json: fixtures.farm }));
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto(`/farms/${fixtures.farm.id}`);
  await expect(page.getByRole("heading", { name: fixtures.farm.name })).toBeVisible();

  // The session "expires": the very next business request comes back
  // with the BFF's stable session_expired body.
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=all`, (route) =>
    route.fulfill({ status: 401, json: { error: "session_expired" } }),
  );

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Batches", exact: true }).click();

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
