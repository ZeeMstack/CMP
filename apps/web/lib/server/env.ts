/** Shared server-only environment-variable helper. Never import this from
 * a "use client" module. */
export function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required server environment variable ${name}. See apps/web/.env.example.`);
  }
  return value;
}
