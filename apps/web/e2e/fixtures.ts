/** Static fixtures shaped exactly like the backend's real response schemas
 * (see lib/api/client.ts / lib/api/schema.gen.ts). Used only to intercept
 * browser-level requests to the same-origin /api proxy in
 * e2e/pilot-happy-path.spec.ts -- no real backend, no dev cmp database, is
 * ever touched by this test. Loosely mirrors the shape of the real pilot
 * dataset's PILOT-LOT-006/007/007A/007B scenario (open hold + placement,
 * split parent + inherited-origin children) without depending on it. */
import type { BatchOperationalContext } from "@/lib/api/client";
import type { AuthBootstrap } from "@/lib/auth/types";

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

/** A single-tenant, already-selected bootstrap -- AUTH-001B2's central
 * /api/auth/bootstrap must be mocked in every spec that renders anything
 * past the shell, since tenant-scoped hooks are `enabled: false` until a
 * tenant is selected (see lib/query/hooks.ts). */
export const authBootstrap: AuthBootstrap = {
  status: "authenticated",
  user: { id: "33333333-3333-3333-3333-333333333333", email: "pilot@example.com", displayName: "Pilot User" },
  memberships: [{ tenantId: farm.tenant_id, tenantCode: "PILOT", tenantName: "Pilot Tenant", roleCode: "tenant_admin" }],
  selectedTenantId: farm.tenant_id,
};

const crop = { id: "crop-1", code: "LETTUCE", common_name: "Lettuce" };
const variety = { id: "var-1", code: "ICE", name: "Iceberg" };

const growingStage = { id: "stage-growing", code: "GROWING", name: "Growing", is_terminal: false, stage_category: "production" };
// Deliberately named/coded with no hint of "harvest" -- proves the UI
// reads stage_category, never the display name/code.
const readyStage = { id: "stage-q7", code: "Q7", name: "Zulu Phase", is_terminal: false, stage_category: "harvest_ready" };

function segment(id: string, code: string, name: string) {
  return { id, code, name };
}

const GH1 = segment("gh1", "PILOT-GH01", "Greenhouse 01");
const GH1_ZA = segment("gh1-za", "PILOT-GH01-ZA", "Zone A");
const GH1_ZA_P1 = segment("gh1-za-p1", "PILOT-GH01ZA-P-01", "Position 01");
const GH1_ZA_P2 = segment("gh1-za-p2", "PILOT-GH01ZA-P-02", "Position 02");

const GH2 = segment("gh2", "PILOT-GH02", "Greenhouse 02");
const GH2_ZA = segment("gh2-za", "PILOT-GH02-ZA", "Zone A");
const GH2_ZA_P1 = segment("gh2-za-p1", "PILOT-GH02ZA-P-01", "Position 01");
const GH2_ZA_P2 = segment("gh2-za-p2", "PILOT-GH02ZA-P-02", "Position 02");

export const locationsTree = [
  {
    id: GH1.id,
    code: GH1.code,
    name: GH1.name,
    location_type_id: "type-greenhouse",
    status: "active",
    occupiable: false,
    children: [
      {
        id: GH1_ZA.id,
        code: GH1_ZA.code,
        name: GH1_ZA.name,
        location_type_id: "type-zone",
        status: "active",
        occupiable: false,
        children: [
          { id: GH1_ZA_P1.id, code: GH1_ZA_P1.code, name: GH1_ZA_P1.name, location_type_id: "type-position", status: "active", occupiable: true, children: [] },
          { id: GH1_ZA_P2.id, code: GH1_ZA_P2.code, name: GH1_ZA_P2.name, location_type_id: "type-position", status: "active", occupiable: true, children: [] },
        ],
      },
    ],
  },
  {
    id: GH2.id,
    code: GH2.code,
    name: GH2.name,
    location_type_id: "type-greenhouse",
    status: "active",
    occupiable: false,
    children: [
      {
        id: GH2_ZA.id,
        code: GH2_ZA.code,
        name: GH2_ZA.name,
        location_type_id: "type-zone",
        status: "active",
        occupiable: false,
        children: [
          { id: GH2_ZA_P1.id, code: GH2_ZA_P1.code, name: GH2_ZA_P1.name, location_type_id: "type-position", status: "active", occupiable: true, children: [] },
          { id: GH2_ZA_P2.id, code: GH2_ZA_P2.code, name: GH2_ZA_P2.name, location_type_id: "type-position", status: "active", occupiable: true, children: [] },
        ],
      },
    ],
  },
];

export const lot006: BatchOperationalContext = {
  id: "batch-lot-006",
  code: "LOT-006",
  crop,
  variety,
  state: "active",
  current_stage: growingStage,
  sowing_origins: [
    { source_batch_id: "batch-lot-006", source_batch_code: "LOT-006", sowing_event_id: "se-006", effective_time: "2026-06-08T08:00:00Z", seed_lot_id: "sl-006", seed_lot_code: "SEED-006" },
  ],
  sown_effective_time: "2026-06-08T08:00:00Z",
  placement: {
    active_carrier_count: 1,
    placed_carrier_count: 1,
    unplaced_carrier_count: 0,
    placements: [
      { carrier_id: "carrier-006", carrier_code: "PLATE-006", location_id: GH1_ZA_P1.id, location_code: GH1_ZA_P1.code, location_name: GH1_ZA_P1.name, path: [GH1, GH1_ZA, GH1_ZA_P1] },
    ],
    common_ancestor_path: [GH1, GH1_ZA, GH1_ZA_P1],
  },
  open_quality_hold_count: 1,
};

export const lot007: BatchOperationalContext = {
  id: "batch-lot-007",
  code: "LOT-007",
  crop,
  variety,
  state: "superseded",
  current_stage: readyStage,
  sowing_origins: [
    { source_batch_id: "batch-lot-007", source_batch_code: "LOT-007", sowing_event_id: "se-007", effective_time: "2026-05-18T08:00:00Z", seed_lot_id: "sl-007", seed_lot_code: "SEED-007" },
  ],
  sown_effective_time: "2026-05-18T08:00:00Z",
  placement: { active_carrier_count: 0, placed_carrier_count: 0, unplaced_carrier_count: 0, placements: [], common_ancestor_path: null },
  open_quality_hold_count: 0,
};

export const lot007a: BatchOperationalContext = {
  id: "batch-lot-007a",
  code: "LOT-007A",
  crop,
  variety,
  state: "active",
  current_stage: readyStage,
  sowing_origins: [
    { source_batch_id: "batch-lot-007", source_batch_code: "LOT-007", sowing_event_id: "se-007", effective_time: "2026-05-18T08:00:00Z", seed_lot_id: "sl-007", seed_lot_code: "SEED-007" },
  ],
  sown_effective_time: "2026-05-18T08:00:00Z",
  placement: {
    active_carrier_count: 1,
    placed_carrier_count: 1,
    unplaced_carrier_count: 0,
    placements: [
      { carrier_id: "carrier-007a", carrier_code: "PLATE-007A", location_id: GH2_ZA_P1.id, location_code: GH2_ZA_P1.code, location_name: GH2_ZA_P1.name, path: [GH2, GH2_ZA, GH2_ZA_P1] },
    ],
    common_ancestor_path: [GH2, GH2_ZA, GH2_ZA_P1],
  },
  open_quality_hold_count: 0,
};

export const lot007b: BatchOperationalContext = {
  ...lot007a,
  id: "batch-lot-007b",
  code: "LOT-007B",
  placement: {
    active_carrier_count: 1,
    placed_carrier_count: 1,
    unplaced_carrier_count: 0,
    placements: [
      { carrier_id: "carrier-007b", carrier_code: "PLATE-007B", location_id: GH2_ZA_P2.id, location_code: GH2_ZA_P2.code, location_name: GH2_ZA_P2.name, path: [GH2, GH2_ZA, GH2_ZA_P2] },
    ],
    common_ancestor_path: [GH2, GH2_ZA, GH2_ZA_P2],
  },
};

// state=active: only genuinely active batches (LOT-007 is superseded and
// deliberately excluded here, proving Home never inflates on superseded).
export const operationalSummaryActive = [lot006, lot007a, lot007b];
// state=all: every legitimate state, including the superseded split parent.
export const operationalSummaryAll = [lot006, lot007, lot007a, lot007b];

export const batchesById: Record<string, (typeof lot006)> = {
  [lot006.id]: lot006,
  [lot007.id]: lot007,
  [lot007a.id]: lot007a,
  [lot007b.id]: lot007b,
};

// The plain (non-operational) CropBatchRead-shaped detail each Batch Detail
// page load still needs (workflow/version/created time -- not part of the
// operational-summary contract).
export function cropBatchDetail(op: (typeof lot006)) {
  return {
    id: op.id,
    tenant_id: farm.tenant_id,
    farm_id: farm.id,
    code: op.code,
    workflow: { id: "wf-1", code: "WF", name: "Leafy Greens" },
    workflow_version_id: "wfv-1",
    version_number: 1,
    crop: op.crop,
    variety: op.variety,
    production_system: { id: "ps-1", code: "PS", name: "NFT" },
    state: op.state,
    current_stage: op.current_stage,
    created_effective_time: op.sown_effective_time,
    created_at: op.sown_effective_time,
    closed_effective_time: null,
    superseded_effective_time: op.state === "superseded" ? "2026-07-28T00:00:00Z" : null,
    superseded_by_batch_derivation_event_id: op.state === "superseded" ? "evt-split-007" : null,
    created_by_batch_derivation_event_id: op.code.startsWith("LOT-007") && op.code !== "LOT-007" ? "evt-split-007" : null,
  };
}

export function stageHistoryFor(op: (typeof lot006)) {
  return [{ id: `history-${op.id}`, stage: op.current_stage, entered_effective_time: op.sown_effective_time, exited_effective_time: null }];
}

export const lineageByBatchId: Record<string, { batch_id: string; parents: unknown[]; children: unknown[] }> = {
  [lot006.id]: { batch_id: lot006.id, parents: [], children: [] },
  [lot007.id]: {
    batch_id: lot007.id,
    parents: [],
    children: [
      { derivation_event_id: "evt-split-007", derivation_kind: "split", effective_time: "2026-07-28T00:00:00Z", batch: { id: lot007a.id, code: lot007a.code }, recorded_plant_quantity_total: 10, recorded_carrier_assignment_count: 1 },
      { derivation_event_id: "evt-split-007", derivation_kind: "split", effective_time: "2026-07-28T00:00:00Z", batch: { id: lot007b.id, code: lot007b.code }, recorded_plant_quantity_total: 10, recorded_carrier_assignment_count: 1 },
    ],
  },
  [lot007a.id]: {
    batch_id: lot007a.id,
    parents: [
      { derivation_event_id: "evt-split-007", derivation_kind: "split", effective_time: "2026-07-28T00:00:00Z", batch: { id: lot007.id, code: lot007.code }, recorded_plant_quantity_total: 10, recorded_carrier_assignment_count: 1 },
    ],
    children: [],
  },
  [lot007b.id]: {
    batch_id: lot007b.id,
    parents: [
      { derivation_event_id: "evt-split-007", derivation_kind: "split", effective_time: "2026-07-28T00:00:00Z", batch: { id: lot007.id, code: lot007.code }, recorded_plant_quantity_total: 10, recorded_carrier_assignment_count: 1 },
    ],
    children: [],
  },
};

export const qualityHoldsByBatchId: Record<string, unknown[]> = {
  [lot006.id]: [
    {
      id: "hold-006",
      tenant_id: farm.tenant_id,
      farm_id: farm.id,
      batch_id: lot006.id,
      stage: lot006.current_stage,
      source_observation_event_id: null,
      effective_time: "2026-07-01T08:00:00Z",
      recorded_time: "2026-07-01T08:00:00Z",
      actor_user_id: "user-1",
      client_command_id: "cmd-1",
      reason_code: "NUTRIENT_DEFICIENCY",
      reason_text: "Yellowing observed on lower leaves.",
      is_open: true,
      release: null,
    },
  ],
  [lot007.id]: [],
  [lot007a.id]: [],
  [lot007b.id]: [],
};

export const subtreeOccupancyByRootId: Record<string, unknown> = {
  [GH1.id]: {
    root_location_id: GH1.id,
    aggregate_counts: [
      { location_id: GH1.id, occupiable_location_count: 2, occupied_location_count: 1 },
      { location_id: GH1_ZA.id, occupiable_location_count: 2, occupied_location_count: 1 },
    ],
    occupied_locations: [
      {
        location_id: GH1_ZA_P1.id,
        occupant: {
          kind: "carrier",
          id: "carrier-006",
          carrier_code: "PLATE-006",
          batch: { batch_id: lot006.id, batch_code: lot006.code, crop, current_stage: growingStage },
        },
      },
    ],
  },
  [GH2.id]: {
    root_location_id: GH2.id,
    aggregate_counts: [
      { location_id: GH2.id, occupiable_location_count: 2, occupied_location_count: 2 },
      { location_id: GH2_ZA.id, occupiable_location_count: 2, occupied_location_count: 2 },
    ],
    occupied_locations: [
      {
        location_id: GH2_ZA_P1.id,
        occupant: {
          kind: "carrier",
          id: "carrier-007a",
          carrier_code: "PLATE-007A",
          batch: { batch_id: lot007a.id, batch_code: lot007a.code, crop, current_stage: readyStage },
        },
      },
      {
        location_id: GH2_ZA_P2.id,
        occupant: {
          kind: "carrier",
          id: "carrier-007b",
          carrier_code: "PLATE-007B",
          batch: { batch_id: lot007b.id, batch_code: lot007b.code, crop, current_stage: readyStage },
        },
      },
    ],
  },
};
