"use client";

import { Boxes, ClipboardList, Scale, Warehouse } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PageHeader } from "@/components/PageHeader";

/** POSTHARVEST-OPS-001G: the Processing landing page -- clear access to
 * Grading, Graded Produce Lots, Packing, and Finished Goods, mirroring the
 * required operational flow (Harvested Produce Lot -> Grading -> Graded
 * Produce Lots -> Packing -> Finished Goods). No dashboard content here
 * (CLAUDE.md: no planning dashboards ahead of the location/movement proof) --
 * this is navigation only. */
export default function ProcessingLandingPage() {
  const { farmId } = useParams<{ farmId: string }>();

  const sections = [
    {
      href: `/farms/${farmId}/processing/grading`,
      icon: Scale,
      title: "Grading",
      description: "Grade a Harvested Produce Lot into one or more Graded Produce Lots.",
    },
    {
      href: `/farms/${farmId}/processing/graded-lots`,
      icon: Boxes,
      title: "Graded Produce Lots",
      description: "Browse Graded Produce Lots, their exact grade, and current available balance.",
    },
    {
      href: `/farms/${farmId}/processing/packing`,
      icon: ClipboardList,
      title: "Packing",
      description: "Pack Graded Produce Lots into Finished Goods Lots.",
    },
    {
      href: `/farms/${farmId}/processing/finished-goods`,
      icon: Warehouse,
      title: "Finished Goods",
      description: "Browse Finished Goods Lots, dispatch-readiness, and cold-store placement.",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Processing"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Processing" }]} />}
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {sections.map(({ href, icon: Icon, title, description }) => (
          <Link
            key={href}
            href={href}
            className="flex min-h-24 flex-col gap-1 rounded-xl border border-border-subtle bg-surface p-4 transition-colors hover:border-brand-300 hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <span className="flex items-center gap-2 font-serif text-sm font-semibold text-ink">
              <Icon aria-hidden="true" className="h-4 w-4 text-brand-700" />
              {title}
            </span>
            <span className="text-xs text-ink-muted">{description}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
