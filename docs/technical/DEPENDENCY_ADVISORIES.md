# Dependency Advisories

Unresolved `npm audit` findings for `apps/web`, recorded here rather than fixed, per explicit instruction not to change frontend dependencies in this ticket.

## Next.js / PostCSS / Sharp (3 high severity)

All three advisories are transitive, nested under the direct production dependency `next@16.2.12`:

- **postcss@8.4.31** (nested under `next`) — high: path traversal / arbitrary file read via `sourceMappingURL` in CSS source maps (GHSA-r28c-9q8g-f849, GHSA-6g55-p6wh-862q). Vulnerable range `<=8.5.17`.
- **sharp@0.34.5** (nested under `next`, used for image optimization) — high: inherited libvips CVEs (GHSA-f88m-g3jw-g9cj). Vulnerable range `<0.35.0`.
- **next@16.2.12** — high, flagged as depending on both of the above.

**Status:** `npm audit fix` (without `--force`) reports no compatible fix — the only available fix path is `next@9.3.3`, a major/breaking downgrade. Not applied.

**Disposition:** deferred until a `next` major-version upgrade is separately planned and approved; out of scope for CMP-001/CMP-002. No frontend dependency changes were made to address this.
