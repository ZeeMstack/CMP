"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import type { PlatformTenantOnboardingCreate } from "@/lib/api/client";
import {
  DEFAULT_CREATE_TENANT_FORM_VALUES,
  buildPlatformTenantOnboardingPayload,
  createTenantFormSchema,
  type CreateTenantFormValues,
} from "@/lib/validation/platformTenant";

const inputClass =
  "min-h-11 w-full rounded-md border border-border-subtle bg-surface px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";
const labelClass = "block text-sm font-medium text-ink";
const hintClass = "block text-xs text-ink-muted";
const errorClass = "block text-xs text-red-700";

function Field({
  id, label, hint, error, children,
}: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={labelClass}>{label}</label>
      {hint && <span id={`${id}-hint`} className={hintClass}>{hint}</span>}
      {children}
      {error && <span id={`${id}-error`} role="alert" className={errorClass}>{error}</span>}
    </div>
  );
}

/** Two named describedby ids (hint/error) are joined only when both are
 * present -- avoids a stray leading/trailing space in the attribute and
 * keeps each field wired to exactly the descriptive text it actually has. */
function describedBy(id: string, hasHint: boolean, hasError: boolean): string | undefined {
  const ids = [hasHint ? `${id}-hint` : null, hasError ? `${id}-error` : null].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

export function CreateTenantForm({
  onSubmit, isSubmitting, serverError,
}: {
  onSubmit: (payload: PlatformTenantOnboardingCreate) => void;
  isSubmitting: boolean;
  serverError?: string | null;
}) {
  const [step, setStep] = useState<"configure" | "review">("configure");

  const {
    register, formState: { errors }, trigger, getValues,
  } = useForm<CreateTenantFormValues>({
    resolver: zodResolver(createTenantFormSchema),
    defaultValues: DEFAULT_CREATE_TENANT_FORM_VALUES,
    mode: "onBlur",
  });

  async function goToReview() {
    const valid = await trigger();
    if (valid) setStep("review");
  }

  function submitReview() {
    onSubmit(buildPlatformTenantOnboardingPayload(getValues()));
  }

  if (step === "review") {
    return (
      <div className="flex flex-col gap-4">
        <StepIndicator step="review" />
        <ReviewSummary values={getValues()} />
        {serverError && (
          <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {serverError}
          </p>
        )}
        <div className="flex gap-3">
          <Button type="button" variant="secondary" onClick={() => setStep("configure")} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="button" variant="primary" onClick={submitReview} disabled={isSubmitting}>
            {isSubmitting ? "Creating…" : "Create Tenant"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        goToReview();
      }}
      noValidate
      className="flex flex-col gap-6"
    >
      <StepIndicator step="configure" />

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Tenant identity</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="tenant-code" label="Tenant code" error={errors.tenantCode?.message}>
            <input
              id="tenant-code"
              aria-invalid={Boolean(errors.tenantCode)}
              aria-describedby={describedBy("tenant-code", false, Boolean(errors.tenantCode))}
              {...register("tenantCode")}
              className={inputClass}
              placeholder="ACME"
            />
          </Field>
          <Field id="tenant-name" label="Tenant name" error={errors.tenantName?.message}>
            <input
              id="tenant-name"
              aria-invalid={Boolean(errors.tenantName)}
              aria-describedby={describedBy("tenant-name", false, Boolean(errors.tenantName))}
              {...register("tenantName")}
              className={inputClass}
              placeholder="Acme Farms"
            />
          </Field>
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Initial Tenant Administrator</legend>
        <p className="text-xs text-ink-muted">
          CMP does not create or store a password for this administrator. Signing in will still require a matching,
          valid OIDC token from the identity provider below -- typing these values here does not verify them.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            id="admin-oidc-issuer"
            label="OIDC issuer"
            hint="Identity provider issuer that authenticates this administrator."
            error={errors.oidcIssuer?.message}
          >
            <input
              id="admin-oidc-issuer"
              aria-invalid={Boolean(errors.oidcIssuer)}
              aria-describedby={describedBy("admin-oidc-issuer", true, Boolean(errors.oidcIssuer))}
              {...register("oidcIssuer")}
              className={inputClass}
              placeholder="https://auth.example.com/"
            />
          </Field>
          <Field
            id="admin-oidc-subject"
            label="OIDC subject"
            hint="Unique identity subject supplied by the identity provider."
            error={errors.oidcSubject?.message}
          >
            <input
              id="admin-oidc-subject"
              aria-invalid={Boolean(errors.oidcSubject)}
              aria-describedby={describedBy("admin-oidc-subject", true, Boolean(errors.oidcSubject))}
              {...register("oidcSubject")}
              className={inputClass}
              placeholder="auth0|64f1a2b3c4d5"
            />
          </Field>
          <Field id="admin-email" label="Email" error={errors.email?.message}>
            <input
              id="admin-email"
              type="email"
              aria-invalid={Boolean(errors.email)}
              aria-describedby={describedBy("admin-email", false, Boolean(errors.email))}
              {...register("email")}
              className={inputClass}
              placeholder="admin@acmefarms.com"
            />
          </Field>
          <Field id="admin-display-name" label="Display name" error={errors.displayName?.message}>
            <input
              id="admin-display-name"
              aria-invalid={Boolean(errors.displayName)}
              aria-describedby={describedBy("admin-display-name", false, Boolean(errors.displayName))}
              {...register("displayName")}
              className={inputClass}
              placeholder="Jordan Alvarez"
            />
          </Field>
        </div>
      </fieldset>

      <div>
        <Button type="submit" variant="primary">
          Review
        </Button>
      </div>
    </form>
  );
}

function StepIndicator({ step }: { step: "configure" | "review" }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">
      Step {step === "configure" ? "1" : "2"} of 2 · {step === "configure" ? "Configure" : "Review"}
    </p>
  );
}

function ReviewSummary({ values }: { values: CreateTenantFormValues }) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface p-4">
      <h2 className="font-serif text-base font-semibold text-ink">Review before creating</h2>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">Tenant</h3>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-muted">Code</dt>
            <dd className="font-medium text-ink">{values.tenantCode}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Name</dt>
            <dd className="font-medium text-ink">{values.tenantName}</dd>
          </div>
        </dl>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
          Initial Tenant Administrator
        </h3>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-muted">Display name</dt>
            <dd className="font-medium text-ink">{values.displayName}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Email</dt>
            <dd className="font-medium text-ink">{values.email}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">OIDC issuer</dt>
            <dd className="font-medium text-ink">{values.oidcIssuer}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">OIDC subject</dt>
            <dd className="font-medium text-ink">{values.oidcSubject}</dd>
          </div>
        </dl>
      </div>

      <p className="rounded-md bg-brand-50 px-3 py-2 text-xs text-brand-800">
        Creating this Tenant will also resolve or create the OIDC-bound User above and establish an active
        tenant_admin Membership for it. You will not be added as a member of this Tenant.
      </p>
    </div>
  );
}
