# Asset and Carrier Model

Full detail: `CMP_MASTER_SPEC.md` §2, §3.1; `CLAUDE.md` rule 4. This document summarizes the approved classification; it does not restate the spec.

## Distinct concepts

Fixed locations, mobile assets, crop carriers, and equipment are distinct record types (`CLAUDE.md` rule 4):

- **Asset** — a managed physical item, often mobile (e.g. trolley, seeder, scale). Assets can require maintenance tracking.
- **Carrier** — an identified object that holds crop/product and is replaceable (e.g. seed tray, cultivation plate, grow cube, grow bag, crate, carton).
- **Equipment** — performs work (e.g. seeder, printer, irrigation robot, packing line).
- **Location** — see `LOCATION_MODEL.md`.

A structure such as a table or gutter may have both a linked asset record (for maintenance) and a linked location record (for occupancy) — see `LOCATION_MODEL.md`.

## Germination trolley

The trolley is a **mobile asset**. Its shelves and slots are **relative positions belonging to the trolley**, not independent farm locations — a tray's effective location is derived through the trolley's slot and the trolley's current chamber position (`LOCATION_MODEL.md`).

## Grow bag

A grow bag is a **replaceable crop carrier only** — not an asset. It occupies a fixed grow-bag position (a location). The carrier and the position it occupies are separate records; the carrier can be replaced without affecting the position record. Any future maintenance or inventory treatment of grow bags (e.g. as a stock item in the input store) is handled separately from this classification and is not decided here.

## Grow tables and grow gutters

These have **linked asset and operational-location records**: the physical/maintainable structure is an asset; the occupiable positions it provides (table position, grow-bag position) are locations.
