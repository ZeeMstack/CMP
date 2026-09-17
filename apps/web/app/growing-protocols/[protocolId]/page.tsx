"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ErrorState } from "@/components/ErrorState";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { StandaloneShell } from "@/components/StandaloneShell";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { AppError } from "@/lib/errors/adapter";
import { useCreateProtocolVersion, useGrowingProtocol, useProtocolVersions } from "@/lib/query/hooks";

function errorMessage(error: unknown): string {
  return error instanceof AppError ? error.message : "Something went wrong. Please try again.";
}

function versionStateTone(state: string): StatusTone {
  if (state === "active") return "active";
  if (state === "draft") return "attention";
  return "closed";
}

function versionActionLabel(state: string): string {
  if (state === "draft") return "Resume Draft";
  if (state === "active") return "View Active Version";
  return "View Retired Version";
}

/** PILOT-AGRO-001B Part 1: this Protocol's own shell fields plus its full
 * version catalog (draft/active/retired, backend's own ascending order) --
 * mirrors `app/workflows/[workflowId]/page.tsx`'s established shell/
 * catalog split exactly. "Create Draft Version" is always offered
 * alongside any already-resumable draft, never hidden -- the backend has
 * no uniqueness constraint preventing more than one concurrent draft. */
export default function GrowingProtocolShellPage() {
  const { protocolId } = useParams<{ protocolId: string }>();
  const router = useRouter();
  const [actionError, setActionError] = useState<string | null>(null);

  const protocolQuery = useGrowingProtocol(protocolId);
  const versionsQuery = useProtocolVersions(protocolId);
  const createDraft = useCreateProtocolVersion(protocolId);

  if (protocolQuery.isLoading) return <StandaloneShell><LoadingSkeleton rows={4} label="Loading protocol" /></StandaloneShell>;
  if (protocolQuery.error) {
    return (
      <StandaloneShell>
        <ErrorState error={protocolQuery.error} onRetry={() => protocolQuery.refetch()} />
      </StandaloneShell>
    );
  }
  const protocol = protocolQuery.data;
  if (!protocol) return null;

  const versions = versionsQuery.data ?? [];

  async function handleCreateDraft() {
    setActionError(null);
    const reason = window.prompt("Reason for this new draft version:");
    if (!reason || !reason.trim()) return;
    try {
      const version = await createDraft.mutateAsync({
        client_command_id: crypto.randomUUID(),
        reason: reason.trim(),
        effective_date: null,
      });
      router.push(`/growing-protocols/${protocolId}/versions/${version.id}`);
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  return (
    <StandaloneShell>
      <PageHeader
        title={protocol.name}
        description={protocol.code}
        breadcrumbs={
          <Breadcrumbs
            items={[
              { label: "Home", href: "/farms" },
              { label: "Growing Protocols", href: "/growing-protocols" },
              { label: protocol.code },
            ]}
          />
        }
        actions={
          <Button variant="primary" onClick={handleCreateDraft} disabled={createDraft.isPending}>
            {createDraft.isPending ? "Creating…" : "Create Draft Version"}
          </Button>
        }
      />

      {actionError && (
        <p role="alert" className="mb-4 text-xs text-danger-700">
          {actionError}
        </p>
      )}

      {versionsQuery.isLoading && <LoadingSkeleton rows={3} label="Loading versions" />}
      {versionsQuery.error && <ErrorState error={versionsQuery.error} onRetry={() => versionsQuery.refetch()} />}
      {versionsQuery.data && versions.length === 0 && (
        <p className="text-sm text-wl-text-secondary">No versions yet — create the first draft above.</p>
      )}
      {versions.length > 0 && (
        <ul className="divide-y divide-wl-border rounded-xl border border-wl-border bg-wl-surface-raised">
          {[...versions].reverse().map((version) => (
            <li key={version.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-wl-text">Version {version.version_number}</span>
                  <StatusBadge label={version.state} tone={versionStateTone(version.state)} />
                </div>
                <p className="mt-0.5 text-xs text-wl-text-secondary">{version.reason}</p>
              </div>
              <button
                type="button"
                onClick={() => router.push(`/growing-protocols/${protocolId}/versions/${version.id}`)}
                className="text-sm font-medium text-wl-brand hover:underline"
              >
                {versionActionLabel(version.state)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </StandaloneShell>
  );
}
