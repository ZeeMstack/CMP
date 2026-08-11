import { expect, test } from "@playwright/test";

/**
 * Minimal AUTH-001B1 E2E coverage (returnTo behavior covered separately
 * in route-access.spec.ts): the login page itself renders and links into
 * the SDK-owned /auth/login route. No real Auth0 tenant, no external
 * redirect is followed -- this only proves CMP's own login page
 * (app/login/page.tsx) is correct. Full "unauthenticated -> redirected to
 * /login" route gating is covered in route-access.spec.ts.
 *
 * AuthGate (AUTH-001B3) now wraps /login too, so a bootstrap mock is
 * required even for this minimal case -- without one, the unreachable
 * CMP_API_BASE_URL configured for this test harness would resolve to a
 * bootstrap "error" state instead of "unauthenticated".
 */
test("login page shows the CMP sign-in entry point", async ({ page }) => {
  await page.route("**/api/auth/bootstrap", (route) =>
    route.fulfill({ status: 401, json: { status: "unauthenticated", user: null, memberships: [], selectedTenantId: null } }),
  );

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "CMP" })).toBeVisible();
  await expect(page.getByText("Commercial Hydroponic Operations")).toBeVisible();

  const signIn = page.getByRole("link", { name: "Sign in" });
  await expect(signIn).toBeVisible();
  await expect(signIn).toHaveAttribute("href", "/auth/login?returnTo=%2Ffarms");
});
