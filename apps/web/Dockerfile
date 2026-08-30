# CMP web (Next.js) — production runtime image (DEPLOY-001B).
#
# Multi-stage, using Next's standalone output (next.config.ts:
# output: "standalone"). Build MUST succeed without production Auth0
# secrets -- DEPLOY-001A already proved `next build` works with no Auth0
# runtime variables and no .env.local, and this Dockerfile preserves that:
# checkAuthStartupInvariant() (instrumentation.ts) only runs when the
# server actually starts (`node server.js`), never during `next build`.
# Real runtime env vars (CMP_API_BASE_URL, AUTH0_*, ...) are supplied only
# at container start (compose.prod.yaml), never baked into this image.

FROM node:22-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# No Auth0/CMP_* env vars are set here on purpose -- the build must not
# require them (see header comment).
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nextjs \
    && adduser --system --uid 1001 --ingroup nextjs nextjs

WORKDIR /app

# Standalone output: a self-contained server.js plus only the
# node_modules subset actually required at runtime. Static assets and
# public/ are deliberately not included by `output: "standalone"` and
# must be copied in alongside it.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

# Documents the container's internal port; Compose (not this line) decides
# whether/how it is ever reachable from outside the private network.
EXPOSE 3000

CMD ["node", "server.js"]
