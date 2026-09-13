"use client";

import { Activity, Leaf, ShieldCheck, Sprout } from "lucide-react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { WaterlineWordmark } from "@/components/brand/WaterlineMark";
import { sanitizeReturnTo } from "@/lib/auth/return-to";

/** Served directly from public/ -- next/image's `fill` layout needs only
 * the URL string, not a static import (imports are for source-tree
 * assets, not files already in public/). */
const GREENHOUSE_PHOTO_SRC = "/brand/growcmp-greenhouse.png";

/**
 * UX-004 final login screen.
 *
 * ---------------------------------------------------------------------
 * STOP CONDITION (email/password fields) -- still in effect
 * ---------------------------------------------------------------------
 * No password-shaped input renders anywhere on this page. Verified
 * directly against the installed SDK: grepped
 * `node_modules/@auth0/nextjs-auth0@4.26.0/dist/server/auth-client.js` for
 * every `grant_type=...`/`/oauth/token` path it exposes -- Authorization
 * Code redirect (what both buttons below use), passwordless OTP,
 * WebAuthn/passkey, MFA, token exchange -- there is no Resource Owner
 * Password Grant and no other path that accepts a raw username+password
 * from our own page. See the AUTH-001 architecture-spike report (prior
 * round) for the full embedded-credential investigation and why it
 * remains parked. "Forgot password?" and "Keep me signed in" are omitted
 * for the same reason: no password field exists here to reset, and
 * session persistence is a static server-wide `Auth0Client` option (see
 * `lib/server/session.ts`), not a per-login toggle.
 *
 * Both provider actions use Auth0 Universal Login exactly as verified and
 * approved: `handleLogin` (dist/server/auth-client.js) forwards every
 * /auth/login query param except `returnTo` verbatim to Auth0's
 * /authorize request, so `?connection=google-oauth2` is a real,
 * already-supported mechanism (already configured on this tenant -- see
 * the `google-oauth2|...` subject example in
 * docs/deployment/PILOT_DEPLOYMENT.md). The plain `/auth/login?returnTo=`
 * link carries no `connection` param -- it does not force any specific
 * connection, so it is labeled "Sign in with organization account"
 * (accurate) rather than a claim about a specific database/email
 * connection this repo cannot verify. It takes the primary (filled)
 * treatment as the generic entry point; "Continue with Google" -- the one
 * connection actually verified -- stays secondary/outlined.
 *
 * ---------------------------------------------------------------------
 * Greenhouse photograph
 * ---------------------------------------------------------------------
 * Real local asset, supplied and approved this round:
 * public/brand/growcmp-greenhouse.png (bright commercial hydroponic
 * greenhouse, leafy greens, no people, no CGI look). Rendered via
 * next/image with a static import (optimized, no remote fetch). A flat
 * `bg-wl-surface/60` wash covers the entire hero panel edge-to-edge for
 * text readability -- not a bounded card behind the copy, no gradient.
 */

const GOOGLE_CONNECTION = "google-oauth2";

function GoogleGlyph() {
  return (
    <span
      aria-hidden="true"
      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-current text-[10px] font-bold leading-none"
    >
      G
    </span>
  );
}

const PRIMARY_BUTTON_CLASSES =
  "flex h-12 w-full items-center justify-center gap-2 rounded-lg border border-transparent bg-wl-brand text-sm font-medium text-wl-text-on-brand transition-colors hover:bg-wl-brand-hover active:bg-wl-brand-pressed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

const SECONDARY_BUTTON_CLASSES =
  "flex h-12 w-full items-center justify-center gap-2 rounded-lg border border-wl-border-strong bg-wl-surface-raised text-sm font-medium text-wl-text transition-colors hover:bg-wl-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus";

function AuthPanel({ googleHref, organizationHref }: { googleHref: string; organizationHref: string }) {
  return (
    <div className="flex items-center justify-center bg-wl-surface px-6 py-12 md:px-10">
      <div className="mb-10 w-full max-w-[420px] md:mb-16">
        <div className="flex justify-center">
          <div className="scale-[1.7]">
            <WaterlineWordmark variant="default" />
          </div>
        </div>
        <p className="mt-4 text-center text-[11px] font-semibold uppercase tracking-[0.15em] text-wl-text-tertiary">
          Cultivate a brighter tomorrow
        </p>

        <h1 className="mt-8 text-center text-2xl font-semibold tracking-tight text-wl-text">Welcome back</h1>
        <p className="mt-2 text-center text-sm text-wl-text-secondary">Sign in to continue to GrowCMP.</p>

        <div className="mt-8 flex flex-col gap-3">
          <a href={organizationHref} className={PRIMARY_BUTTON_CLASSES}>
            Sign in with organization account
          </a>

          <div className="flex items-center gap-3" aria-hidden="true">
            <div className="h-px flex-1 bg-wl-border" />
            <span className="text-[11px] font-medium uppercase tracking-wide text-wl-text-tertiary">Or</span>
            <div className="h-px flex-1 bg-wl-border" />
          </div>

          <a href={googleHref} className={SECONDARY_BUTTON_CLASSES}>
            <GoogleGlyph />
            Continue with Google
          </a>
        </div>

        <p className="mt-4 text-center text-xs text-wl-text-tertiary">Secure sign-in managed by your organization.</p>

        <p className="mt-8 text-center text-[10px] font-medium uppercase tracking-wide text-wl-text-tertiary">
          Crops | People | Progress
        </p>
      </div>
    </div>
  );
}

function AuthPanelFallback() {
  return (
    <div className="flex items-center justify-center bg-wl-surface px-6 py-12 md:px-10">
      <div role="status" aria-label="Loading" className="mb-10 w-full max-w-[420px] animate-pulse md:mb-16">
        <div className="mx-auto h-8 w-40 rounded bg-wl-surface-sunken" />
        <div className="mx-auto mt-8 h-7 w-32 rounded bg-wl-surface-sunken" />
        <div className="mx-auto mt-3 h-4 w-56 rounded bg-wl-surface-sunken" />
        <div className="mt-8 flex flex-col gap-3">
          <div className="h-12 rounded-lg bg-wl-surface-sunken" />
          <div className="h-12 rounded-lg bg-wl-surface-sunken" />
        </div>
        <span className="sr-only">Loading&hellip;</span>
      </div>
    </div>
  );
}

const VALUE_ITEMS = [
  { Icon: Sprout, label: "Plan", caption: "From seed to harvest" },
  { Icon: Activity, label: "Track", caption: "Real-time visibility" },
  { Icon: ShieldCheck, label: "Ensure", caption: "Quality & compliance" },
  { Icon: Leaf, label: "Grow", caption: "A more sustainable future" },
] as const;

/** Real local greenhouse photograph (public/brand/growcmp-greenhouse.png),
 * softened with a flat existing-token wash across the whole panel -- not a
 * card behind the text -- so copy stays readable while the photo remains
 * clearly visible throughout. */
function ImagePanel() {
  return (
    <div className="relative hidden isolate overflow-hidden md:block">
      <Image
        src={GREENHOUSE_PHOTO_SRC}
        alt=""
        fill
        priority={false}
        sizes="(min-width: 768px) 62vw, 0px"
        className="object-cover"
        style={{ filter: "saturate(0.92) brightness(1.04)" }}
      />
      <div aria-hidden="true" className="absolute inset-0 bg-wl-surface/60" />

      <div className="relative flex h-full flex-col justify-end px-10 py-14 lg:px-16">
        <div className="max-w-lg">
          <h2 className="text-2xl font-semibold leading-snug tracking-tight text-wl-text md:text-3xl">
            Grow with visibility.
            <br />
            Operate with control.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-wl-text-secondary">
            Nursery, production, quality and post-harvest in one traceable system.
          </p>

          <div className="mt-8 grid grid-cols-2 gap-x-6 gap-y-5">
            {VALUE_ITEMS.map(({ Icon, label, caption }) => (
              <div key={label} className="flex items-start gap-2.5">
                <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-wl-brand" />
                <div>
                  <p className="text-sm font-semibold text-wl-text">{label}</p>
                  <p className="text-xs text-wl-text-secondary">{caption}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AuthPanelWithReturnTo() {
  const searchParams = useSearchParams();
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));
  const encodedReturnTo = encodeURIComponent(returnTo);
  const organizationHref = `/auth/login?returnTo=${encodedReturnTo}`;
  const googleHref = `/auth/login?connection=${GOOGLE_CONNECTION}&returnTo=${encodedReturnTo}`;

  return <AuthPanel googleHref={googleHref} organizationHref={organizationHref} />;
}

const GRID_SHELL_CLASSES = "grid grid-cols-1 md:min-h-screen md:grid-cols-[39%_1fr] lg:grid-cols-[38%_1fr]";

export default function LoginPage() {
  return (
    <div className={GRID_SHELL_CLASSES}>
      <Suspense fallback={<AuthPanelFallback />}>
        <AuthPanelWithReturnTo />
      </Suspense>
      <ImagePanel />
    </div>
  );
}
