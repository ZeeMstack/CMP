import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

const VARIANT_CLASSES = {
  primary:
    "border-transparent bg-wl-brand text-wl-text-on-brand hover:bg-wl-brand-hover active:bg-wl-brand-pressed disabled:bg-wl-brand-disabled disabled:text-wl-text-tertiary disabled:hover:bg-wl-brand-disabled",
  secondary:
    "border-wl-border-strong bg-wl-surface-raised text-wl-text hover:bg-wl-surface-hover disabled:text-wl-text-tertiary disabled:hover:bg-wl-surface-raised",
  danger: "border-danger-700 bg-danger-700 text-white hover:bg-danger-800 disabled:opacity-60",
} as const;

export type ButtonVariant = keyof typeof VARIANT_CLASSES;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

/** Shared button primitive (PILOT-UX-001A2-R2 Waterline direction) --
 * restrained height/radius, Deepwater primary. Screens keep their own
 * hand-rolled `<button>`/`<Link>` markup until the batch that owns them
 * migrates it; this does not retroactively convert anything. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", type = "button", className = "", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border px-4 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus disabled:cursor-not-allowed ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
});
