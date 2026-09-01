const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-surface-subtle text-ink-muted border-border-subtle",
  // Bright Mint tint with dark teal text (PILOT-UX-001A approved usage:
  // "prefer dark teal text/icons on mint backgrounds").
  active: "bg-mint-subtle text-brand-800 border-mint-border",
  attention: "bg-warning-100 text-warning-900 border-warning-200",
  closed: "bg-surface-subtle text-ink-muted border-border-subtle",
};

export type StatusTone = keyof typeof TONE_CLASSES;

export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: StatusTone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}
