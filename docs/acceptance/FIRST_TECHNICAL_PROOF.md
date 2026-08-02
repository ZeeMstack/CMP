# First Technical Proof — Acceptance Criteria

Source: `CMP_MASTER_SPEC.md` §13 "Current Technical Milestone". This proof must pass before any crop-planning dashboards or further feature work is built. Ten acceptance areas:

## 1. Tenant and farm creation
- **Given** an authenticated tenant admin, **when** Tenant A and Farm PB-01 are created, **then** both exist with correct `tenant_id` ownership and audit metadata.

## 2. Nursery and germination chamber creation
- **Given** Farm PB-01, **when** a nursery greenhouse and Germination Chamber GC-01 are created, **then** they exist as generic locations under the farm's location tree (no fixed-depth assumption).

## 3. Chamber position generation
- **Given** Chamber GC-01, **when** 20 chamber positions are generated, **then** 20 distinct occupiable location records exist, each linked to GC-01.

## 4. Trolley registration
- **Given** Farm PB-01, **when** Trolley GT-0001 is registered with 8 shelves × 5 slots, **then** it exists as a mobile asset with 40 relative slot positions belonging to the trolley (not independent farm locations).

## 5. Seed tray registration and slot assignment
- **Given** Trolley GT-0001, **when** Seed Tray ST-200-00001 is registered and placed at Shelf 03 / Slot 04, **then** an active occupancy record links the tray to that slot.

## 6. Trolley-to-chamber-position assignment
- **Given** Trolley GT-0001, **when** it is placed at Chamber Position 12, **then** an active occupancy record links the trolley to that position.

## 7. Scan and derived location
- **Given** a scan of Seed Tray ST-200-00001's QR token, **when** the lookup resolves via its `scan_identity` record, **then** the system returns the tray's complete derived location: `tray → trolley slot → trolley → chamber position`.

## 8. Movement preserves history
- **Given** Trolley GT-0001 is moved to a new chamber position, **when** the movement commits, **then** the tray's derived location reflects the new position **and** the prior occupancy period is retained as history (not overwritten).

## 9. Idempotent duplicate movement
- **Given** the same movement command is submitted twice with the same client-generated idempotency key, **when** both submissions are processed, **then** only one movement is applied and the duplicate is handled without creating a second state change or a second audit event.

## 10. Cross-tenant isolation
- **Given** Tenant B, **when** a user authenticated as Tenant B attempts to look up or scan any Tenant A record (farm, chamber, trolley, tray), **then** the request is rejected and no Tenant A data is returned, including via direct ID/token guessing.
