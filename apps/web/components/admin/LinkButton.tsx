import Link from "next/link";
import type { ComponentProps } from "react";

const VARIANT_CLASSES = {
  primary: "border-brand-700 bg-brand-700 text-white hover:bg-brand-800",
  secondary: "border-border-subtle bg-surface text-ink hover:bg-surface-subtle",
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
      className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border px-4 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
