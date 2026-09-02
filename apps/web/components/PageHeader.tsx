import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
}: {
  title: string;
  description?: ReactNode;
  breadcrumbs?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 border-b border-wl-border pb-5">
      {breadcrumbs}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="font-serif text-[28px] font-semibold leading-tight tracking-tight text-wl-text md:text-[32px]">
            {title}
          </h1>
          {description && <p className="max-w-[65ch] text-sm text-wl-text-secondary">{description}</p>}
        </div>
        {actions && <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
