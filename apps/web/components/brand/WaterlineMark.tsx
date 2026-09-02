/**
 * The Waterline brand mark (PILOT-UX-001A2-R2): a shoot rising through a
 * waterline, with a single leaf. Inline SVG so no external image asset is
 * needed. Kept to one instance per screen (the app shell) rather than a
 * repeated decorative motif -- see the ticket's Waterline Rules.
 *
 * Colors are the frozen brand palette: Canopy (stem), Deepwater (waterline),
 * Current (ripple), Chlorophyll (leaf -- reserved for the mark and genuine
 * biological/live status, never a generic UI fill).
 */
export function WaterlineMark({
  size = 28,
  compact = size <= 24,
  title,
  className,
}: {
  /** Rendered width/height in px. */
  size?: number;
  /** Drops the fainter background ripple for legibility at small sizes. */
  compact?: boolean;
  /** Accessible name. Omit (default) to render the mark as decorative. */
  title?: string;
  className?: string;
}) {
  const decorative = !title;

  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? "true" : undefined}
    >
      {title && <title>{title}</title>}
      {!compact && (
        <path
          d="M2 23c3-2.5 6-2.5 9 0s6 2.5 9 0s6-2.5 9 0"
          stroke="#2C8FB4"
          strokeWidth="1.6"
          strokeLinecap="round"
          fill="none"
          opacity="0.55"
        />
      )}
      <path
        d="M2 19.5c3-2.2 6-2.2 9 0s6 2.2 9 0s6-2.2 9 0"
        stroke="#145E7A"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M16 27.5c-.6-6 .4-12-1-17.5"
        stroke="#0E1519"
        strokeWidth="2.1"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M15 9.8c1.8-3.4 6-4.4 8.4-2.9-1 3.7-4.9 6.4-8.7 5.6-.4-.9-.3-1.8.3-2.7Z"
        fill="#35B37E"
      />
    </svg>
  );
}

/** Mark + "growCMP" wordmark lockup (light-background variant): "grow" in
 * Canopy, "CMP" in Deepwater -- deliberately restrained, never bright green
 * (see the ticket's rejection of the prior loud-green prototype). */
export function WaterlineWordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <WaterlineMark size={26} />
      <span className="font-serif text-base font-semibold leading-none tracking-tight">
        <span className="text-wl-canopy">grow</span>
        <span className="text-wl-deepwater">CMP</span>
      </span>
    </span>
  );
}
