import { expect, test } from "@playwright/test";

import * as fixtures from "./fixtures";

/**
 * Preferred FE-001 E2E path: Farm -> Home -> Locations -> Batches ->
 * Batch Detail -> History/Lineage/Quality.
 *
 * All backend calls are intercepted at the browser level with static
 * fixtures shaped like the real schemas -- this proves frontend
 * routing/rendering only. It never reaches the real FastAPI backend and
 * never seeds or mutates the development `cmp` database.
 */
test.beforeEach(async ({ page }) => {
  await page.route("**/api/farms", (route) => route.fulfill({ json: [fixtures.farm] }));
  await page.route(`**/api/farms/${fixtures.farm.id}`, (route) => route.fulfill({ json: fixtures.farm }));
  await page.route(`**/api/farms/${fixtures.farm.id}/locations/tree`, (route) =>
    route.fulfill({ json: fixtures.locationsTree }),
  );
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches`, (route) =>
    route.fulfill({ json: [fixtures.cropBatch] }),
  );
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${fixtures.cropBatch.id}`, (route) =>
    route.fulfill({ json: fixtures.cropBatch }),
  );
  await page.route(
    `**/api/farms/${fixtures.farm.id}/crop-batches/${fixtures.cropBatch.id}/stage-history`,
    (route) => route.fulfill({ json: fixtures.stageHistory }),
  );
  await page.route(`**/api/farms/${fixtures.farm.id}/crop-batches/${fixtures.cropBatch.id}/lineage`, (route) =>
    route.fulfill({ json: fixtures.lineage }),
  );
  await page.route(
    `**/api/farms/${fixtures.farm.id}/crop-batches/${fixtures.cropBatch.id}/quality-holds`,
    (route) => route.fulfill({ json: fixtures.qualityHolds }),
  );
});

test("pilot happy path: farm -> home -> locations -> batches -> batch detail", async ({ page }) => {
  await page.goto("/");

  // Single accessible farm -> redirected straight to its operational home.
  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}`);
  await expect(page.getByRole("heading", { name: fixtures.farm.name })).toBeVisible();
  await expect(page.getByText("Active batches")).toBeVisible();

  // Locations.
  await page.getByRole("link", { name: "Locations" }).first().click();
  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}/locations`);
  await expect(page.getByText("Greenhouse 1")).toBeVisible();
  await expect(page.getByText("Zone A")).toBeVisible();

  // Batches.
  await page.getByRole("link", { name: "Batches" }).first().click();
  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}/crop-batches`);
  await expect(page.getByRole("link", { name: fixtures.cropBatch.code })).toBeVisible();

  // Batch detail: Overview.
  await page.getByRole("link", { name: fixtures.cropBatch.code }).first().click();
  await expect(page).toHaveURL(`/farms/${fixtures.farm.id}/crop-batches/${fixtures.cropBatch.id}`);
  await expect(page.getByText("Lettuce — Iceberg")).toBeVisible();
  await expect(page.getByText("Growing")).toBeVisible();

  // History tab.
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByText(/entered/i)).toBeVisible();

  // Lineage tab -- this batch has no recorded parents/children.
  await page.getByRole("link", { name: "Lineage" }).click();
  await expect(page.getByText("No lineage recorded")).toBeVisible();

  // Quality tab -- no holds recorded.
  await page.getByRole("link", { name: "Quality" }).click();
  await expect(page.getByText("No quality holds")).toBeVisible();
});
