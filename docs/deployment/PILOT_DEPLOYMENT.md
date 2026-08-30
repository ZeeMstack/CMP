# Pilot Deployment

Read this for pilot/production deployment configuration and the first-platform-admin bootstrap procedure. Permanent coding rules are in the root `CLAUDE.md`; the approved deployment architecture is DigitalOcean (one application VPS, DigitalOcean Managed PostgreSQL, Docker Compose runtime, Caddy reverse proxy/TLS, one public CMP hostname, Auth0 production authentication, manual controlled deployments). This document covers the **environment/configuration contract, admin-bootstrap procedure (DEPLOY-001A), and container runtime packaging (DEPLOY-001B)**. Actual DigitalOcean/Auth0/DNS provisioning and CI/CD are later DEPLOY slices.

## Production container topology (DEPLOY-001B)

```
Internet --HTTPS--> Caddy --> web (Next.js, port 3000) --> api (FastAPI, port 8000) --TLS--> DigitalOcean Managed PostgreSQL
```

- **Caddy** (`Caddyfile`, `caddy:2-alpine`) is the only container publishing host ports (`80`, `443`). It terminates TLS (automatic HTTPS/Let's Encrypt) and reverse-proxies everything to `web`.
- **web** (`apps/web/Dockerfile`) is the Next.js production server (standalone output). It owns `/api/**` as the BFF and is the only service that talks to `api` — over the private `cmp_internal` Compose network, never a published host port.
- **api** (`apps/api/Dockerfile`) is FastAPI/uvicorn. It is **never** published to the host or the public internet — reachable only as `http://api:8000` from `web`.
- **PostgreSQL** is not a container in this stack. `compose.prod.yaml` has no `postgres`/`db` service and no `5432` mapping anywhere — production Postgres is DigitalOcean Managed PostgreSQL, reached by `api` over TLS via `DATABASE_URL`.

All three application/edge services are defined in `compose.prod.yaml` at the repo root. Real production secrets are never in that file or in Git — they are supplied by an external, untracked env file at deploy time.

### Build

```
docker compose -f compose.prod.yaml build
```

Building requires no production database, no Auth0 tenant, and no real secrets — both images build from disposable/placeholder-free context. The frontend build in particular does not require `AUTH0_*`/`CMP_API_AUDIENCE` (see "Frontend build does not require secrets" below); `apps/api/.dockerignore` and `apps/web/.dockerignore` also keep `.env*` and `.env.local` out of both build contexts (`.env.example` is intentionally still allowed).

### Config — external runtime env file

Real production values live only in an env file kept **outside Git**, referenced explicitly at every `docker compose` invocation:

```
docker compose --env-file /path/to/production.env -f compose.prod.yaml up -d
```

Required variables (all consumed as Compose interpolation, not written into `compose.prod.yaml` itself):

**Backend (`api`):**

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Managed Postgres DSN, TLS query params included (`?sslmode=verify-full&sslrootcert=...`, or `?sslmode=require` minimum — see "Database" above) |
| `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` | Required — the backend refuses to start without all three outside `ENV=development` |
| `DB_CONNECT_TIMEOUT_SECONDS`, `OIDC_ALLOWED_ALGORITHMS`, `OIDC_CLOCK_SKEW_SECONDS`, `OIDC_JWKS_CACHE_TTL_SECONDS`, `OIDC_JWKS_MIN_REFRESH_INTERVAL_SECONDS` | Optional — `compose.prod.yaml` supplies production-safe defaults if unset |

`ENV=production` and `ENABLE_DEV_AUTH=false` are hardcoded in `compose.prod.yaml` itself (not operator-configurable) — this is a security invariant, not a deployment choice.

**Frontend (`web`):**

| Variable | Notes |
|---|---|
| `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, `APP_BASE_URL`, `CMP_API_AUDIENCE` | Required — the frontend refuses to start under `NODE_ENV=production` without all six |

`NODE_ENV=production` and `CMP_API_BASE_URL=http://api:8000` are hardcoded in `compose.prod.yaml` — `CMP_API_BASE_URL` must stay the **internal** Compose DNS name; it is never a browser-visible FastAPI URL.

**Edge (`caddy`):**

| Variable | Notes |
|---|---|
| `CMP_PUBLIC_HOST` | The one public CMP hostname (e.g. `cmp.example.com`), read by `Caddyfile`'s `{$CMP_PUBLIC_HOST}` placeholder |

### Start

```
docker compose --env-file /path/to/production.env -f compose.prod.yaml up -d
```

### Stop

```
docker compose --env-file /path/to/production.env -f compose.prod.yaml down
```

(Add `-v` only if the Caddy TLS-state volumes should also be discarded — normally they should not be, to avoid re-issuing certificates unnecessarily.)

### Logs

```
docker compose -f compose.prod.yaml logs -f api
docker compose -f compose.prod.yaml logs -f web
docker compose -f compose.prod.yaml logs -f caddy
```

### Health

- **API**: internal readiness at `http://api:8000/ready` (checked by Compose's own `api` healthcheck — not published to the host).
- **Frontend**: public URL `https://<pilot-host>/login` (a genuinely unauthenticated, prerendered page — see `apps/web/app/login/page.tsx`); the container's own healthcheck hits it internally at `http://localhost:3000/login`.
- A container reporting "unhealthy" is not necessarily crashed — e.g. a Next.js instrumentation-hook startup failure (misconfigured Auth0 env) leaves the Node process running but serving HTTP 500 to every request; the healthcheck, not the process exit code, is what surfaces this. Watch `docker compose ps` / container health status, not just "is the container running."

### Migration

Migrations are **never** run automatically — neither Dockerfile's `CMD` nor any container entrypoint touches Alembic. `migrations/env.py`'s `_alembic_url_safety.py` also fails closed on any bare/implicit invocation (see root `CLAUDE.md`), so a pilot migration must always supply its target explicitly, the same way `scripts/reset_test_database.py` and `tests/conftest.py:migrations_alembic_config()` already do (a `Config` with `sqlalchemy.url` set directly — never a bare `alembic upgrade`).

The `api` image (`apps/api/Dockerfile`) includes `alembic.ini` and `migrations/` for exactly this purpose, so a one-shot invocation can run against the built production image:

```
docker compose --env-file /path/to/production.env -f compose.prod.yaml run --rm api <explicit migration command>
```

**No `<explicit migration command>` is implemented yet.** Writing one requires a small script that constructs an Alembic `Config` with `sqlalchemy.url` set explicitly from `DATABASE_URL` (mirroring `scripts/reset_test_database.py`'s `_migrations_cfg()`), since the existing safety module has no bare-CLI `-x`/env-var override wired into `migrations/env.py` — inventing one, along with a backup-before-migration workflow, is DEPLOY-001D's scope, not DEPLOY-001B's. Until then, a pilot migration must be run the same way any other environment's migration already is: from a machine with an explicit `Config`/`sqlalchemy.url` pointed at the target database (never a bare CLI invocation), following the exact pattern in `scripts/reset_test_database.py`.

### Platform-admin CLI (containerized)

`apps/api/Dockerfile` copies exactly one script into the image, at `/app/scripts/manage_platform_admin.py` — deliberately not the rest of `apps/api/scripts/` (`reset_test_database.py`, `create_test_db.py`, `dev_seed_frontend_pilot.py`, `seed_qa_005b.py`, `bootstrap_pilot_master_data.py` are dev/test-only and never ship in the production image). This lets the first-platform-admin bootstrap procedure (see "Initial admin" below) run from the same deployed artifact already holding the correct `DATABASE_URL`/OIDC configuration, over the private network — with no separate host Python environment and no need to expose managed PostgreSQL to an operator laptop:

```
docker compose --env-file /path/to/production.env -f compose.prod.yaml run --rm api \
  python scripts/manage_platform_admin.py bootstrap-first-admin \
  --oidc-issuer "<exact issuer>" \
  --oidc-subject "<exact subject>" \
  --email "<administrator email>" \
  --display-name "<administrator display name>" \
  --reason "Initial pilot platform administrator"
```

`run --rm` starts a throwaway container from the already-built `api` image, with the same environment (`DATABASE_URL`, `OIDC_*`) as the running `api` service — no dev auth, no HTTP route, no extra secrets baked into the image. `grant`/`revoke` work the same way, substituting the subcommand.

### Network

- Only `caddy` publishes host ports: `80` and `443`.
- `web` publishes **no** host port (not `3000`).
- `api` publishes **no** host port (not `8000`).
- No service publishes `5432` — Postgres is not part of this Compose file at all.
- All three services share one private Compose network (`cmp_internal`); `web` reaches `api` at `http://api:8000`, `caddy` reaches `web` at `web:3000`.

DigitalOcean/Auth0/DNS provisioning steps are not part of this document — see DEPLOY-001E.

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
3. Run the platform-admin CLI against the pilot database (never over HTTP) — from the deployed `api` image itself, over the private network (see "Platform-admin CLI (containerized)" above), or from a machine with direct `DATABASE_URL` access if the container path is unavailable:

   ```
   docker compose --env-file /path/to/production.env -f compose.prod.yaml run --rm api \
     python scripts/manage_platform_admin.py bootstrap-first-admin \
     --oidc-issuer "<exact issuer>" \
     --oidc-subject "<exact subject>" \
     --email "<administrator email>" \
     --display-name "<administrator display name>" \
     --reason "Initial pilot platform administrator"
   ```

   This previews the exact identity before making any change and requires typed confirmation (or `--yes` for a scripted/CI run). It resolves-or-creates the CMP `User` by exact issuer+subject identity and atomically grants platform-admin authority — see `docs/domain/AUTHORIZATION_MODEL.md`'s "Platform-level authority" section and `app.services.platform_admin_service.bootstrap_first_platform_admin` for the exact contract. It creates no Tenant, no TenantMembership, and no password/local credential.
4. Verify: the command's own output confirms the grant; independently, running `... run --rm api python scripts/manage_platform_admin.py grant --oidc-issuer ... --oidc-subject ...` again against the same identity reports "already holds active platform-admin authority" rather than performing a new grant.
5. The administrator logs in through the normal application URL (real Auth0 login) — this is their first real authentication, independent of and not weakened by step 3.
6. The administrator, now an authenticated Platform Admin, creates the pilot's Tenant through the normal CMP Platform Admin UI/API (`POST /platform/tenants`, gated by `require_platform_admin`) — not through this bootstrap procedure, and not through any manual `INSERT`.

Bootstrap audit trail: this is treated as an **infrastructure-security operation**, not a tenant-scoped business action (there is no tenant yet at this point, so no tenant-scoped `AuditEvent` is or should be created for it — the same structural precedent `user_service.create_user`/`platform_admin_service.grant_platform_admin` already establish). Its durable record is:

- Provider-level DB access logs/controls for whoever ran the bootstrap command (DigitalOcean audit trail, SSH/bastion access logs, or equivalent).
- The created `users` row (issuer/subject/email/display_name — permanent, never deleted).
- The created `platform_admins` row (`granted_at`, `reason`, `revoked_at IS NULL` — permanent grant/revoke history, mirrors every other platform-admin grant).

No separate platform-level audit primitive is invented for this ticket.

## .gitignore / secrets review

`.gitignore` already excludes `.env`, `.env.local`, `.env.*.local` (all real environment files) repository-wide. `apps/api/.env.example` and `apps/web/.env.example` are tracked and must only ever contain variable names and placeholders — never real values. Never commit: `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, database credentials, real Auth0 issuer/subject values for any real person, API tokens, DigitalOcean tokens, or private keys.
