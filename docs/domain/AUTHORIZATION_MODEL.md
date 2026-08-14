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

| Domain permission | Primary endpoint(s) | Status |
|---|---|---|
| `farm.read` | `GET /farms/{farm_id}`, `GET /farms` | **Enforced** (AUTHZ-001A technical proof; `GET /farms` added in AUTHZ-001B1) |
| `farm.manage` | `POST /farms` | **Enforced** (AUTHZ-001A technical proof) |
| `location.read` | `GET /farms/{farm_id}/locations*` (tree, by id, children, path, occupant, subtree-occupancy) | **Enforced** (AUTHZ-001B1) |
| `location.manage` | `POST /farms/{farm_id}/locations`, `.../bulk-children` | **Enforced** (AUTHZ-001B2) |
| `asset.read` | `GET /farms/{farm_id}/assets*` | **Enforced** (AUTHZ-001B1) |
| `asset.manage` | `POST /farms/{farm_id}/assets`, `.../positions/generate` | **Enforced** (AUTHZ-001B2) |
| `carrier.read` | `GET /farms/{farm_id}/carriers*` | **Enforced** (AUTHZ-001B1) |
| `carrier.manage` | `POST /farms/{farm_id}/carriers`, `.../bulk` | **Enforced** (AUTHZ-001B2) |
| `movement.manage` | `POST /farms/{farm_id}/movements` (occupant relocation command) | **Enforced** (AUTHZ-001B2) |
| `crop.read` | `GET /crops`, `GET /crops/{id}`, `GET /crops/{id}/varieties*` | **Enforced** (AUTHZ-001B1) |
| `crop.manage` | `POST /crops`, `POST /crops/{id}/varieties` | **Enforced** (AUTHZ-001B2) |
| `production_system.read` | `GET /production-systems*` | **Enforced** (AUTHZ-001B1) |
| `production_system.manage` | `POST /production-systems` | **Enforced** (AUTHZ-001B2) |
| `workflow.read` | `GET /workflows*`, `.../versions/{id}` | **Enforced** (AUTHZ-001B1) |
| `workflow.manage` | `POST /workflows`, `.../versions`, `.../stages`, `.../transitions`, `.../publish` | **Enforced** (AUTHZ-001B2) |
| `crop_batch.read` | `GET /farms/{farm_id}/crop-batches*` (list, by id, operational-summary/context, current-stage, stage-history, stage-transitions/{id}) | **Enforced** (AUTHZ-001B1) |
| `crop_batch.manage` | `POST /farms/{farm_id}/crop-batches`, `.../stage-transitions` | **Enforced** (AUTHZ-001B2) |
| `batch_derivation.read` | `GET /farms/{farm_id}/batch-derivations/{id}`, `.../crop-batches/{id}/lineage` | **Enforced** (AUTHZ-001B1) |
| `batch_derivation.manage` | `POST .../crop-batches/{id}/split`, `POST /farms/{farm_id}/crop-batch-merges` | **Enforced** (AUTHZ-001B2) |
| `seed_lot.read` | `GET /farms/{farm_id}/seed-lots*` | **Enforced** (AUTHZ-001B1) |
| `seed_lot.manage` | `POST /farms/{farm_id}/seed-lots` | **Enforced** (AUTHZ-001B2) |
| `sowing.read` | `GET .../crop-batches/{id}/sowings*`, `.../carriers*`, `GET /farms/{farm_id}/carriers/{id}/batch-assignment` | **Enforced** (AUTHZ-001B1) |
| `sowing.manage` | `POST .../crop-batches/{id}/sowings` | **Enforced** (AUTHZ-001B2) |
| `transplant.read` | `GET .../crop-batches/{id}/transplants*` | **Enforced** (AUTHZ-001B1) |
| `transplant.manage` | `POST .../crop-batches/{id}/transplants` | **Enforced** (AUTHZ-001B2) |
| `observation.read` | `GET .../crop-batches/{id}/observations*`, `GET /observation-definitions*` | **Enforced** (AUTHZ-001B1). Deliberately still unified for both observation records and observation definitions — see "Observation permission split (AUTHZ-002B1)" below; no operational reason was found to split visibility. |
| `observation_entry.manage` | `POST .../crop-batches/{id}/observations` | **Enforced** (AUTHZ-001B2 as the former unified `observation.manage`; split into this permission by AUTHZ-002B1) |
| `observation_definition.manage` | `POST /observation-definitions` | **Enforced** (AUTHZ-001B2 as the former unified `observation.manage`; split into this permission by AUTHZ-002B1) |
| `quality_hold.read` | `GET .../crop-batches/{id}/quality-holds*` | **Enforced** (AUTHZ-001B1) |
| `quality_hold.manage` | `POST .../quality-holds`, `.../quality-holds/{id}/release` | **Enforced** (AUTHZ-001B2) — covers both placing *and* releasing a hold; see "Future hardening" below |
| `harvest.read` | `GET .../crop-batches/{id}/harvests*`, `GET /farms/{farm_id}/harvested-produce-lots*` (incl. ledger, balance) | **Enforced** (AUTHZ-001B1) |
| `harvest.manage` | `POST .../crop-batches/{id}/harvests` | **Enforced** (AUTHZ-001B2) |
| `packing.read` | `GET /farms/{farm_id}/packing-events*`, `GET .../finished-goods-lots*` (incl. ledger, balance) | **Enforced** (AUTHZ-001B1) |
| `packing.manage` | `POST /farms/{farm_id}/packing-events` | **Enforced** (AUTHZ-001B2) |
| `finished_goods_storage.read` | `GET .../finished-goods-lots/{id}/storage-movements`, `.../placements`, `GET .../locations/{id}/finished-goods-inventory` | **Enforced** (AUTHZ-001B1) |
| `finished_goods_storage.manage` | `POST /farms/{farm_id}/finished-goods-storage-movements` | **Enforced** (AUTHZ-001B2) |
| `dispatch.read` | `GET /farms/{farm_id}/dispatches*` | **Enforced** (AUTHZ-001B1) |
| `dispatch.manage` | `POST /farms/{farm_id}/dispatches` | **Enforced** (AUTHZ-001B2) |
| `recall.read` | `GET /farms/{farm_id}/recall-cases*` | **Enforced** (AUTHZ-001B1) |
| `recall.manage` | `POST /farms/{farm_id}/recall-cases`, `.../recall-cases/{id}/close` | **Enforced** (AUTHZ-001B2) — covers both opening *and* closing a case; see "Future hardening" below |
| `traceability.read` | `GET /farms/{farm_id}/traceability/*` (finished-goods-lot trace, crop-batch/produce-lot impact) | **Enforced** (AUTHZ-001B1) |
| `tenant.members.manage` | `POST /memberships` | **Enforced** (AUTHZ-001B2) |

Not permission-gated by design, unaffected by AUTHZ-001B1 or AUTHZ-001B2:

- `GET /` — inline service-info endpoint (`app.main.root`), no auth at all.
- `GET /auth/me` — tenant-**un**scoped by definition (its purpose is letting a caller discover which tenants it may select before any tenant context exists); uses `require_authenticated_principal`, not `require_tenant_context`, so no `role_code`/`TenantContext` exists yet at that point.
- `GET /health`, `GET /ready` — infrastructure probes, no auth at all.
- `POST /dev/bootstrap/tenants`, `POST /dev/bootstrap/users`, `POST /dev/bootstrap/memberships` — development-only, mounted only when `ENABLE_DEV_AUTH=true` (itself forbidden outside `ENV=development`, see `app.core.dev_auth.check_dev_auth_startup_invariant`); exist specifically to create a tenant, a user identity, and a tenant's *first* membership — each strictly before any membership (and therefore any permission) can exist for that tenant. These are the only mutation endpoints exempt from `require_permission`; every other mounted mutation/action route is enforced.

This exemption list is itself enforced, not just documented: `tests/test_authz_read_enforcement_architecture.py::test_exemption_list_is_exact_not_a_superset` (reads) and `tests/test_authz_mutation_enforcement_architecture.py::test_exemption_list_is_exact_not_a_superset` (mutations) each assert every entry still corresponds to a real mounted route, so a stale entry can't silently mask a future gap.

## Role policy

`app.core.permissions.ROLE_PERMISSIONS` — the single centralized mapping; no route or service compares `role_code` directly (enforced by `tests/test_authz_architecture.py`).

**AUTHZ-002B2 activated the Imperial Pilot role policy.** Every one of the 12 `APPROVED_ROLE_CODES` now has a real, explicit, non-empty (except where the policy genuinely intends zero mutation authority) grant — this is no longer "all non-admin roles have zero permissions." The source of truth for exactly what each role holds is `docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md`'s Matrix A ("Imperial Pilot"); this table summarizes it, but that document is authoritative if the two ever disagree.

| `role_code` | Permission count | Summary |
|---|---|---|
| `tenant_admin` | 42 (all) | Superuser |
| `farm_manager` | 25 (minimum-tier — no `dispatch.manage` backup, no `tenant.members.manage`) | Site infrastructure + full visibility + senior recall escalation |
| `head_grower` | 25 | Agronomic master data (crop/production-system/workflow/observation-definition) + batch lifecycle |
| `production_supervisor` | 24 | Floor execution oversight; no master-data configuration |
| `operator` | 16 | Restricted routine execution only |
| `storekeeper` | 6 | Seed-lot receiving only — see the policy document's storekeeper limitation |
| `qc_officer` | 19 | Observation entry, quality-hold place/release, cross-chain read visibility; no recall |
| `packing_supervisor` | 12 | Packing execution only |
| `cold_store_supervisor` | 11 | Finished-goods storage execution only |
| `dispatch_officer` | 11 | Dispatch execution only |
| `auditor` | 20 (all `*.read`) | Zero mutations — technically identical to `read_only` today (see the policy document's gap list) |
| `read_only` | 20 (all `*.read`) | Zero mutations |
| any other string / missing / blank | 0 | Deny by default, unchanged |

Every grant above is mechanically pinned by `tests/test_permissions.py`'s exact-set assertions (`EXPECTED_ROLE_GRANTS`, independently transcribed from the policy document, not re-derived from `ROLE_PERMISSIONS` itself) — a future accidental privilege change to any role fails that test immediately. External-Commercial-V1 hardening items the policy document itself defers (farm-scoped role assignment; quality-hold place/release split; recall open/close split; a general Input/Store module; an `audit.read` permission) are **not** implemented by this activation and remain open, tracked in that document's P1/P2 list.

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

`require_permission` was first wired into exactly two endpoints, chosen for having the simplest possible behavior and the strongest existing test coverage:

- `GET /farms/{farm_id}` → `Permission.FARM_READ`
- `POST /farms` → `Permission.FARM_MANAGE`

See `tests/test_authz_farm_proof.py` for the full behavioral matrix established here (tenant_admin allowed; a known, DB-approved role with no granted permissions is `403`; an unrecognized role_code is `403`; a cross-tenant farm is still `404`; unauthenticated is still `401`; a caller with no active tenant access is `403`, never reaching the permission check; the dev-auth identity path is subject to the exact same permission check as real bearer auth, never bypassing it). This matrix is what every subsequent rollout ticket (AUTHZ-001B1, and mutation/action enforcement in AUTHZ-001B2) is checked against.

## Read enforcement (AUTHZ-001B1)

Every tenant-scoped `GET` business endpoint is now gated by `require_permission(Permission.<domain>_READ)` — `GET /farms` (previously the one deliberate exception, left on plain `require_tenant_context` to keep the AUTHZ-001A proof minimal) is included. 73 endpoints across every domain in the permission catalog; see the catalog table above for the per-domain endpoint list, all now marked **Enforced**.

Every route continues to compose `require_permission` exactly as `app.core.permissions.require_permission`'s own contract describes — no route inspects `role_code`, email, or any Auth0 claim; no route performs its own membership lookup; no service-layer permission check was introduced. `require_permission` itself is unchanged from AUTHZ-001A/A.1 (`Permission`, `ROLE_PERMISSIONS`, `has_permission` are all untouched by AUTHZ-001B1).

Structural proof, not a hand-maintained checklist: `tests/test_authz_read_enforcement_architecture.py` walks the live, mounted FastAPI route table (`app.routes[*].dependant`) and fails immediately if any current or future tenant-scoped `GET` endpoint is missing `require_permission`, is gated by a non-`.read` permission, or still depends on bare `require_tenant_context` — there is no endpoint-name list to keep in sync by hand. `tests/test_authz_read_enforcement_http.py` adds representative HTTP-level behavioral coverage (zero-permission-role denial, same-user-different-tenant-role independence, cross-tenant `404`) across a cross-section of domains beyond the original farms proof slice.

**Mutation/action endpoints (create, update-via-command, domain actions) were unaffected by AUTHZ-001B1** — every `POST` endpoint outside the original `POST /farms` proof used plain `require_tenant_context` until **AUTHZ-001B2** (below).

## Mutation/action enforcement (AUTHZ-001B2)

Every tenant-scoped mutation/action endpoint is now gated by `require_permission(Permission.<domain>_MANAGE)`. CMP's API is, and has always been, append-only: a live route audit confirmed **zero** `PUT`/`PATCH`/`DELETE` endpoints exist anywhere — every mutation is a `POST`, either a simple create or a domain command (movement, stage transition, split/merge, quality-hold place/release, harvest/pack/dispatch, recall open/close). 34 tenant-scoped mutation routes across 20 router files are covered; see the catalog table above for the per-domain route list, all now marked **Enforced (AUTHZ-001B2)**. `POST /farms` (AUTHZ-001A's own technical proof) required no change — it was already `FARM_MANAGE`-gated and is simply one of the now-uniformly-enforced routes, not a special case.

Command/action endpoints are mapped to the domain that owns business authority, not inferred from the HTTP verb: e.g. a movement command is `movement.manage`, a quality-hold release is `quality_hold.manage` (the same permission as placing a hold — see "Future hardening" below), a recall case close is `recall.manage` (the same permission as opening a case). No mutation required inventing a new permission or splitting an existing one; every mutation mapped cleanly to exactly one existing `.manage` `Permission`.

`POST /memberships` (tenant-membership administration) is gated by `tenant.members.manage`, audited specifically for privilege-bootstrap risk: the caller's own membership and permission are fully resolved by `require_permission`/`require_tenant_context` *before* the route body runs, and the membership being created is always for a different `user_id` under the caller's own `tenant_id` — a caller can never grant themselves a tenant they don't already administer.

As with AUTHZ-001B1, every route continues to compose `require_permission` exactly as its own contract describes — no route inspects `role_code`, email, or any Auth0 claim; no route performs its own membership lookup; no service-layer permission check was introduced; no duplicate/bare `require_tenant_context` was left alongside `require_permission` on any route.

Structural proof: `tests/test_authz_mutation_enforcement_architecture.py` walks the live, mounted FastAPI route table and fails immediately if any current or future tenant-scoped mutation/action endpoint (of any HTTP method) is missing `require_permission`, is gated by a non-`.manage` permission, still depends on bare `require_tenant_context`, or if a defined `.manage` permission is never bound to any route. `tests/test_authz_mutation_enforcement_http.py` adds representative HTTP-level behavioral coverage across a cross-section of domains (location, movement, crop, production_system) beyond the farms proof slice: zero-permission-role denial, same-user-different-tenant-role independence, no/inactive-membership denial, cross-tenant `404` for a domain command, and two properties unique to mutations — a denied request produces **zero** domain side effects and **zero** audit-trail writes (verified by explicit before/after state checks, not just the response status code), and authorization is evaluated **before** any idempotency-record lookup: a caller who no longer holds the required permission cannot obtain a cached command result by replaying another caller's `client_command_id`, while an authorized caller's own exact-replay semantics remain unchanged.

### Future hardening: quality-hold and recall segregation of duty

`quality_hold.manage` governs both **placing** and **releasing** a hold; `recall.manage` governs both **opening** and **closing** a recall case. AUTHZ-001A first noted this; AUTHZ-001B2 deliberately did **not** split either permission or add any self-approval restriction (e.g. preventing the same user from placing and releasing the same hold) — no such segregation-of-duty policy is currently approved, and inventing one here would be a product/quality-policy decision, not a foundation-architecture one. If segregation of duty for these two commands is required, it needs its own explicitly-scoped ticket to (a) decide the policy, (b) potentially add `quality_hold.release`/`recall.close` permissions, and (c) decide whether enforcement is a permission split, a same-actor check, or both. **Not touched by AUTHZ-002B1** — this ticket only split the unrelated `observation.manage` permission (below); `quality_hold.manage`/`recall.manage` remain unsplit exactly as described here.

### Observation permission split (AUTHZ-002B1)

`observation.manage` previously covered two authority levels that `docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md` (AUTHZ-002A's role-policy design) identified as the sole P0 blocker before the Imperial pilot: recording a routine observation against an *existing* definition, and creating/configuring an `ObservationDefinition` (master/configuration data — the definition's `value_type`, `unit`, `target_scope`, and bounds are immutable once created, enforced by a DB trigger, so defining one is a materially different, rarer, higher-authority action than recording against one). A role that should only ever record (e.g. a floor operator) could not previously be granted that ability without *also* gaining the power to redefine what can be recorded tenant-wide — the two were inseparable.

AUTHZ-002B1 splits this cleanly into two `.manage` permissions, replacing `OBSERVATION_MANAGE`/`observation.manage` entirely (no alias, no backward-compatible dual grant): confirmed via repository-wide search that the old permission was never persisted to the database, never stored in configuration, and never referenced by `apps/web` — it existed only as an in-memory `Permission` enum member consulted by `require_permission` at request time, so a clean replacement carries no compatibility risk.

- `Permission.OBSERVATION_ENTRY_MANAGE` / `"observation_entry.manage"` → gates only `POST /farms/{farm_id}/crop-batches/{batch_id}/observations` (routine observation recording).
- `Permission.OBSERVATION_DEFINITION_MANAGE` / `"observation_definition.manage"` → gates only `POST /observation-definitions` (observation-definition configuration).
- `Permission.OBSERVATION_READ` / `"observation.read"` is **unchanged** — it remains the single shared read permission for both observation records and observation definitions. Audited specifically (ticket AUTHZ-002B1 §11): the approved role policy already grants broad observation visibility to every production/QC-adjacent role, and no distinct security boundary was found between "who may see a recorded value" and "who may see what can be recorded" — splitting reads here would be permission proliferation without a corresponding risk this ticket could identify, so it was not done.

**Critical distinction — permission-model change only, not an active role-policy change.** `ROLE_PERMISSIONS` is untouched by AUTHZ-002B1: `tenant_admin` automatically receives both new permissions (it is derived from every defined `Permission` value, a mechanism that predates and is unaffected by this split), and every other approved `role_code` — including `head_grower`, `production_supervisor`, `operator`, and `qc_officer`, all of which the approved design in `ROLE_PERMISSION_POLICY_PROPOSAL.md` intends to eventually grant `OBSERVATION_ENTRY_MANAGE` (and, for `head_grower` alone, also `OBSERVATION_DEFINITION_MANAGE`) — still resolves to the empty set today. The former P0 finding is **technically resolved** at the permission-model level (the two authorities can now be granted independently), but **no pilot staff can exercise either new permission yet**; activating the approved non-admin grants is AUTHZ-002B2's job, not this ticket's.

Structural proof: the same `tests/test_authz_mutation_enforcement_architecture.py` used throughout AUTHZ-001B2 re-verifies, unmodified, that every `.manage`-suffixed permission (now including both new observation permissions) is bound to at least one route, that `OBSERVATION_MANAGE` no longer exists anywhere in the mounted route table, and that no mutation route was left on bare `require_tenant_context`. `tests/test_authz_observation_permission_split_http.py` adds representative HTTP-level proof of the boundary itself: a caller granted only `OBSERVATION_ENTRY_MANAGE` may record but not define; a caller granted only `OBSERVATION_DEFINITION_MANAGE` may define but not record; a caller granted neither is denied both; `tenant_admin` may do both; and a denied call in each direction produces zero domain rows and zero audit-trail writes.

## What AUTHZ-001A / AUTHZ-001B1 / AUTHZ-001B2 deliberately do not do

- Does not assign any permission to any role other than `tenant_admin` — the non-admin role→permission matrix remains entirely undefined (zero permissions for every role but `tenant_admin`), deferred to a future role-policy ticket.
- Does not split `quality_hold.manage` or `recall.manage` into place/release or open/close, and does not add any self-approval restriction — see "Future hardening" above.
- Does not add a database permission/role table, a role editor, or any setup/role-management UI.
- Does not use Auth0 Organizations or Auth0 RBAC for CMP business authorization.
- Does not change the database schema (no migration in any of these tickets).
- Does not change frontend behavior (`apps/web` untouched).
