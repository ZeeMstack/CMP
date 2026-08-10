import { expect, test } from "@playwright/test";

/**
 * Minimal AUTH-001B1 E2E coverage: the login page itself renders and
 * links into the SDK-owned /auth/login route. No real Auth0 tenant, no
 * external redirect is followed -- this only proves CMP's own login page
 * (app/login/page.tsx) is correct. Full "unauthenticated -> redirected to
 * /login" route gating is B3's job, not tested here.
 */
test("login page shows the CMP sign-in entry point", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "CMP" })).toBeVisible();
  await expect(page.getByText("Commercial Hydroponic Operations")).toBeVisible();

  const signIn = page.getByRole("link", { name: "Sign in" });
  await expect(signIn).toBeVisible();
  await expect(signIn).toHaveAttribute("href", "/auth/login");
});
