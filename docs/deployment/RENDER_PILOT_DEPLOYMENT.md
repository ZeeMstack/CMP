# Render Pilot Deployment

This document is the Render-specific deployment runbook (DEPLOY-001E). It is an **alternative** to `docs/deployment/PILOT_DEPLOYMENT.md`, not a replacement — that document (DigitalOcean, one application VPS, Docker Compose, Caddy reverse proxy/TLS) remains a valid, supported deployment path and is left unchanged. Use this document when deploying to Render instead.

Permanent coding rules are in the root `CLAUDE.md`. This document covers configuration, migration, and first-admin bootstrap for a Render-hosted pilot — it does not change any application code, domain rule, or the underlying Alembic/tenant-isolation safety model.

## Architecture

```
Internet --HTTPS--> Render Web Service (Next.js, apps/web/Dockerfile)
                        --Render private network-->
                     Render Private Service (FastAPI, apps/api/Dockerfile, port 8000)
                        --Render internal connection-->
                     Render managed PostgreSQL (internal URL)
```

- **web** is a Render **Web Service** built from `apps/web/Dockerfile`. It is the only publicly reachable application service and owns `/api/**` as the BFF proxy to `api`, exactly as in the Compose/Caddy topology — nothing about the BFF proxy pattern changes.
- **api** is a Render **Private Service** built from `apps/api/Dockerfile`, listening on port `8000`. It is never publicly reachable; `web` reaches it only over Render's private network.
- **PostgreSQL** is Render Managed PostgreSQL, reached by `api` (and, for migration/admin-bootstrap Jobs, by a One-off Job using the same image/environment) via its **internal** connection URL — never the external/public one for normal operation.
- No Caddy, no `compose.prod.yaml` — Render terminates TLS for the public Web Service itself.

## Public URL

- **Initial pilot testing**: the Render-assigned `https://<web-service-name>.onrender.com` URL.
- **Later**: `growcmp.com` becomes the primary custom domain on the `web` Web Service. `farmcmp.com` is added later still, configured to redirect to `growcmp.com`. Neither is provisioned as part of this document — see "Auth0" below for the config updates each domain change requires.

## Region

Create the `web` Web Service, the `api` Private Service, and the Postgres instance **in the same Render region and the same Render workspace** — Render's private networking (used for `web` → `api` and for `api`/migration-Job → Postgres) only connects services that share both. Region choice itself should follow the pilot's actual operator/user location; no part of this codebase constrains which region.

## Release control

Set **Auto-Deploy to `Off`** on both the `web` Web Service and the `api` Private Service. This preserves the existing "controlled deployment from merged `main`" release policy: a deploy is triggered explicitly via Render's Manual Deploy, selecting the exact reviewed/merged `main` commit — an arbitrary push to `main` never silently becomes production. (Render Postgres has no equivalent auto-deploy concept.)

## Web (Next.js)

- Build from `apps/web/Dockerfile`, build context `apps/web` — used **as-is**, no Dockerfile changes. Next's standalone `server.js` (`.next/standalone`, enabled by `next.config.ts`'s `output: "standalone"`) reads `process.env.PORT`/`process.env.HOSTNAME` at runtime; `HOSTNAME=0.0.0.0` is already baked in, and the image's `ENV PORT=3000` is only a fallback default that a Render-injected runtime value overrides.
- **Health check path**: `/login` — the same genuinely public, unauthenticated, prerendered page `compose.prod.yaml`'s own `web` healthcheck already targets (`apps/web/app/login/page.tsx`). There is no dedicated `/health` route on the frontend.
- **PORT**: do not manually set a `PORT` environment variable on this service in the Render dashboard unless Render's own service configuration screen actually requires or shows one at setup time. Standalone Next.js already binds to whatever `PORT` Render provides dynamically — setting one by hand risks a mismatch between what Render expects to route to and what the container binds. Confirm the real dashboard behavior during first setup and only override if genuinely necessary.
- **Runtime environment variables** (set in the Render dashboard, never in `render.yaml` in plaintext — see "Secrets"): `NODE_ENV=production`, `CMP_API_BASE_URL` (see "Web → API private connectivity" below), `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, `APP_BASE_URL`, `CMP_API_AUDIENCE`. All six Auth0/`CMP_API_AUDIENCE` variables are required at startup once `NODE_ENV=production` and no dev/test bypass is active (`apps/web/lib/server/auth-mode.ts::checkAuthStartupInvariant`, enforced via `apps/web/instrumentation.ts`) — this invariant is unchanged by deploying to Render.

### Web → API private connectivity

Render's private networking gives each service a stable private hostname of the form `<service-name>-<id>:<port>`, reachable only from other services in the same region and workspace — this replaces Compose's `http://api:8000` bridge-network DNS name.

- **No code change is required.** `apps/web/app/api/[...path]/route.ts` already reads `CMP_API_BASE_URL` via `requireEnv()` at request time — it is never baked into the build (the Dockerfile's build stage sets no `CMP_*`/`AUTH0_*` variables; see the Dockerfile's own header comment).
- Set `CMP_API_BASE_URL` as a **runtime environment variable on the `web` service**, to `http://<api-private-hostname>:8000`, using the private hostname Render assigns to the `api` Private Service once it exists (visible on the `api` service's own Render dashboard page under its private networking / connect info).
- Keep `api` as a Render **Private Service**, never a public Web Service — the existing BFF pattern (only `web` calls `api`) transfers directly, and there is no compelling reason found in this codebase to expose FastAPI publicly.

## API (FastAPI)

- Build from `apps/api/Dockerfile`, build context `apps/api` — used **as-is**, no Dockerfile changes. `CMD` hardcodes `uvicorn ... --port 8000`; configure the Render Private Service's port to `8000` to match (Private Services are given a fixed configured port for private-network routing, unlike a public Web Service's dynamic-`PORT` contract).
- **Health check**: use `/health` (`app/api/health.py`) — a pure liveness check with no database dependency, always fast and always `200` while the process is up. This is what should govern Render's own health-check/restart behavior, so a transient database blip never causes Render to churn a healthy process.
- **Readiness**: `/ready` (`app/api/ready.py`) additionally checks database connectivity (`SELECT 1`) and returns `503` if it fails. Use it for manual verification and monitoring after a deploy, not as Render's primary health-check target.
- **Runtime environment variables**: `ENV=production`, `ENABLE_DEV_AUTH=false` (both security invariants, not operator-configurable — the backend refuses to start with dev auth enabled outside development, `app/core/dev_auth.py::check_dev_auth_startup_invariant`), `DATABASE_URL` (see "Database" below), `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` (all three required outside `ENV=development`, `app/core/settings.py::check_oidc_startup_invariant`), plus the optional `DB_CONNECT_TIMEOUT_SECONDS`/`OIDC_*` tuning variables `compose.prod.yaml` already documents production-safe defaults for.

## Database

CMP's **primary Render runtime `DATABASE_URL`** — used by the `api` service and by the migration/first-admin One-off Jobs — is Render's **Internal** Postgres connection URL, reached entirely over Render's private network. It is never the External/public one for normal application operation.

- **Internal URL: no `sslmode`.** Render's own current guidance is that internal Postgres connections already run over Render's private network and do not require (and should not be forced onto) TLS — appending `sslmode=require` to the internal URL is not supported and can produce SSL handshake failures. CMP's final documented `DATABASE_URL` form for Render is therefore, deliberately, **without** an `sslmode` query parameter:

  ```
  DATABASE_URL=postgresql+psycopg://<user>:<password>@<render-internal-host>/<database>
  ```

  Render issues the internal URL as `postgres://<user>:<password>@<render-internal-host>/<database>`; CMP uses SQLAlchemy with the `psycopg` (psycopg 3) driver, which requires the `postgresql+psycopg://` dialect prefix — the operator rewrites the scheme by hand when setting the `api` service's environment variable in the Render dashboard. **No application-level URL normalization is introduced or needed** — `sanitize_target_identity()`/`create_engine()` already accept this exact form unchanged.
- **This `sslmode`-free internal URL only works together with `--allow-private-network-without-tls`** (see "Migration" below) — `apps/api/scripts/migrate_database.py`'s production-style TLS check still refuses any `DATABASE_URL` without a safe `sslmode` unless that flag is explicitly passed. The `api` service itself has no such check (it is application runtime code, not the migration CLI) and connects with this URL directly.
- **This is not a global relaxation of CMP's TLS policy.** Every ordinary production `DATABASE_URL` — any target that is not passed through `--allow-private-network-without-tls` — still requires `sslmode=require|verify-ca|verify-full`, exactly as before. The exception applies only to a target the flag has itself positively verified is private (see "Private-network migration flag" below); nothing about this changes what a plain, unflagged production invocation demands.
- **External URL: TLS required, and not used for normal CMP traffic.** Render's External/public Postgres connection string does require TLS (`sslmode=require` at minimum). CMP's application (`api`) and its normal migration/admin-bootstrap Jobs must never use the external URL — it exists only as a fallback for occasions where private-network reachability genuinely isn't available (e.g. inspecting the database from an operator's own machine), and any such use must supply `sslmode=require` (or stronger) explicitly.
- **After deployment, disable or tightly restrict the external connection** wherever Render's plan/dashboard permits it (e.g. an IP allowlist, or disabling the public endpoint outright if the plan supports it) — there is no ongoing operational need for public reachability once the internal-URL path is confirmed working.
- No code change was made to `migrate_database.py`'s or `migrations/_alembic_url_safety.py`'s existing TLS/host/database-name safety checks beyond the new opt-in `--allow-private-network-without-tls` flag itself — neither file contained any DigitalOcean- or Render-specific logic to begin with, and the default TLS requirement for every other invocation is unchanged.

## Migration

Migrations are **never** run automatically — not on `api` startup (no Alembic call anywhere in `app/main.py`), and never via a Render Pre-Deploy Command. A Pre-Deploy Command runs before *every* deploy of a service automatically; using it here would mean either hardcoding `--yes` permanently (defeating this script's own typed-confirmation model) or having every deploy silently attempt a migration whether one was intended or not — both are exactly the kind of automatic-migration behavior this pilot deliberately avoids.

**Use a Render One-off Job** against the `api` service instead — it runs the already-built `api` image with the same environment (including private database access) for a single operator-triggered command, closely mirroring the existing `docker compose run --rm api ...` pattern.

Because CMP's primary Render `DATABASE_URL` is the internal Postgres URL **without** `sslmode` (see "Database" above), the migration procedure for Render internal Postgres must explicitly pass `--allow-private-network-without-tls` — this is the canonical, expected command for this environment, not a fallback:

```
python scripts/migrate_database.py \
  --allow-private-network-without-tls \
  --backup-confirmed \
  --expect-host <render-internal-host> \
  --expect-database <database> \
  --yes
```

Before running this:

1. **Verify a recoverable Render Postgres backup/point-in-time-recovery snapshot exists** — `--backup-confirmed` is an operator acknowledgement of this, not a backup mechanism itself (unchanged from the existing DigitalOcean procedure).
2. `--expect-host` and `--expect-database` are **mandatory** with `--allow-private-network-without-tls` — the script refuses to proceed without both, before `DATABASE_URL` is even read (see "Private-network migration flag" below).

Render Shell (an interactive shell into a running instance) is the documented fallback if One-off Jobs is unavailable on the selected plan.

### Private-network migration flag (`--allow-private-network-without-tls`)

`apps/api/scripts/migrate_database.py` supports an explicit, provider-neutral exception to its TLS requirement, for a target reachable only over a verified private network. It is **not** Render-specific and never auto-detects a provider — Render's internal Postgres URL is simply this pilot's one concrete use of it.

**This is not a global relaxation of CMP's TLS policy.** Without the flag, production TLS behavior is **exactly unchanged**: an ordinary production-style invocation still refuses unless `DATABASE_URL` carries `sslmode=require|verify-ca|verify-full`. The flag only ever opens an exception for the one target it is explicitly pointed at, for that single invocation — it never changes the default.

With the flag:

- `--expect-host` and `--expect-database` must both be supplied, or the script refuses immediately, before `DATABASE_URL` is even read.
- The target host must not be `localhost`/a loopback address (the existing dev/test-database refusal already covers this at the literal-hostname level; the new check additionally covers a hostname that merely *resolves* to loopback).
- **The flag positively verifies, via real DNS resolution, that the target resolves only to approved private address ranges before the TLS exception is permitted** — it does not merely trust an `--expect-host` string or a provider label. The hostname is resolved via the system resolver (resolution failure refuses), and **every** resolved address (IPv4 and IPv6) must be a private-network address — RFC1918 IPv4 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) or IPv6 unique-local (`fc00::/7`) — never loopback, link-local, multicast, or any publicly routable address. If even one resolved address is public, the script refuses before touching the database. A literal public IP as the host is refused the same way.
- **All existing database-identity, dev/test-database refusal, backup-confirmation, and migration safeguards remain fully active** — the flag adds this one additional, narrowly-scoped check on top of them, it removes none of them: the known dev/test-database-name refusal, `--backup-confirmed`, and the typed confirmation prompt unless `--yes` is passed all still apply. `--yes` never bypasses any of the above — it only skips the interactive typed-confirmation step, exactly as before.
- The script prints, in plain terms, that private-network/no-TLS mode was explicitly selected and which resolved addresses were verified private. It never prints credentials (host/database/resolved-IP output only).
- `--allow-private-network-without-tls` and `--allow-non-production-database` (the pre-existing `cmp_test`-only escape hatch) are mutually exclusive — combining them is refused, since they represent two different, non-stacking safety models.

Focused tests for this flag live in `apps/api/tests/test_migrate_database_script.py`; see "Verify" in the DEPLOY-001E.2 change record for the full list.

## First admin

Same One-off Job mechanism, no application code change, no SQL, no public database exposure:

```
python scripts/manage_platform_admin.py bootstrap-first-admin \
  --oidc-issuer "<exact issuer>" \
  --oidc-subject "<exact subject>" \
  --email "<administrator email>" \
  --display-name "<administrator display name>" \
  --reason "Initial pilot platform administrator" \
  --yes
```

This is the identical procedure `docs/deployment/PILOT_DEPLOYMENT.md`'s "Initial admin" section already documents — only the invocation mechanism (`docker compose run --rm` → Render One-off Job) changes. It resolves-or-creates the CMP `User` by exact OIDC issuer+subject identity and atomically grants platform-admin authority (`app.services.platform_admin_service.bootstrap_first_platform_admin`); it creates no Tenant, no TenantMembership, and no password/local credential.

## Auth0

Auth0/OIDC remains the sole authentication mechanism — Render introduces no new auth system.

**Initial pilot testing** (temporary `*.onrender.com` URL): configure the Auth0 application with

- Allowed Callback URL: `https://<web-service>.onrender.com/auth/callback`
- Allowed Logout URL: `https://<web-service>.onrender.com`
- Allowed Web Origin: `https://<web-service>.onrender.com`

and set the `web` service's `APP_BASE_URL` to the same `https://<web-service>.onrender.com` value.

**Later, once `growcmp.com` is attached**: update the same three Auth0 URLs to `https://growcmp.com/...`, and update `APP_BASE_URL` accordingly, then redeploy `web`. This is a second, expected configuration pass — not a blocker to the initial pilot. `farmcmp.com`'s later redirect to `growcmp.com` does not require its own separate Auth0 application entry as long as it only ever redirects (never serves the app directly).

Auth0 application type remains a **Regular Web Application** (not SPA, not M2M); the Auth0 API resource's audience identifier is `CMP_API_AUDIENCE` (frontend) and must exactly equal `OIDC_AUDIENCE` (backend) — unchanged from the existing DigitalOcean procedure.

## Secrets

Every real secret value (`AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, `DATABASE_URL`'s credentials, `OIDC_*` real values, `CMP_API_AUDIENCE`) is entered **directly into the Render dashboard's environment-variable settings for the relevant service** — never written into `render.yaml`, never committed to Git. This mirrors the existing rule for the Compose/DigitalOcean path, where real values live only in an external, untracked env file. See "render.yaml" in the DEPLOY-001E.1 discovery record for exactly which variable *names* (not values) a future committed Blueprint should declare with `sync: false`.

## render.yaml

**Not created yet — this pilot's first hosted deployment uses manual Render Dashboard configuration.** Reason: the actual provider-specific behavior this document has to leave provisionally open above (exact private-hostname format, exact Web Service port/PORT behavior) needs to be validated against the real dashboard once, before it is worth capturing as reproducible infrastructure-as-code. After the first successful hosted deployment, capture the resulting known-good configuration as a committed `render.yaml` in a follow-up change.
