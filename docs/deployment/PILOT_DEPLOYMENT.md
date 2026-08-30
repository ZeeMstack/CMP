# Pilot Deployment

Read this for pilot/production deployment configuration and the first-platform-admin bootstrap procedure. Permanent coding rules are in the root `CLAUDE.md`; the approved deployment architecture is DigitalOcean (one application VPS, DigitalOcean Managed PostgreSQL, Docker Compose runtime, Caddy reverse proxy/TLS, one public CMP hostname, Auth0 production authentication, manual controlled deployments). This document is the **environment/configuration contract and admin-bootstrap procedure only** (DEPLOY-001A) — it is not yet the full server-provisioning guide. Container packaging (`Dockerfile`s, `compose.prod.yaml`, `Caddyfile`), CI/CD, and actual DigitalOcean/Auth0/DNS provisioning are later DEPLOY slices.

## Environments

| Environment | Database | Auth | Notes |
|---|---|---|---|
| **Local Dev** | Local `docker compose` Postgres (`cmp` DB), unauthenticated on localhost | `ENABLE_DEV_AUTH=true` (backend) / `CMP_DEV_AUTH_BYPASS=true` (frontend) | Never reachable from outside the developer's machine; never a production credential |
| **Test** | Local `docker compose` Postgres, separate `cmp_test` database, migrated by the test suite via `tests/conftest.py`'s `migrations_alembic_config()` | Backend: `db_session`/`test_engine` fixtures against `cmp_test` directly. Frontend (Playwright): `CMP_TEST_AUTH_BYPASS=playwright-e2e-only` against a `next build && next start` (`NODE_ENV=production`) instance | `TEST_DATABASE_URL` is read only by the test suite, never by the running app |
| **Pilot/Production** | DigitalOcean Managed PostgreSQL, TLS-required | `ENABLE_DEV_AUTH=false` (backend, enforced at startup), Auth0 (frontend, real bearer tokens only) | See "Security" and "Database" below |

## Security

- Production secrets (`AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, `DATABASE_URL` credentials, DigitalOcean tokens) are **never committed** — see ".gitignore / secrets review" below.
- `ENABLE_DEV_AUTH=false` in every non-development environment. The backend fails to start otherwise (`app/core/dev_auth.py::check_dev_auth_startup_invariant`, enforced in `app/main.py::create_app`) — this is not optional configuration, it is a hard startup invariant.
- `CMP_DEV_AUTH_BYPASS` must never be set under `NODE_ENV=production` (frontend fails to start otherwise — `apps/web/lib/server/auth-mode.ts::resolveAuthMode`, enforced at startup via `apps/web/instrumentation.ts`). `CMP_TEST_AUTH_BYPASS` is a deliberately distinct mechanism reserved for the Playwright suite's own `next build && next start` run and is not a production auth path even though it can activate under `NODE_ENV=production` by design.
- The test database is never the pilot database: `TEST_DATABASE_URL` and pilot `DATABASE_URL` must always point at physically separate database instances. `scripts/reset_test_database.py` and every other `cmp_test`-targeting script refuse to run against any database that doesn't identify as `cmp_test` (`_database_name`/`require_cmp_test` guards throughout `apps/api/scripts/` and `apps/api/tests/`) — never run that tooling against the pilot database, and never point `TEST_DATABASE_URL` at it.
- Alembic never resolves a database target implicitly (`apps/api/migrations/env.py`'s `_alembic_url_safety.py` fails closed on a bare invocation) — a pilot migration must always supply its target explicitly, through the same approved mechanism used for every other environment (an explicit `-x db_url=...`/`Config` with `sqlalchemy.url` set, never a bare `alembic upgrade`).

## Auth0 prerequisites

Before pilot deployment, a company-controlled Auth0 tenant must have:

- A **Regular Web Application** (not SPA, not M2M) — the backing type `@auth0/nextjs-auth0`'s server-side session flow (`apps/web/lib/server/auth0.ts`) requires.
- An **Auth0 API** defining the CMP API's own resource audience — this identifier is `CMP_API_AUDIENCE` (frontend) and must **exactly equal** the backend's `OIDC_AUDIENCE`. A mismatch here means every bearer token the frontend obtains is issued for the wrong audience and every backend request 401s.
- **Allowed Callback URL**: `https://<pilot-domain>/auth/callback` (the exact path `@auth0/nextjs-auth0`'s route handler expects).
- **Allowed Logout URL**: `https://<pilot-domain>` (or the SDK's configured post-logout path).
- **Allowed Web Origin**: `https://<pilot-domain>`, if the current SDK version's CORS/silent-auth behavior requires it.

Do not provision or reference any specific real Auth0 tenant/application/identity in this document or in code — those are pilot-specific and out of scope for DEPLOY-001A.

## Database

- Managed PostgreSQL (DigitalOcean), reachable only from the application server/private trusted source — never a public, unrestricted database.
- **TLS is required.** SQLAlchemy's `postgresql+psycopg://` DSN passes libpq-style connection parameters straight through to psycopg 3 via the URL query string — no application code change is needed to enable TLS. Append the provider's required parameters directly to `DATABASE_URL`, e.g.:

  ```
  DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<db>?sslmode=verify-full&sslrootcert=/path/to/ca-certificate.crt
  ```

  - **Preferred:** `sslmode=verify-full` with the provider's issued CA certificate (`sslrootcert`), if certificate handling is practical for this deployment — this verifies both encryption and server identity.
  - **Minimum acceptable for the initial pilot:** `sslmode=require` (encrypts the connection but does not verify the server certificate), only if `verify-full` certificate handling proves impractical for the initial pilot. This is a real reduction in protection against a man-in-the-middle on the connection path and must be called out as such wherever it's used — it is never silently substituted by application code, and application code never disables certificate verification itself.
  - Do not hard-code DigitalOcean-specific credentials or certificate paths anywhere in the repository — these belong only in the deployed environment's own `DATABASE_URL`.
- Migrations are run as a separate, explicit step — never automatically on application startup (no migration call exists in `app/main.py` or any container entrypoint this ticket adds).

## Initial admin — first Platform Admin bootstrap

No manual `INSERT` into `users` is required or approved under this procedure. On a freshly migrated, empty production database:

1. Migrate the clean production database to head (explicit target, per "Security" above).
2. Obtain the exact Auth0 **issuer** and **subject** for the designated first administrator. The issuer is the tenant's OIDC issuer URL (e.g. `https://<tenant>.us.auth0.com/`); the subject is that person's Auth0 `user_id` (e.g. `auth0|abc123` or `google-oauth2|...`) — visible in the Auth0 dashboard under that user, or in the `sub` claim of a token they've already obtained by signing in once against this tenant.
3. From a machine with direct `DATABASE_URL` access to the pilot database (never over HTTP), run:

   ```
   python scripts/manage_platform_admin.py bootstrap-first-admin \
     --oidc-issuer "<exact issuer>" \
     --oidc-subject "<exact subject>" \
     --email "<administrator email>" \
     --display-name "<administrator display name>" \
     --reason "Initial pilot platform administrator"
   ```

   This previews the exact identity before making any change and requires typed confirmation (or `--yes` for a scripted/CI run). It resolves-or-creates the CMP `User` by exact issuer+subject identity and atomically grants platform-admin authority — see `docs/domain/AUTHORIZATION_MODEL.md`'s "Platform-level authority" section and `app.services.platform_admin_service.bootstrap_first_platform_admin` for the exact contract. It creates no Tenant, no TenantMembership, and no password/local credential.
4. Verify: the command's own output confirms the grant; independently, `python scripts/manage_platform_admin.py grant --oidc-issuer ... --oidc-subject ...` run again against the same identity reports "already holds active platform-admin authority" rather than performing a new grant.
5. The administrator logs in through the normal application URL (real Auth0 login) — this is their first real authentication, independent of and not weakened by step 3.
6. The administrator, now an authenticated Platform Admin, creates the pilot's Tenant through the normal CMP Platform Admin UI/API (`POST /platform/tenants`, gated by `require_platform_admin`) — not through this bootstrap procedure, and not through any manual `INSERT`.

Bootstrap audit trail: this is treated as an **infrastructure-security operation**, not a tenant-scoped business action (there is no tenant yet at this point, so no tenant-scoped `AuditEvent` is or should be created for it — the same structural precedent `user_service.create_user`/`platform_admin_service.grant_platform_admin` already establish). Its durable record is:

- Provider-level DB access logs/controls for whoever ran the bootstrap command (DigitalOcean audit trail, SSH/bastion access logs, or equivalent).
- The created `users` row (issuer/subject/email/display_name — permanent, never deleted).
- The created `platform_admins` row (`granted_at`, `reason`, `revoked_at IS NULL` — permanent grant/revoke history, mirrors every other platform-admin grant).

No separate platform-level audit primitive is invented for this ticket.

## .gitignore / secrets review

`.gitignore` already excludes `.env`, `.env.local`, `.env.*.local` (all real environment files) repository-wide. `apps/api/.env.example` and `apps/web/.env.example` are tracked and must only ever contain variable names and placeholders — never real values. Never commit: `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, database credentials, real Auth0 issuer/subject values for any real person, API tokens, DigitalOcean tokens, or private keys.
