/**
 * Minimal CMP login page (AUTH-001B1). Deliberately no credential form --
 * Auth0 Universal Login performs all credential entry; this page only
 * links into the SDK-owned /auth/login route. No signup, no provider
 * chooser, no password-reset UI belongs here (see AUTH-001B audit §12).
 */
export default function LoginPage() {
  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl font-semibold text-brand-700">CMP</h1>
      <p className="mt-1 text-sm text-ink-muted">Commercial Hydroponic Operations</p>
      <a
        href="/auth/login"
        className="mt-8 inline-flex min-h-11 items-center justify-center rounded-md bg-brand-700 px-6 text-sm font-medium text-white hover:bg-brand-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
      >
        Sign in
      </a>
    </div>
  );
}
