"use client";

import { PlusCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { CapacityOutlookTable } from "@/components/planning/CapacityOutlookTable";
import { HarvestForecastTimeline } from "@/components/planning/HarvestForecastTimeline";
import { HarvestForecastWorksheetTable } from "@/components/planning/HarvestForecastWorksheetTable";
import { PlanningPeriodSelector } from "@/components/planning/PlanningPeriodSelector";
import { PlanningRiskList } from "@/components/planning/PlanningRiskList";
import { RequirementsTable } from "@/components/planning/RequirementsTable";
import { SeedingProgramTable } from "@/components/planning/SeedingProgramTable";
import { Tabs } from "@/components/ui/Tabs";
import { defaultPlanningPeriod } from "@/lib/format/planningPeriod";
import { useProductionRequirements, useRequirementHarvestOutlooks, useSeedingProgramLines } from "@/lib/query/hooks";

type PlanningTab = "overview" | "requirements" | "seeding-program" | "forecast" | "capacity";

/** PILOT-PLAN-001B: evolves the existing Planning workspace (PLANNING-OPS-001)
 * into a management worksheet -- adds Overview/Forecast/Capacity tabs
 * alongside the existing Requirements/Seeding Program tabs, rather than a
 * second Planning surface. DEMAND != PLAN != SOWN != FORECAST != HARVESTED
 * stays visually distinct throughout: the Requirements table's existing
 * Demand/Planned/Gap columns (seeding-plan coverage) are never replaced by
 * the new Forecast/Harvested/Outlook columns -- they render side by side. */
export default function PlanningPage() {
  const { farmId } = useParams<{ farmId: string }>();
  // Default tab stays "requirements" -- the existing landing experience --
  // rather than "overview", so this evolution never disrupts what a
  // returning user already expects to see first (CLAUDE.md: "do not
  // duplicate/disrupt already-existing planning screens" and "prefer
  // evolving the current Planning workspace"). Overview is one click away.
  const [tab, setTab] = useState<PlanningTab>("requirements");
  const [period, setPeriod] = useState(() => defaultPlanningPeriod());

  const requirementsQuery = useProductionRequirements(farmId);
  const linesQuery = useSeedingProgramLines(farmId);
  const openRequirements = useMemo(
    () => (requirementsQuery.data ?? []).filter((r) => r.status === "open"),
    [requirementsQuery.data],
  );
  const openRequirementIds = useMemo(() => openRequirements.map((r) => r.id), [openRequirements]);
  const outlooks = useRequirementHarvestOutlooks(farmId, openRequirementIds);

  return (
    <div>
      <PageHeader
        title="Planning"
        breadcrumbs={<Breadcrumbs items={[{ label: "Home", href: `/farms/${farmId}` }, { label: "Planning" }]} />}
        description="What crop do we need, how much, by when -- what we're planning to sow, what we expect to harvest, and where capacity is planned."
        actions={
          tab === "requirements" ? (
            <Link
              href={`/farms/${farmId}/planning/requirements/new`}
              className="flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wl-focus"
            >
              <PlusCircle aria-hidden="true" className="h-4 w-4" />
              Production requirement
            </Link>
          ) : undefined
        }
      />

      <Tabs
        aria-label="Planning"
        activeId={tab}
        onChange={(id) => setTab(id as PlanningTab)}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "requirements", label: "Requirements" },
          { id: "seeding-program", label: "Seeding Program" },
          { id: "forecast", label: "Forecast" },
          { id: "capacity", label: "Capacity" },
        ]}
      />

      <div className="mt-4">
        {tab === "overview" && (
          <div className="flex flex-col gap-6">
            <PlanningPeriodSelector start={period.start} end={period.end} onChange={setPeriod} />

            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">A. Requirement Coverage</h2>
              {requirementsQuery.isLoading && <LoadingSkeleton rows={3} label="Loading requirement coverage" />}
              {requirementsQuery.error && (
                <ErrorState error={requirementsQuery.error} onRetry={() => requirementsQuery.refetch()} />
              )}
              {requirementsQuery.data && openRequirements.length === 0 && (
                <EmptyState title="No open production requirements." />
              )}
              {requirementsQuery.data && openRequirements.length > 0 && (
                <RequirementsTable
                  requirements={openRequirements}
                  farmId={farmId}
                  outlookByRequirementId={outlooks.byRequirementId}
                  outlookLoading={outlooks.isLoading}
                />
              )}
            </section>

            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">B. Harvest Forecast</h2>
              <HarvestForecastWorksheetTable farmId={farmId} periodStart={period.start} periodEnd={period.end} />
            </section>

            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">C. Capacity Outlook</h2>
              <CapacityOutlookTable farmId={farmId} periodStart={period.start} periodEnd={period.end} />
            </section>

            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">D. Risks / Attention</h2>
              <PlanningRiskList farmId={farmId} periodStart={period.start} periodEnd={period.end} />
            </section>
          </div>
        )}

        {tab === "requirements" && (
          <>
            {requirementsQuery.isLoading && <LoadingSkeleton rows={4} label="Loading production requirements" />}
            {requirementsQuery.error && (
              <ErrorState error={requirementsQuery.error} onRetry={() => requirementsQuery.refetch()} />
            )}
            {requirementsQuery.data && requirementsQuery.data.length === 0 && (
              <EmptyState
                title="No production requirements yet."
                description="Create one to record how much of a crop the farm needs to produce, and by when."
                action={
                  <Link
                    href={`/farms/${farmId}/planning/requirements/new`}
                    className="mt-2 flex min-h-11 items-center gap-1.5 rounded-md bg-wl-brand px-3 text-sm font-medium text-wl-text-on-brand hover:bg-wl-brand-hover"
                  >
                    <PlusCircle aria-hidden="true" className="h-4 w-4" />
                    Production requirement
                  </Link>
                }
              />
            )}
            {requirementsQuery.data && requirementsQuery.data.length > 0 && (
              <RequirementsTable
                requirements={requirementsQuery.data}
                farmId={farmId}
                outlookByRequirementId={outlooks.byRequirementId}
                outlookLoading={outlooks.isLoading}
              />
            )}
          </>
        )}

        {tab === "seeding-program" && (
          <>
            {linesQuery.isLoading && <LoadingSkeleton rows={4} label="Loading the seeding program" />}
            {linesQuery.error && <ErrorState error={linesQuery.error} onRetry={() => linesQuery.refetch()} />}
            {linesQuery.data && linesQuery.data.length === 0 && (
              <EmptyState
                title="No planned sowings yet."
                description="Add a plan line from a Production Requirement to schedule a planned sowing against it."
              />
            )}
            {linesQuery.data && linesQuery.data.length > 0 && (
              <SeedingProgramTable lines={linesQuery.data} farmId={farmId} />
            )}
          </>
        )}

        {tab === "forecast" && (
          <div className="flex flex-col gap-6">
            <PlanningPeriodSelector start={period.start} end={period.end} onChange={setPeriod} />
            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">Harvest Forecast Worksheet</h2>
              <HarvestForecastWorksheetTable farmId={farmId} periodStart={period.start} periodEnd={period.end} />
            </section>
            <section>
              <h2 className="mb-2 font-serif text-base font-semibold text-wl-text">Weekly Timeline</h2>
              <HarvestForecastTimeline farmId={farmId} periodStart={period.start} periodEnd={period.end} />
            </section>
          </div>
        )}

        {tab === "capacity" && (
          <div className="flex flex-col gap-6">
            <PlanningPeriodSelector start={period.start} end={period.end} onChange={setPeriod} />
            <CapacityOutlookTable farmId={farmId} periodStart={period.start} periodEnd={period.end} />
          </div>
        )}
      </div>
    </div>
  );
}
