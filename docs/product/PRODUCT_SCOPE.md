# Product Scope

Full detail: `CMP_MASTER_SPEC.md` §1. This document summarizes boundaries for quick reference; it does not restate the spec.

## What CMP is

A multi-tenant operating and traceability platform for commercial hydroponic greenhouse farms. It builds a digital farm map and records how inputs, crop batches, carriers, harvest lots, pack lots, and finished goods move through it.

**Core promise:** complete forward and backward traceability from supplier lot to customer dispatch.

## Included

Nursery propagation; leafy-green and vine greenhouses; input store; production; quality; harvest; packing; finished-goods cold store; dispatch; recall. CMP-019 (`docs/domain/TRACEABILITY_MODEL.md`) implements the read-only backward-trace and forward-impact foundation for "recall"; CMP-020 (`docs/domain/RECALL_CONTAINMENT_MODEL.md`) adds the recall case/containment decision itself — an immutable case with a frozen scope and four write-path containment gates (batch derivation, packing, storage release, dispatch). Customer notification, regulatory submission, delivery recall, return processing, destruction/disposal, financial credit, CAPA, and investigation workflow remain future, separately-approved work.

PILOT-OPS-001 (`docs/domain/FARM_WORK_ITEM_MODEL.md`) adds a small operational work/assignment domain — the Farm Work Item — and "Today on the Farm" as the main authenticated operating screen for a farm. A Work Item never replaces the authoritative farm transaction it may relate to (harvest, observation, ...); it tracks assignment/status and, for transaction-backed work, links to the resulting record. Not a project-management, HR/payroll, or scheduling system.

PILOT-SCAN-001 (`docs/domain/QR_SCAN_MODEL.md`) makes physical GrowCMP identities scannable: printable QR labels for Carriers, Assets, Locations, Crop Batches, Batch Carrier Assignments ("placements"), Harvested/Graded Produce Lots, and Finished Goods Lots, plus an authenticated scan-and-resolve page. A QR identifies context only — scanning never executes a farm operation (move, harvest, record loss, release Quality, ...); it resolves current authoritative state and prepares links into the existing workflows that do.

PILOT-AGRO-001 (`docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md`) adds versioned Growing Protocols (what SHOULD agronomically happen, by crop/variety/production-system), Batch → Protocol Version assignment history, protocol-driven observation requirements and crop-care activities mapped to the existing generic `stage_category`, structured Grower Inspections (what a grower ACTUALLY observed, referencing — never duplicating — the existing Observation architecture), and Crop Issues with deliberate diagnosis-confirmation, Work-Item-linked corrective action, follow-up, and closure. A Protocol never proves an operation happened; age informs display/deviation only and never advances a Batch's stage, moves plants, or creates a farm event; a Crop Issue never reduces living crop quantity; suspected cause and confirmed diagnosis are permanently separate facts; completing a linked Farm Work Item never resolves the Issue.

PILOT-AGRO-001B (`docs/domain/GROWING_PROTOCOL_INSPECTION_MODEL.md`, "Operator frontend" section) builds the operator/grower-facing UI on that frozen backend: Growing Protocol administration, a Batch Protocol panel with deliberate Assign/Change confirmation, an Inspect Crop workspace (one Inspection, many Observation values, optional Findings, optional Open-Issue follow-through), a Crop Issue workspace (suspected cause vs. confirmed diagnosis kept visually separate; Resolve and Close as two deliberate commands), corrective-work assignment via the existing Farm Work Item creation flow (never a second task model), Today-on-the-Farm "Crop Attention"/"Inspections Due" live sections, and QR "Inspect Crop" scan-context wiring (a scan only prepares a link into the workspace — it never itself records an Inspection).

PILOT-WATER-001A (`docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md`) adds the hydroponic water/nutrient domain foundation: water topology (Water Source → Reservoir → Irrigation Circuit → Delivery Point → Drainage/Return Point → Return Reservoir), kept structurally separate from the physical Location hierarchy; effective-dated topology connections that preserve history; Sampling Points, Instruments, and immutable Calibration/Measurement records; a versioned Nutrient Recipe catalog (target only); actual Nutrient Mix, Reservoir adjustment, and Delivery records (each a distinct, independent fact from the Recipe target and from each other); and a read-only Crop Water Exposure model answering which Batch Placements potentially shared water with which Reservoir/Circuit over a time window. This is domain/API foundation only — manual/human-entered, no controller integration, no automatic dosing/irrigation, and exposure is always labelled potential, never a disease/contamination finding. PILOT-WATER-001B builds the operator-facing screens on this foundation.

PILOT-ASSET-001 (`docs/domain/EQUIPMENT_READINESS_MODEL.md`) adds an Equipment Readiness lifecycle (`UNKNOWN → AWAITING_CLEANING → CLEANING_COMPLETED → READY`, plus `DAMAGED`/`MAINTENANCE`/terminal `RETIRED`) for reusable Assets/Carriers whose type is configured `readiness_tracked` — kept deliberately separate from physical Occupancy (WHERE) and from the existing registry `status` (active/inactive/damaged/retired). A Carrier/Asset becoming empty never automatically becomes READY; cleaning being recorded never automatically means READY; existing "available X" allocation reads (Seed Trays, Nursery/Production Cultivation Plates, Germination Trolleys) are hardened to exclude non-ready equipment. A lightweight Critical Equipment Incident domain (`OPEN → ACKNOWLEDGED → ACTION_IN_PROGRESS → RESOLVED → CLOSED`) records equipment/system problems (pump, cooling, dosing, RO plant, germination chamber, seeding equipment, scale, cold store, ...), may optionally identify a "potentially impacted area" (never an inferred crop impact), and may link `FarmWorkItem`s for corrective action — completing a linked Work Item never resolves the Incident; resolution and closure are always deliberate, separate commands. Not a CMMS: no preventive-maintenance scheduling, spare-parts inventory, vendor management, or predictive analytics.

## Excluded unless separately approved

Open fields, livestock, orchards, GIS/satellite features, machinery telematics, payroll, accounting, invoicing, general ledger, and retail POS.

## Design constraint

The platform is crop-agnostic: new crops and workflows are configuration, never new code paths or crop-specific tables (`CLAUDE.md` rule 1).

## Future application structure

Planned repository layout uses `apps/api` (backend) and `apps/web` (frontend) — not yet created; this repository is documentation-only.
