# Authorization Model

Full detail: `CLAUDE.md` rules 2 and 11 ("Tenant isolation", "Security"); `MULTI_TENANCY.md`; the AUTHZ-001A ticket. This document summarizes the approved approach and records the current enforcement inventory; it does not restate ticket rationale.

## Layered trust model

Authentication and authorization are deliberately separate concerns, resolved in strict order. Each layer only ever consumes the layer below it — never skips ahead, never re-derives a fact a lower layer already proved:

1. **Authentication — Auth0.** Auth0 (OIDC) proves *who is making the request* and issues a bearer access token for the CMP API's own resource audience (never an ID token). CMP's backend verifies that token itself (`app.core.oidc`) — signature, issuer, audience, expiry, algorithm allowlist — entirely independent of any Auth0-side role, permission, or organization concept. Auth0 has no notion of CMP tenants, memberships, or roles, and nothing downstream of verification ever inspects an Auth0 claim other than `iss`/`sub` (and optionally `email`/`email_verified`, carried only for display, never for authorization — see `AuthenticatedIdentity` in `app.core.oidc`).
2. **Identity binding — exact issuer + subject.** A verified `(issuer, subject)` pair is looked up against `users.oidc_issuer`/`users.oidc_subject` (`app.core.auth._resolve_cmp_user_for_identity`). No email-based auto-linking exists or is planned here — a token whose issuer+subject has no matching active CMP user is a `403`, not an automatic account match.
3. **Tenant access — CMP active membership.** A resolved CMP user only gains access to a specific tenant by way of an **active** `tenant_memberships` row for `(tenant_id, user_id)` (`app.services.membership_service.get_active_membership`, consumed by `app.core.auth.require_tenant_context`/`app.core.dev_auth.resolve_dev_tenant_context`). A removed membership, an inactive tenant, or no membership at all is an authentication/tenant-context failure (`401`), never merely "no permissions."
4. **Role — `tenant_memberships.role_code`.** The one and only role signal. Constrained at the database layer to `app.models.membership.APPROVED_ROLE_CODES`; CMP never reads a role from anywhere else (not Auth0 custom claims, not a request header value that wasn't independently verified against the database).
5. **Authorization — CMP role → permission policy (AUTHZ-001A).** `app.core.permissions.ROLE_PERMISSIONS` maps `role_code` to a set of CMP-domain `Permission` values. `app.core.permissions.require_permission(permission)` is a FastAPI dependency built strictly on top of `require_tenant_context` — it never bypasses or duplicates tenant/membership resolution, it only adds one more check once a `TenantContext` already exists.
6. **Resource isolation — tenant filter + 404 concealment.** Independent of and in addition to the permission check: every resource-by-id lookup filters by `tenant_id` (and `farm_id`/parent id where nested) and raises a domain "not found" error on a miss, mapped to a generic `404`. A permission grant never implies visibility into another tenant's data — see "Error semantics" below.

Auth0 dashboard roles, Auth0 RBAC, and Auth0 Organizations are not used for CMP business authorization and are not referenced anywhere in this model (`app.core.permissions` imports nothing Auth0-shaped — enforced by `tests/test_authz_architecture.py`). Authorization decisions are made entirely server-side, on every request, from the database's current membership/role state; nothing about the policy or a caller's specific permissions is ever exposed to browser-side bearer handling.

## Permission catalog

Stable, dotted `<domain>.read` / `<domain>.manage` strings (`app.core.permissions.Permission`), derived from a full endpoint audit — not the ticket's own illustrative example list. `manage` covers every mutation/command in that domain: CMP has no `PUT`/`PATCH`/`DELETE` endpoints anywhere (every mutation is an append-only `POST` — a create or a domain command), so a narrower per-verb split was not justified by current behavior. A handful of domains have only one tier where the endpoint audit gave no reason for the other (no read-only domain has a `.manage` value it doesn't need; `movement` and `tenant.members` currently have no standalone read endpoint; `traceability` has no mutation endpoint at all).

Unknown permission values cannot silently succeed: `Permission` is a closed `StrEnum`, and `require_permission` only ever accepts a member of it — there is no free-text permission string anywhere in a route.

| Domain permission | Primary endpoint(s) | AUTHZ-001A status |
|---|---|---|
| `farm.read` | `GET /farms/{farm_id}` | **Enforced** (technical proof) |
| `farm.manage` | `POST /farms` | **Enforced** (technical proof) |
| `location.read` | `GET /farms/{farm_id}/locations*` (tree, by id, children, path, occupant, subtree-occupancy) | Planned (AUTHZ-001B) |
| `location.manage` | `POST /farms/{farm_id}/locations`, `.../bulk-children` | Planned |
| `asset.read` | `GET /farms/{farm_id}/assets*` | Planned |
| `asset.manage` | `POST /farms/{farm_id}/assets`, `.../positions/generate` | Planned |
| `carrier.read` | `GET /farms/{farm_id}/carriers*` | Planned |
| `carrier.manage` | `POST /farms/{farm_id}/carriers`, `.../bulk` | Planned |
| `movement.manage` | `POST /farms/{farm_id}/movements` (occupant relocation command) | Planned |
| `crop.read` | `GET /crops`, `GET /crops/{id}`, `GET /crops/{id}/varieties*` | Planned |
| `crop.manage` | `POST /crops`, `POST /crops/{id}/varieties` | Planned |
| `production_system.read` | `GET /production-systems*` | Planned |
| `production_system.manage` | `POST /production-systems` | Planned |
| `workflow.read` | `GET /workflows*`, `.../versions/{id}` | Planned |
| `workflow.manage` | `POST /workflows`, `.../versions`, `.../stages`, `.../transitions`, `.../publish` | Planned |
| `crop_batch.read` | `GET /farms/{farm_id}/crop-batches*` (list, by id, operational-summary/context, current-stage, stage-history, stage-transitions/{id}) | Planned |
| `crop_batch.manage` | `POST /farms/{farm_id}/crop-batches`, `.../stage-transitions` | Planned |
| `batch_derivation.read` | `GET /farms/{farm_id}/batch-derivations/{id}`, `.../crop-batches/{id}/lineage` | Planned |
| `batch_derivation.manage` | `POST .../crop-batches/{id}/split`, `POST /farms/{farm_id}/crop-batch-merges` | Planned |
| `seed_lot.read` | `GET /farms/{farm_id}/seed-lots*` | Planned |
| `seed_lot.manage` | `POST /farms/{farm_id}/seed-lots` | Planned |
| `sowing.read` | `GET .../crop-batches/{id}/sowings*`, `.../carriers*`, `GET /farms/{farm_id}/carriers/{id}/batch-assignment` | Planned |
| `sowing.manage` | `POST .../crop-batches/{id}/sowings` | Planned |
| `transplant.read` | `GET .../crop-batches/{id}/transplants*` | Planned |
| `transplant.manage` | `POST .../crop-batches/{id}/transplants` | Planned |
| `observation.read` | `GET .../crop-batches/{id}/observations*`, `GET /observation-definitions*` | Planned |
| `observation.manage` | `POST .../crop-batches/{id}/observations`, `POST /observation-definitions` | Planned |
| `quality_hold.read` | `GET .../crop-batches/{id}/quality-holds*` | Planned |
| `quality_hold.manage` | `POST .../quality-holds`, `.../quality-holds/{id}/release` | Planned |
| `harvest.read` | `GET .../crop-batches/{id}/harvests*`, `GET /farms/{farm_id}/harvested-produce-lots*` (incl. ledger, balance) | Planned |
| `harvest.manage` | `POST .../crop-batches/{id}/harvests` | Planned |
| `packing.read` | `GET /farms/{farm_id}/packing-events*`, `GET .../finished-goods-lots*` (incl. ledger, balance) | Planned |
| `packing.manage` | `POST /farms/{farm_id}/packing-events` | Planned |
| `finished_goods_storage.read` | `GET .../finished-goods-lots/{id}/storage-movements`, `.../placements`, `GET .../locations/{id}/finished-goods-inventory` | Planned |
| `finished_goods_storage.manage` | `POST /farms/{farm_id}/finished-goods-storage-movements` | Planned |
| `dispatch.read` | `GET /farms/{farm_id}/dispatches*` | Planned |
| `dispatch.manage` | `POST /farms/{farm_id}/dispatches` | Planned |
| `recall.read` | `GET /farms/{farm_id}/recall-cases*` | Planned |
| `recall.manage` | `POST /farms/{farm_id}/recall-cases`, `.../recall-cases/{id}/close` | Planned |
| `traceability.read` | `GET /farms/{farm_id}/traceability/*` (finished-goods-lot trace, crop-batch/produce-lot impact) | Planned |
| `tenant.members.manage` | `POST /memberships` | Planned |

Not permission-gated by design, unaffected by this ticket:

- `GET /auth/me` — tenant-**un**scoped by definition (its purpose is letting a caller discover which tenants it may select before any tenant context exists); uses `require_authenticated_principal`, not `require_tenant_context`, so no `role_code`/`TenantContext` exists yet at that point.
- `GET /health`, `GET /ready` — infrastructure probes, no auth at all.
- `POST /dev/bootstrap/*` — development-only, mounted only when `ENABLE_DEV_AUTH=true` (itself forbidden outside `ENV=development`, see `app.core.dev_auth.check_dev_auth_startup_invariant`); exists specifically to create a tenant's *first* membership before any membership can exist.

## Role policy

`app.core.permissions.ROLE_PERMISSIONS` — the single centralized mapping; no route or service compares `role_code` directly (enforced by `tests/test_authz_architecture.py`).

| `role_code` | Permissions granted (AUTHZ-001A) |
|---|---|
| `tenant_admin` | **All** currently-defined `Permission` values |
| `farm_manager`, `head_grower`, `production_supervisor`, `operator`, `storekeeper`, `qc_officer`, `auditor`, `packing_supervisor`, `cold_store_supervisor`, `dispatch_officer`, `read_only` | **None** (deny by default) |
| any other string (including a future role_code added to `APPROVED_ROLE_CODES` before this policy is updated) | **None** (deny by default) |
| missing/blank | **None** |

Every role other than `tenant_admin` has real precedent as an authenticatable role in this codebase's fixtures/tests, but **no source or product document defines what any of them may specifically do** (`docs/CMP_MASTER_SPEC.md` §11 lists role *names* only — "typical roles: tenant admin, facility manager, head grower, storekeeper, supervisor, operator, QC, auditor, packing/cold-store/dispatch users, and read-only management" — with no per-role authority beyond "backend permissions and farm access apply to all commands"). Inventing a permission set for any of them would be a product decision, not a foundation-architecture one. They are deliberately left unmapped rather than guessed at, which — via `get_permissions_for_role`'s deny-by-default lookup — grants them zero permissions today. Assigning real permission sets to these roles (most plausibly at least `read_only` → the `*.read` tier, and role-specific `*.manage` grants for the production-floor roles) is deferred to **AUTHZ-001B**, pending an explicit product decision on each role's intended authority.

## Error semantics

Unchanged from pre-AUTHZ-001A except where this section says otherwise:

| Condition | Status |
|---|---|
| No/invalid bearer; dev auth disabled; dev headers present but the claimed dev user id doesn't resolve to a real, active CMP user | `401` (unchanged — an authentication failure: is this a usable identity at all?) |
| Valid bearer/dev identity, but the tenant selector is malformed or missing (real mode: no `X-CMP-Tenant-Id`; dev mode: incomplete dev headers) | `400`/`401` per the existing `require_tenant_context` behavior (unchanged) |
| Valid identity (real bearer or dev), but the selected tenant is inactive, or the caller has no active membership for it (missing entirely, or present but removed/inactive) | **`403`** — a tenant-access failure: identity is valid, but this identity has no access to the selected tenant. Real bearer: `require_tenant_context`'s own inline checks (unchanged, pre-dates AUTHZ-001A; see `tests/test_auth_context.py::test_removed_membership_is_403`, `::test_inactive_tenant_is_403`). Dev-auth: `app.core.dev_auth.resolve_dev_tenant_context`'s equivalent checks (aligned to 403 in **AUTH-001D**; previously 401 — see `tests/test_authz_farm_proof.py`'s dev-auth tenant-access tests) |
| Active membership exists, but `role_code`'s permission set does not include the permission the route requires | **`403`** (new: `require_permission`) — generic `"You don't have permission to perform this action"`; never names the missing permission, the caller's role, or any other policy detail |
| Fully authorized caller requests a resource that exists but belongs to a different tenant | **`404`** (unchanged) — a permission grant is never sufficient by itself; the resource must also resolve under the caller's own `tenant_id` |

Real bearer and dev-auth now agree on every row above: authentication answers "is this a usable identity?" (`401` only), tenant access answers "may this identity reach the selected tenant?" (`403`), authorization answers "may this active tenant member perform this action?" (`403`), and resource isolation answers "does this resource exist inside the authorized tenant?" (`404`). Cross-tenant concealment is never converted into a `403` — a resource in a tenant the caller can't see must remain indistinguishable from a resource that doesn't exist at all, regardless of what the caller is permitted to do in their *own* tenant.

## Technical proof (AUTHZ-001A)

`require_permission` is wired into exactly two endpoints, chosen for having the simplest possible behavior and the strongest existing test coverage:

- `GET /farms/{farm_id}` → `Permission.FARM_READ`
- `POST /farms` → `Permission.FARM_MANAGE`

`GET /farms` (list) intentionally remains on the plain `require_tenant_context` dependency — the proof is deliberately not expanded beyond the two endpoints above. See `tests/test_authz_farm_proof.py` for the full behavioral matrix (tenant_admin allowed; a known, DB-approved role with no granted permissions is `403`; an unrecognized role_code is `403`; a cross-tenant farm is still `404`; unauthenticated is still `401`; an inactive membership is still `401`, never reaching the permission check; the dev-auth identity path is subject to the exact same permission check as real bearer auth, never bypassing it).

## What AUTHZ-001A deliberately does not do

- Does not retrofit permission checks onto any endpoint outside the two-endpoint technical proof.
- Does not assign any permission to any role other than `tenant_admin`.
- Does not add a database permission/role table, a role editor, or any setup/role-management UI.
- Does not use Auth0 Organizations or Auth0 RBAC for CMP business authorization.
- Does not change the database schema (no migration in this ticket).
- Does not change frontend behavior (`apps/web` untouched).
