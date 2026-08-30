# CMP API — production runtime image (DEPLOY-001B).
#
# Multi-stage: the builder stage installs the package (via the repo's own
# pyproject.toml, no Poetry/uv/pip-tools invented) into a throwaway
# --prefix so the runtime stage never carries pip's cache, build tooling,
# or the build context's stray files. No .env, no secrets, no test DB
# config, no dev extras ([project.optional-dependencies].dev) are ever
# part of this image — DATABASE_URL/OIDC_* are supplied only at container
# start (compose.prod.yaml), never baked in.
#
# Migrations are intentionally NOT run here or in the runtime CMD — see
# docs/deployment/PILOT_DEPLOYMENT.md, "Migrations".

FROM python:3.12-slim AS builder

WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Only what the package build needs (pyproject.toml's own
# [tool.setuptools.packages.find] scopes the install to app*) — no tests/,
# no scripts/, no migrations/ in this stage; migrations are copied
# directly into the runtime stage below since Alembic reads them from disk
# rather than as an importable package.
COPY pyproject.toml ./
COPY app ./app

# Production dependencies only (no [project.optional-dependencies].dev:
# pytest/httpx never ship in this image). Not an editable install --
# `--prefix` produces a normal, relocatable site-packages tree.
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root runtime user. No shell/login needed for a service process.
RUN groupadd --system cmp \
    && useradd --system --gid cmp --home-dir /app --no-create-home --shell /usr/sbin/nologin cmp

WORKDIR /app

COPY --from=builder /install /usr/local

# Alembic's migration graph, not part of the installed `app` package
# (migrations/env.py loads its own helper modules by file path). Included
# so the one-shot migration invocation documented in
# docs/deployment/PILOT_DEPLOYMENT.md can run `docker compose run --rm api
# ...` against this same image -- never executed automatically by this
# Dockerfile's own CMD.
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# The one production-required admin CLI (first-platform-admin bootstrap /
# grant / revoke -- docs/deployment/PILOT_DEPLOYMENT.md), so the approved
# bootstrap procedure can run from this same deployed artifact
# (`docker compose run --rm api python scripts/manage_platform_admin.py
# ...`) without exposing managed PostgreSQL to an operator laptop or
# requiring a separate host Python environment. Deliberately NOT the rest
# of apps/api/scripts/ -- reset_test_database.py, create_test_db.py,
# dev_seed_frontend_pilot.py, seed_qa_005b.py, and bootstrap_pilot_
# master_data.py are dev/test-only and must never ship in the production
# image.
COPY scripts/manage_platform_admin.py ./scripts/manage_platform_admin.py

RUN chown -R cmp:cmp /app
USER cmp

# Documents the container's internal port; Compose (not this line) decides
# whether/how it is ever reachable from outside the private network.
EXPOSE 8000

# One process for the pilot: no evidence yet that DB connection pool size
# or pilot load needs multi-worker uvicorn, and a single process keeps
# logs and restarts predictable. Revisit only if pilot load data says
# otherwise. No --reload in production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
