/** Static fixtures shaped exactly like the backend's real response schemas
 * (see lib/api/client.ts / lib/api/schema.gen.ts). Used only to intercept
 * browser-level requests to the same-origin /api proxy in e2e/pilot-happy-path.spec.ts
 * -- no real backend, no dev cmp database, is ever touched by this test. */

export const farm = {
  id: "11111111-1111-1111-1111-111111111111",
  tenant_id: "22222222-2222-2222-2222-222222222222",
  code: "PILOT-01",
  name: "Pilot Test Farm",
  country_code: "AE",
  city_region: "Dubai",
  timezone: "Asia/Dubai",
  status: "active",
};

export const locationsTree = [
  {
    id: "33333333-3333-3333-3333-333333333333",
    code: "GH1",
    name: "Greenhouse 1",
    location_type_id: "44444444-4444-4444-4444-444444444444",
    status: "active",
    occupiable: false,
    children: [
      {
        id: "55555555-5555-5555-5555-555555555555",
        code: "ZA",
        name: "Zone A",
        location_type_id: "66666666-6666-6666-6666-666666666666",
        status: "active",
        occupiable: true,
        children: [],
      },
    ],
  },
];

export const cropBatch = {
  id: "77777777-7777-7777-7777-777777777777",
  tenant_id: farm.tenant_id,
  farm_id: farm.id,
  code: "BATCH-E2E-01",
  workflow: { id: "wf-1", code: "WF", name: "Leafy Greens" },
  workflow_version_id: "wfv-1",
  version_number: 1,
  crop: { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" },
  variety: { id: "var-1", code: "ICE", name: "Iceberg" },
  production_system: { id: "ps-1", code: "PS", name: "NFT" },
  state: "active",
  current_stage: { id: "stage-1", code: "GROW", name: "Growing", is_terminal: false },
  created_effective_time: "2026-01-01T08:00:00Z",
  created_at: "2026-01-01T08:00:00Z",
  closed_effective_time: null,
  superseded_effective_time: null,
  superseded_by_batch_derivation_event_id: null,
  created_by_batch_derivation_event_id: null,
};

export const stageHistory = [
  {
    id: "88888888-8888-8888-8888-888888888888",
    stage: cropBatch.current_stage,
    entered_effective_time: "2026-01-01T08:00:00Z",
    exited_effective_time: null,
  },
];

export const lineage = { batch_id: cropBatch.id, parents: [], children: [] };

export const qualityHolds: unknown[] = [];
