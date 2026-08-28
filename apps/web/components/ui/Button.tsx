import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

const VARIANT_CLASSES = {
  primary: "border-brand-700 bg-brand-700 text-white hover:bg-brand-800",
  secondary: "border-border-subtle bg-surface text-ink hover:bg-surface-subtle",
  danger: "border-red-700 bg-red-700 text-white hover:bg-red-800",
} as const;

export type ButtonVariant = keyof typeof VARIANT_CLASSES;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

/** Minimal shared button primitive (UI-OPT-001 Batch A) -- covers the
 * variants existing pages already hand-roll. Screens keep their own
 * `<button>` markup until the batch that owns them migrates it; this does
 * not retroactively convert anything. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", type = "button", className = "", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border px-4 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-60 ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
});
