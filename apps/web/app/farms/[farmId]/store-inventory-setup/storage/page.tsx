"use client";

import { useParams } from "next/navigation";

import { ScopeLabel } from "@/components/store-inventory-setup/ScopeLabel";
import { StorageSection } from "@/components/stores/StorageSection";
import { useFarm } from "@/lib/query/hooks";

export default function StorageWorkspacePage() {
  const { farmId } = useParams<{ farmId: string }>();
  const { data: farm } = useFarm(farmId);

  return (
    <div>
      <ScopeLabel>For {farm ? farm.name : "this farm"}</ScopeLabel>
      <StorageSection farmId={farmId} />
    </div>
  );
}
