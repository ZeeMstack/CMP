"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { ReportIncidentForm } from "@/components/equipment-incidents/ReportIncidentForm";
import { AppError } from "@/lib/errors/adapter";
import { flattenLocationTree } from "@/lib/format/locationTree";
import { useAssets, useLocationsTree, useOpenEquipmentIncident } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

/** PILOT-ASSET-001: Report Incident -- reached either from the QR "Report
 * Incident" action (`?assetId=` locks the Asset, matching the exact href
 * `qr_service.py::_equipment_readiness_actions` builds) or a plain
 * navigation link with no preselection. */
export default function ReportEquipmentIncidentPage() {
  const { farmId } = useParams<{ farmId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const lockedAssetId = searchParams.get("assetId") ?? undefined;

  const assetsQuery = useAssets(farmId, "");
  const locationsTreeQuery = useLocationsTree(farmId);
  const openIncident = useOpenEquipmentIncident(farmId);
  const [serverError, setServerError] = useState<string | null>(null);

  const assetOptions = useMemo(
    () => (assetsQuery.data ?? []).map((a) => ({ id: a.id, label: `${a.name} (${a.code})` })),
    [assetsQuery.data],
  );
  const locationOptions = useMemo(
    () => flattenLocationTree(locationsTreeQuery.data ?? []).map((o) => ({ id: o.id, label: o.label })),
    [locationsTreeQuery.data],
  );

  const isLoading = assetsQuery.isLoading || locationsTreeQuery.isLoading;
  const loadError = assetsQuery.error ?? locationsTreeQuery.error;

  return (
    <div>
      <PageHeader
        title="Report Incident"
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: `/farms/${farmId}` },
              { label: "Equipment Incidents", href: `/farms/${farmId}/equipment-incidents` },
              { label: "Report Incident" },
            ]}
          />
        }
      />
      {isLoading && <LoadingSkeleton rows={5} label="Loading" />}
      {!isLoading && loadError && (
        <ErrorState
          error={loadError}
          onRetry={() => {
            assetsQuery.refetch();
            locationsTreeQuery.refetch();
          }}
        />
      )}
      {!isLoading && !loadError && (
        <ReportIncidentForm
          assets={assetOptions}
          locationOptions={locationOptions}
          lockedAssetId={lockedAssetId}
          isSubmitting={openIncident.isPending}
          serverError={serverError}
          onCancel={() => router.push(`/farms/${farmId}/equipment-incidents`)}
          onSubmit={(payload) => {
            setServerError(null);
            openIncident.mutate(payload, {
              onSuccess: (incident) => router.push(`/farms/${farmId}/equipment-incidents/${incident.id}`),
              onError: (error) => setServerError(errorMessage(error)),
            });
          }}
        />
      )}
    </div>
  );
}
