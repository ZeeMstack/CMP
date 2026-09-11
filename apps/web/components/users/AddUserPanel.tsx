"use client";

import { useState } from "react";

import { RoleField } from "@/components/users/RoleField";
import { Button } from "@/components/ui/Button";
import type { RoleOption, UserLookupRead } from "@/lib/api/client";
import { AppError } from "@/lib/errors/adapter";
import { useLookupUserByEmail } from "@/lib/query/hooks";

const inputClass =
  "min-h-11 w-full rounded-md border border-wl-border bg-wl-surface-raised px-3 text-sm text-wl-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

/** AUTHZ-OPS-001 section 7/8/23: "Add Existing User". CMP has no
 * self-service signup and no invitation mechanism -- a Tenant Admin can
 * only attach an ALREADY-provisioned CMP identity to their tenant (see
 * `docs/domain/AUTHORIZATION_MODEL.md`, "Identity binding"). This panel
 * makes that limitation explicit rather than pretending an invitation was
 * sent: the admin must first resolve the email to a real CMP user via
 * `GET /users/lookup`, and only then may pick a role and submit. */
export function AddUserPanel({
  roles,
  onCancel,
  onSubmit,
  isSubmitting,
  serverError,
}: {
  roles: RoleOption[];
  onCancel: () => void;
  onSubmit: (payload: { userId: string; roleCode: string }) => void;
  isSubmitting: boolean;
  serverError: string | null;
}) {
  const [email, setEmail] = useState("");
  const [foundUser, setFoundUser] = useState<UserLookupRead | null>(null);
  const [lookupIssueMessage, setLookupIssueMessage] = useState<string | null>(null);
  const [roleCode, setRoleCode] = useState("");
  const lookup = useLookupUserByEmail();

  function handleCheck() {
    const trimmed = email.trim();
    if (!trimmed) return;
    setFoundUser(null);
    setLookupIssueMessage(null);
    lookup.mutate(trimmed, {
      onSuccess: (user) => setFoundUser(user),
      onError: (error) => {
        // Both the "not provisioned yet" (404) and "ambiguous identity"
        // (409) cases carry a truthful, safe-to-display backend message --
        // shown verbatim rather than re-worded, so the admin sees exactly
        // what GrowCMP found (or didn't). Only a genuinely unexpected
        // failure (network error, 5xx) falls back to generic wording.
        if (error instanceof AppError && (error.kind === "not_found" || error.kind === "conflict")) {
          setLookupIssueMessage(error.message);
        } else {
          setLookupIssueMessage("Could not check this email right now. Please try again.");
        }
      },
    });
  }

  function handleEmailChange(value: string) {
    setEmail(value);
    // Any edit to the email invalidates a previous lookup result -- never
    // let a stale "found" state be added under a since-changed address.
    setFoundUser(null);
    setLookupIssueMessage(null);
  }

  function handleSubmit() {
    if (!foundUser || !roleCode) return;
    onSubmit({ userId: foundUser.id, roleCode });
  }

  return (
    <div className="mb-6 flex flex-col gap-4 rounded-xl border border-wl-border bg-wl-surface-raised p-5">
      <h2 className="text-sm font-semibold text-wl-text">Add User</h2>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="add-user-email" className="text-xs font-medium uppercase tracking-wide text-wl-text-tertiary">
          Email
        </label>
        <div className="flex gap-2">
          <input
            id="add-user-email"
            type="email"
            className={inputClass}
            placeholder="user@example.com"
            value={email}
            onChange={(e) => handleEmailChange(e.target.value)}
          />
          <Button onClick={handleCheck} disabled={!email.trim() || lookup.isPending}>
            {lookup.isPending ? "Checking…" : "Check"}
          </Button>
        </div>
        {foundUser && (
          <p className="text-sm text-wl-grow-fg">
            Found: {foundUser.display_name} ({foundUser.email})
          </p>
        )}
        {lookupIssueMessage && <p className="text-sm text-wl-hold-fg">{lookupIssueMessage}</p>}
      </div>

      <RoleField roles={roles} value={roleCode} onChange={setRoleCode} disabled={!foundUser} />

      {serverError && <p className="text-sm text-danger-700">{serverError}</p>}

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={!foundUser || !roleCode || isSubmitting}>
          {isSubmitting ? "Adding…" : "Add User"}
        </Button>
      </div>
    </div>
  );
}
