import { expect, test } from "@playwright/test";

import * as fixtures from "./fixtures";

/**
 * Deterministic FE-002B E2E path: Farm -> Home -> Batches -> Batch Detail
 * (Overview/Quality/Origin & Splits) -> Locations. All backend calls are
 * intercepted at the browser level with static fixtures shaped like the
 * real schemas -- this proves frontend routing/rendering only. It never
 * reaches the real FastAPI backend and never seeds or mutates the
 * development `cmp` database.
 */
test.beforeEach(async ({ page }) => {
  await page.route("**/api/farms", (route) => route.fulfill({ json: [fixtures.farm] }));
  await page.route(`**/api/farms/${fixtures.farm.id}`, (route) => route.fulfill({ json: fixtures.farm }));
  await page.route(`**/api/farms/${fixtures.farm.id}/locations/tree`, (route) =>
    route.fulfill({ json: fixtures.locationsTree }),
  );

  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=active`, (route) =>
    route.fulfill({ json: fixtures.operationalSummaryActive }),
  );
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/operational-summary?state=all`, (route) =>
    route.fulfill({ json: fixtures.operationalSummaryAll }),
  );

  for (const batch of Object.values(fixtures.batchesById)) {
    await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${batch.id}`, (route) =>
      route.fulfill({ json: fixtures.cropBatchDetail(batch) }),
    );
    await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${batch.id}/operational-context`, (route) =>
      route.fulfill({ json: batch }),
    );
    await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${batch.id}/stage-history`, (route) =>
      route.fulfill({ json: fixtures.stageHistoryFor(batch) }),
    );
    await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${batch.id}/lineage`, (route) =>
      route.fulfill({ json: fixtures.lineageByBatchId[batch.id] }),
    );
    await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${batch.id}/quality-holds`, (route) =>
      route.fulfill({ json: fixtures.qualityHoldsByBatchId[batch.id] }),
    );
  }

  for (const [rootId, response] of Object.entries(fixtures.subtreeOccupancyByRootId)) {
    await page.route(`**/api/farms/${fixtures.farm.id}/locations/${rootId}/subtree-occupancy`, (route) =>
      route.fulfill({ json: response }),
    );
  }
});

test("Home shows active/harvest-ready/open-hold KPIs without superseded inflation", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}`);
  await expect(page.getByRole("heading", { name: fixtures.farm.name })).toBeVisible();

  // 3 active batches (LOT-006, LOT-007A, LOT-007B) -- LOT-007 (superseded)
  // must never be counted here.
  const activeCard = page.getByRole("link", { name: /Active batches/ });
  await expect(activeCard).toBeVisible();
  await expect(activeCard.getByText("3", { exact: true })).toBeVisible();

  // 2 harvest-ready batches (007A, 007B), by authoritative stage_category.
  const harvestReadyCard = page.getByRole("link", { name: /Harvest ready/ });
  await expect(harvestReadyCard).toBeVisible();
  await expect(harvestReadyCard.getByText("2", { exact: true })).toBeVisible();

  await expect(page.getByText("Batches with open quality holds")).toBeVisible();
});

test("Batch List shows placement and an unmistakable on-hold badge, and the superseded split parent in the register", async ({ page }) => {
  await page.goto(`/farms/${fixtures.farm.id}/crop-batches`);
  await expect(page.getByRole("link", { name: "LOT-006", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "LOT-007", exact: true })).toBeVisible();

  await expect(page.getByText("On hold").first()).toBeVisible();
  await expect(page.getByText(/Greenhouse 01 \/ Zone A/).first()).toBeVisible();
});

test("LOT-006 Overview shows the open-hold banner immediately, placement, and sowing date/age; Quality tab humanizes the reason", async ({ page }) => {
  await page.goto(`/farms/${fixtures.farm.id}/crop-batches/${fixtures.lot006.id}`);
  await expect(page.getByText("Quality hold", { exact: true })).toBeVisible();
  await expect(page.getByText("This batch currently has 1 open quality hold.")).toBeVisible();
  await expect(page.getByText(/Greenhouse 01 \/ Zone A/)).toBeVisible();
  await expect(page.getByText(/08 Jun 2026/)).toBeVisible();

  await page.getByRole("navigation", { name: "Batch detail sections" }).getByRole("link", { name: "Quality" }).click();
  await expect(page.getByText("Nutrient deficiency")).toBeVisible();
});

test("LOT-007 Origin & Splits explains the split into LOT-007A/007B", async ({ page }) => {
  await page.goto(`/farms/${fixtures.farm.id}/crop-batches/${fixtures.lot007.id}`);
  await page.getByRole("navigation", { name: "Batch detail sections" }).getByRole("link", { name: "Origin & Splits" }).click();
  await expect(page.getByText("This batch was split into:")).toBeVisible();
  await expect(page.getByRole("link", { name: "LOT-007A" })).toBeVisible();
  await expect(page.getByRole("link", { name: "LOT-007B" })).toBeVisible();
});

test("LOT-007A inherits its sowing origin/age from the split parent", async ({ page }) => {
  await page.goto(`/farms/${fixtures.farm.id}/crop-batches/${fixtures.lot007a.id}`);
  await expect(page.getByText(/18 May 2026/)).toBeVisible();
});

test("Locations shows aggregate occupancy on expand with no per-position Check occupancy click required", async ({ page }) => {
  await page.goto(`/farms/${fixtures.farm.id}/locations`);
  await expect(page.getByText("Greenhouse 01")).toBeVisible();
  await expect(page.getByText("1 / 2 occupied").first()).toBeVisible();

  await expect(page.getByRole("button", { name: /check occupancy/i })).toHaveCount(0);

  await page.getByRole("button", { name: /expand zone a/i }).first().click();
  await expect(page.getByText("LOT-006")).toBeVisible();
});
