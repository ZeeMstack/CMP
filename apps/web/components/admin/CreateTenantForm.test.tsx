import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreateTenantForm } from "./CreateTenantForm";

function fillConfigureStep() {
  fireEvent.change(screen.getByLabelText("Tenant code"), { target: { value: "ACME" } });
  fireEvent.change(screen.getByLabelText("Tenant name"), { target: { value: "Acme Farms" } });
  fireEvent.change(screen.getByLabelText("OIDC issuer"), { target: { value: "https://auth.example.com/" } });
  fireEvent.change(screen.getByLabelText("OIDC subject"), { target: { value: "auth0|abc123" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@acmefarms.com" } });
  fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Jordan Alvarez" } });
}

describe("CreateTenantForm", () => {
  it("renders exactly the B2 contract fields, grouped into Tenant identity and Initial Tenant Administrator", () => {
    render(<CreateTenantForm onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByText("Tenant identity")).toBeInTheDocument();
    expect(screen.getByText("Initial Tenant Administrator")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenant code")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenant name")).toBeInTheDocument();
    expect(screen.getByLabelText("OIDC issuer")).toBeInTheDocument();
    expect(screen.getByLabelText("OIDC subject")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toBeInTheDocument();
  });

  it("never renders a password field or mentions a password/username-password flow", () => {
    const { container } = render(<CreateTenantForm onSubmit={vi.fn()} isSubmitting={false} />);
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.getByText(/does not create or store a password/i)).toBeInTheDocument();
  });

  it("explains the OIDC issuer/subject fields without claiming the identity is verified", () => {
    render(<CreateTenantForm onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByText(/Identity provider issuer that authenticates this administrator/i)).toBeInTheDocument();
    expect(screen.getByText(/Unique identity subject supplied by the identity provider/i)).toBeInTheDocument();
    expect(screen.getByText(/typing these values here does not verify them/i)).toBeInTheDocument();
  });

  it("blocks moving to review when required fields are blank", async () => {
    render(<CreateTenantForm onSubmit={vi.fn()} isSubmitting={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Tenant code is required")).toBeInTheDocument());
    expect(screen.queryByText("Review before creating")).not.toBeInTheDocument();
  });

  it("shows a review step with both the Tenant and Initial Tenant Administrator facts, and does not submit until confirmed", async () => {
    const onSubmit = vi.fn();
    render(<CreateTenantForm onSubmit={onSubmit} isSubmitting={false} />);
    fillConfigureStep();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());
    expect(screen.getByText("ACME")).toBeInTheDocument();
    expect(screen.getByText("Acme Farms")).toBeInTheDocument();
    expect(screen.getByText("Jordan Alvarez")).toBeInTheDocument();
    expect(screen.getByText("admin@acmefarms.com")).toBeInTheDocument();
    expect(screen.getByText(/will also resolve or create the OIDC-bound User/i)).toBeInTheDocument();
    expect(screen.getByText(/You will not be added as a member of this Tenant/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits exactly once, with exactly the B2 request shape, when Create Tenant is clicked on review", async () => {
    const onSubmit = vi.fn();
    render(<CreateTenantForm onSubmit={onSubmit} isSubmitting={false} />);
    fillConfigureStep();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Create Tenant" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual({
      tenant: { code: "ACME", name: "Acme Farms" },
      initial_admin: {
        oidc_issuer: "https://auth.example.com/",
        oidc_subject: "auth0|abc123",
        email: "admin@acmefarms.com",
        display_name: "Jordan Alvarez",
      },
    });
  });

  it("disables the Create Tenant action while isSubmitting, preventing a second submission", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<CreateTenantForm onSubmit={onSubmit} isSubmitting={false} />);
    fillConfigureStep();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());

    rerender(<CreateTenantForm onSubmit={onSubmit} isSubmitting />);
    expect(screen.getByRole("button", { name: /Creating/i })).toBeDisabled();
  });

  it("returns to the configure step from review via Back, without submitting", async () => {
    const onSubmit = vi.fn();
    render(<CreateTenantForm onSubmit={onSubmit} isSubmitting={false} />);
    fillConfigureStep();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before creating")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Tenant code")).toHaveValue("ACME");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a server-supplied conflict message verbatim on the review step", async () => {
    render(
      <CreateTenantForm onSubmit={vi.fn()} isSubmitting={false} serverError="Tenant code already exists" />,
    );
    fillConfigureStep();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Tenant code already exists")).toBeInTheDocument());
  });
});
