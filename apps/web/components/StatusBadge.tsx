const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-surface-subtle text-ink-muted border-border-subtle",
  active: "bg-brand-100 text-brand-800 border-brand-200",
  attention: "bg-amber-100 text-amber-900 border-amber-200",
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
