"use client";

import { AlertTriangle, CheckCircle2, MinusCircle, RefreshCw, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import type { FarmSetupReadinessItem, FarmSetupReadinessMilestone } from "@/lib/api/client";
import { useFarmSetupReadiness } from "@/lib/query/hooks";

/** PILOT-SETUP-001B8: item code -> the most useful EXISTING setup route for
 * that item, never a fabricated/dead link. Keyed by item code (not
 * milestone) since Full Pilot Readiness reuses the same item codes the
 * other three milestones already defined. */
function actionHrefFor(code: string, farmId: string): string | null {
  switch (code) {
    case "nursery_structure":
    case "nursery_intersalads_structure":
    case "leafy_production_structure":
      return `/farms/${farmId}/farm-setup`;
    case "crop_configured":
    case "variety_configured":
      return "/crops";
    case "production_system_configured":
      return "/production-systems";
    case "published_workflow":
      return "/workflows";
    case "seed_tray_specification":
    case "nursery_cultivation_plate_specification":
    case "production_cultivation_plate_specification":
      return "/carrier-specifications";
    case "physical_seed_trays":
    case "physical_nursery_cultivation_plates":
    case "physical_production_cultivation_plates":
      return `/farms/${farmId}/carriers`;
    case "seed_lot":
      return `/farms/${farmId}/seed-lots`;
    case "packing_hall_location":
    case "cold_store_location":
    case "cold_store_position_structure":
      return `/farms/${farmId}/locations`;
    case "grade_definition_active_version":
      return "/grade-definitions";
    case "packaging_unit_active":
      return "/packaging-units";
    case "pack_specification_active_version":
      return "/pack-specifications";
    default:
      return null;
  }
}

function ItemIcon({ status }: { status: FarmSetupReadinessItem["status"] }) {
  if (status === "pass") return <CheckCircle2 aria-hidden="true" className="h-5 w-5 shrink-0 text-emerald-600" />;
  if (status === "warning") return <AlertTriangle aria-hidden="true" className="h-5 w-5 shrink-0 text-amber-600" />;
  if (status === "not_applicable") return <MinusCircle aria-hidden="true" className="h-5 w-5 shrink-0 text-ink-muted" />;
  return <XCircle aria-hidden="true" className="h-5 w-5 shrink-0 text-red-600" />;
}

const STATUS_LABEL: Record<FarmSetupReadinessItem["status"], string> = {
  pass: "Configured",
  missing: "Missing",
  warning: "Needs attention",
  not_applicable: "Not applicable",
};

function ReadinessItemRow({ item, farmId }: { item: FarmSetupReadinessItem; farmId: string }) {
  const href = item.status !== "pass" && item.status !== "not_applicable" ? actionHrefFor(item.code, farmId) : null;
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="flex items-start gap-2">
        <ItemIcon status={item.status} />
        <div>
          <p className="text-sm font-medium text-ink">
            {item.label}
            <span className="sr-only"> — {STATUS_LABEL[item.status]}</span>
          </p>
          {item.detail && <p className="text-xs text-ink-muted">{item.detail}</p>}
        </div>
      </div>
      {href && (
        <Link
          href={href}
          className="shrink-0 whitespace-nowrap rounded-md border border-border-subtle bg-surface px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
        >
          Fix
        </Link>
      )}
    </li>
  );
}

function MilestoneCard({ milestone, farmId }: { milestone: FarmSetupReadinessMilestone; farmId: string }) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-serif text-base font-semibold text-ink">{milestone.label}</h2>
        <StatusBadge
          label={milestone.status === "ready" ? "Ready" : "Incomplete"}
          tone={milestone.status === "ready" ? "active" : "attention"}
        />
      </div>
      <ul className="divide-y divide-border-subtle">
        {milestone.items.map((item) => (
          <ReadinessItemRow key={item.code} item={item} farmId={farmId} />
        ))}
      </ul>
    </section>
  );
}

export default function FarmSetupReadinessPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data, isLoading, error, refetch, isFetching } = useFarmSetupReadiness(farmId);

  return (
    <div>
      <PageHeader
        title="Farm Setup Readiness"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Farm Setup", href: `/farms/${farmId}/farm-setup` },
              { label: "Setup Readiness" },
            ]}
          />
        }
        actions={
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex min-h-11 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-subtle disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
          >
            <RefreshCw aria-hidden="true" className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
        }
      />
      <p className="-mt-3 mb-6 text-xs text-ink-muted">
        This checklist reflects the Farm&apos;s actual configuration -- there is no manual completion; each item
        updates automatically as the underlying setup changes.
      </p>
      {isLoading && <LoadingSkeleton rows={4} label="Loading setup readiness" />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data.milestones.map((milestone) => (
            <MilestoneCard key={milestone.code} milestone={milestone} farmId={farmId} />
          ))}
        </div>
      )}
    </div>
  );
}
