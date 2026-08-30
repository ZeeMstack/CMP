import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";
import NewPlatformTenantPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function fillAndReview() {
  fireEvent.change(screen.getByLabelText("Tenant code"), { target: { value: "ACME" } });
  fireEvent.change(screen.getByLabelText("Tenant name"), { target: { value: "Acme Farms" } });
  fireEvent.change(screen.getByLabelText("OIDC issuer"), { target: { value: "https://auth.example.com/" } });
  fireEvent.change(screen.getByLabelText("OIDC subject"), { target: { value: "auth0|abc123" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@acmefarms.com" } });
  fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Jordan Alvarez" } });
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
}

const SUCCESS_RESPONSE = {
  tenant: { id: "tenant-abc", code: "ACME", name: "Acme Farms", status: "active" },
  admin_user: {
    id: "user-1",
    oidc_issuer: "https://auth.example.com/",
    oidc_subject: "auth0|abc123",
    email: "admin@acmefarms.com",
    display_name: "Jordan Alvarez",
    status: "active",
  },
  admin_user_created: true,
  membership: { id: "mem-1", tenant_id: "tenant-abc", user_id: "user-1", status: "active", role_code: "tenant_admin" },
};

describe("NewPlatformTenantPage", () => {
  it("submits exactly one create mutation and renders a factual confirmation on success", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(SUCCESS_RESPONSE, 201));
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText("Tenant created. Initial Tenant Administrator established.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("ACME")).toBeInTheDocument();
    expect(screen.getByText("Jordan Alvarez")).toBeInTheDocument();
    expect(screen.getByText("admin@acmefarms.com")).toBeInTheDocument();
  });

  it("renders 'Newly created' when admin_user_created is true", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(SUCCESS_RESPONSE, 201)));
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText("Newly created")).toBeInTheDocument());
    expect(screen.queryByText("Existing user resolved")).not.toBeInTheDocument();
  });

  it("renders 'Existing user resolved' when admin_user_created is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ ...SUCCESS_RESPONSE, admin_user_created: false }, 201)),
    );
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText("Existing user resolved")).toBeInTheDocument());
    expect(screen.queryByText("Newly created")).not.toBeInTheDocument();
  });

  it("never implies the Platform Admin became a Tenant member, and never offers an 'Open Tenant' action into the operational workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(SUCCESS_RESPONSE, 201)));
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText(/You have not been added as a member of this Tenant/i)).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /open tenant/i })).not.toBeInTheDocument();
    // "View Tenant" only ever navigates to the platform metadata page, never into the Tenant's own operational workspace.
    expect(screen.getByRole("link", { name: "View Tenant" })).toHaveAttribute("href", "/admin/tenants/tenant-abc");
  });

  it("renders the specific duplicate-Tenant-code conflict from B2 on 409", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Tenant code already exists" }, 409)),
    );
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText("Tenant code already exists")).toBeInTheDocument());
    expect(screen.queryByText("Tenant created. Initial Tenant Administrator established.")).not.toBeInTheDocument();
  });

  it("renders the specific OIDC identity/email conflict from B2 on 409", async () => {
    const mismatchDetail =
      "resolved User for oidc_issuer='https://auth.example.com/' oidc_subject='auth0|abc123' already has email 'someone-else@example.com', which does not match the supplied 'admin@acmefarms.com' -- refusing to silently overwrite an existing identity's email";
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: mismatchDetail }, 409)));
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText(mismatchDetail)).toBeInTheDocument());
  });

  it("renders the platform-access-denied copy on a 403 from the create call itself", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Platform administrator authority required" }, 403)),
    );
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(screen.getByText("You do not have platform administrator access.")).toBeInTheDocument());
  });

  it("Create Another Tenant resets to a fresh, empty configure step", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(SUCCESS_RESPONSE, 201)));
    render(withQueryClient(<NewPlatformTenantPage />));

    fillAndReview();
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));
    await waitFor(() => expect(screen.getByText("Tenant created. Initial Tenant Administrator established.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Create Another Tenant" }));

    expect(screen.getByLabelText("Tenant code")).toHaveValue("");
    expect(screen.queryByText("Tenant created. Initial Tenant Administrator established.")).not.toBeInTheDocument();
  });
});
