import { expect, test } from "@playwright/test";

import { alphaFarm, betaFarm, bootstrapWithSelection, tenantBeta } from "./multi-tenant-fixtures";

/**
 * AUTH-001B2 multi-tenant E2E: proves a tenant switch cannot flash stale
 * data from the previous tenant. No real Auth0, no live FastAPI/dev DB --
 * every backend call is intercepted at the browser boundary, including
 * the BFF-owned /api/auth/bootstrap and /api/tenant/select endpoints.
 */
test("switching from Alpha to Beta never shows Alpha data after the switch begins, and lands on Beta data", async ({
  page,
}) => {
  let currentTenantId: string = "aaaaaaaa-0000-0000-0000-000000000001"; // tenantAlpha.id, starts selected

  await page.route("**/api/auth/bootstrap", (route) => route.fulfill({ json: bootstrapWithSelection(currentTenantId) }));

  await page.route("**/api/tenant/select", async (route) => {
    const body = route.request().postDataJSON() as { tenant_id: string };
    currentTenantId = body.tenant_id;
    await route.fulfill({ json: bootstrapWithSelection(currentTenantId) });
  });

  await page.route("**/api/farms", (route) => {
    const farm = currentTenantId === tenantBeta.id ? betaFarm : alphaFarm;
    return route.fulfill({ json: [farm] });
  });
  await page.route(`**/api/farms/${alphaFarm.id}`, (route) => route.fulfill({ json: alphaFarm }));
  await page.route(`**/api/farms/${betaFarm.id}`, (route) => route.fulfill({ json: betaFarm }));
  await page.route(`**/api/farms/${alphaFarm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/farms/${betaFarm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ json: [] }),
  );

  // Initial state: Alpha selected, exactly one farm -> auto-navigates
  // straight through to Alpha's farm Home.
  await page.goto("/farms");
  await expect(page).toHaveURL(`/farms/${alphaFarm.id}`);
  await expect(page.getByRole("heading", { name: "Alpha Farm" })).toBeVisible();
  await expect(page.getByText("Beta Farm")).toHaveCount(0);

  // Switch tenant via the AppShell TenantSelector.
  await page.getByRole("button", { name: "Alpha Tenant" }).click();
  await page.getByRole("option", { name: /Beta Tenant/ }).click();

  // The switch always returns to /farms, then auto-navigates through to
  // Beta's own (different) farm id -- never preserving Alpha's farm id
  // in the URL.
  await expect(page).toHaveURL(`/farms/${betaFarm.id}`);

  // The critical assertion: Alpha's farm name is not present anywhere on
  // the page once the switch has landed -- not as a flash, not as
  // leftover stale content.
  await expect(page.getByText("Alpha Farm")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Beta Farm" })).toBeVisible();
});
