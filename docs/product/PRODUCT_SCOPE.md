# Product Scope

Full detail: `CMP_MASTER_SPEC.md` §1. This document summarizes boundaries for quick reference; it does not restate the spec.

## What CMP is

A multi-tenant operating and traceability platform for commercial hydroponic greenhouse farms. It builds a digital farm map and records how inputs, crop batches, carriers, harvest lots, pack lots, and finished goods move through it.

**Core promise:** complete forward and backward traceability from supplier lot to customer dispatch.

## Included

Nursery propagation; leafy-green and vine greenhouses; input store; production; quality; harvest; packing; finished-goods cold store; dispatch; recall. CMP-019 (`docs/domain/TRACEABILITY_MODEL.md`) implements the read-only backward-trace and forward-impact foundation for "recall"; CMP-020 (`docs/domain/RECALL_CONTAINMENT_MODEL.md`) adds the recall case/containment decision itself — an immutable case with a frozen scope and four write-path containment gates (batch derivation, packing, storage release, dispatch). Customer notification, regulatory submission, delivery recall, return processing, destruction/disposal, financial credit, CAPA, and investigation workflow remain future, separately-approved work.

## Excluded unless separately approved

Open fields, livestock, orchards, GIS/satellite features, machinery telematics, payroll, accounting, invoicing, general ledger, and retail POS.

## Design constraint

The platform is crop-agnostic: new crops and workflows are configuration, never new code paths or crop-specific tables (`CLAUDE.md` rule 1).

## Future application structure

Planned repository layout uses `apps/api` (backend) and `apps/web` (frontend) — not yet created; this repository is documentation-only.
