import Link from "next/link";
import type { ComponentProps } from "react";

const VARIANT_CLASSES = {
  primary: "border-transparent bg-wl-brand text-wl-text-on-brand hover:bg-wl-brand-hover",
  secondary: "border-wl-border-strong bg-wl-surface-raised text-wl-text hover:bg-wl-surface-hover",
} as const;

export type LinkButtonVariant = keyof typeof VARIANT_CLASSES;

/** A navigating sibling of components/ui/Button -- same base classes/
 * variants, but a real `<Link>` (never a `<button>` nested inside one) for
 * the platform-admin screens' several "go to another admin route" actions
 * (View Tenant, Back to Tenants, ...). */
export function LinkButton({
  variant = "secondary",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: LinkButtonVariant }) {
  return (
    <Link
      className={`inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border px-4 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
