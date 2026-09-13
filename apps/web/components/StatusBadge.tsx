const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-wl-surface-sunken text-wl-text-secondary",
  // Growing/active biological or "healthy configuration" state.
  active: "bg-wl-grow-bg text-wl-grow-fg",
  // Awaiting QC / hold.
  attention: "bg-wl-hold-bg text-wl-hold-fg",
  closed: "bg-wl-surface-sunken text-wl-text-secondary",
  // PILOT-UI-002 approved Critical tone -- hold/recall/blocked/rejected/
  // serious exceptions. Additive: no existing caller passes this tone yet,
  // so this does not change any current screen's rendering; call sites
  // that should adopt it are a separate, domain-judgment decision (which
  // specific statuses count as "serious"), out of this ticket's scope.
  critical: "bg-wl-flag-bg text-wl-flag-fg",
};

export type StatusTone = keyof typeof TONE_CLASSES;

export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: StatusTone }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-[3px] text-[11px] font-medium ${TONE_CLASSES[tone]}`}>
      {label}
    </span>
  );
}
