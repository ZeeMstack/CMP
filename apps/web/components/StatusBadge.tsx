const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-wl-surface-sunken text-wl-text-secondary",
  // Growing/active biological or "healthy configuration" state.
  active: "bg-wl-grow-bg text-wl-grow-fg",
  // Awaiting QC / hold.
  attention: "bg-wl-hold-bg text-wl-hold-fg",
  closed: "bg-wl-surface-sunken text-wl-text-secondary",
};

export type StatusTone = keyof typeof TONE_CLASSES;

export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: StatusTone }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-[3px] text-[11px] font-medium ${TONE_CLASSES[tone]}`}>
      {label}
    </span>
  );
}
