class DomainError(Exception):
    """Base class for application-level domain errors mapped to HTTP by routers."""


class DuplicateTenantCodeError(DomainError):
    pass


class DuplicateUserIdentityError(DomainError):
    pass


class DuplicateMembershipError(DomainError):
    pass


class AdminIdentityEmailMismatchError(DomainError):
    """PILOT-SETUP-001B2: platform Tenant onboarding resolved an existing
    User by exact (oidc_issuer, oidc_subject) match, but the caller-supplied
    email does not match that User's own already-recorded email. Never
    silently overwritten -- the identity binding a Platform Admin is
    administratively vouching for must not be allowed to quietly retarget an
    unrelated person's account."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DuplicateFarmCodeError(DomainError):
    pass


class FarmNotFoundError(DomainError):
    pass


class LocationNotFoundError(DomainError):
    pass


class LocationTypeNotFoundError(DomainError):
    pass


class InactiveParentLocationError(DomainError):
    pass


class InvalidLocationHierarchyError(DomainError):
    pass


class DuplicateLocationCodeError(DomainError):
    pass


class AssetTypeNotFoundError(DomainError):
    pass


class CarrierTypeNotFoundError(DomainError):
    pass


class AssetNotFoundError(DomainError):
    pass


class CarrierNotFoundError(DomainError):
    pass


class DuplicateAssetCodeError(DomainError):
    pass


class DuplicateCarrierCodeError(DomainError):
    pass


class CarrierSpecificationNotFoundError(DomainError):
    pass


class DuplicateCarrierSpecificationCodeError(DomainError):
    pass


class CarrierSpecificationTypeMismatchError(DomainError):
    """Raised when a `carrier_type_code` and a `specification_id` are both
    supplied to Carrier registration but resolve to different CarrierTypes,
    or when a specification update's `carrier_type_code` disagrees with its
    own current `carrier_type_id`."""


class CarrierSpecificationInactiveError(DomainError):
    pass


class CarrierSpecificationRequiredError(DomainError):
    pass


class CarrierSpecificationStructurallyLockedError(DomainError):
    """Raised when a structural field (carrier_type, code, dimensions,
    biological_position_count) would change on a CarrierSpecification that
    at least one Carrier already references."""


class CarrierSpecificationValidationError(DomainError):
    """Raised when a specification-required CarrierType's specification is
    missing its minimum required dimensions/biological_position_count."""


class PositionsNotSupportedError(DomainError):
    pass


class InvalidPositionHierarchyError(DomainError):
    pass


class DuplicatePositionCodeError(DomainError):
    pass


class AssetPositionNotFoundError(DomainError):
    pass


class InactiveOccupantError(DomainError):
    pass


class InactiveTargetError(DomainError):
    pass


class TargetNotOccupiableError(DomainError):
    pass


class IncompatibleOccupantTargetError(DomainError):
    pass


class AssetCannotOccupyOwnPositionError(DomainError):
    pass


class TargetOccupiedError(DomainError):
    pass


class OccupantAlreadyActiveError(DomainError):
    pass


class NoOpMovementError(DomainError):
    pass


class NothingToRemoveError(DomainError):
    pass


class MovementCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InvalidEffectiveTimeError(DomainError):
    pass


class CropNotFoundError(DomainError):
    pass


class DuplicateCropCodeError(DomainError):
    pass


class VarietyNotFoundError(DomainError):
    pass


class DuplicateVarietyCodeError(DomainError):
    pass


class ProductionSystemNotFoundError(DomainError):
    pass


class DuplicateProductionSystemCodeError(DomainError):
    pass


class WorkflowNotFoundError(DomainError):
    pass


class DuplicateWorkflowCodeError(DomainError):
    pass


class VarietyCropMismatchError(DomainError):
    pass


class WorkflowVersionNotFoundError(DomainError):
    pass


class WorkflowVersionNotDraftError(DomainError):
    pass


class WorkflowStageNotFoundError(DomainError):
    pass


class DuplicateStageCodeError(DomainError):
    pass


class LocationTypeReferenceNotFoundError(DomainError):
    pass


class CarrierTypeReferenceNotFoundError(DomainError):
    pass


class DuplicateTransitionCodeError(DomainError):
    pass


class DuplicateTransitionPairError(DomainError):
    pass


class SelfTransitionError(DomainError):
    pass


class CropBatchNotFoundError(DomainError):
    pass


class DuplicateBatchCodeError(DomainError):
    pass


class BatchCommandReusedWithDifferentPayloadError(DomainError):
    pass


class WorkflowInactiveError(DomainError):
    pass


class WorkflowHasNoPublishedVersionError(DomainError):
    pass


class BatchCreationValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CropBatchClosedError(DomainError):
    pass


class ConfiguredTransitionNotFoundError(DomainError):
    pass


class StageMismatchError(DomainError):
    pass


class InvalidBatchEffectiveTimeError(DomainError):
    pass


class StageVersionMismatchError(DomainError):
    pass


class WorkflowPublicationValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DuplicateSeedLotCodeError(DomainError):
    pass


class SeedLotNotFoundError(DomainError):
    pass


class SeedLotValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SowingEventNotFoundError(DomainError):
    pass


class SowingCommandReusedWithDifferentPayloadError(DomainError):
    pass


class SowingValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CarrierAlreadyAssignedError(DomainError):
    pass


class InvalidSowingEffectiveTimeError(DomainError):
    pass


class TooManySowingLinesError(DomainError):
    pass


class SowingCapacityExceededError(DomainError):
    """CARRIER-CONFIG-001B: raised when a Sowing line's `sown_site_count`
    exceeds its Carrier's CarrierSpecification.biological_position_count.
    Only ever raised when both facts are actually known (a NULL
    specification_id or a NULL biological_position_count skips this check
    entirely -- see `sowing_service._sow_batch_core`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BatchCarrierAssignmentNotFoundError(DomainError):
    pass


class BatchAlreadySownError(DomainError):
    """NURSERY-OPS-001: a Crop Batch may have at most one Sowing Event,
    ever -- enforced by `ux_sowing_events_batch_id` (DB-level). Raised when
    a genuinely new sowing command (a client_command_id not already tied to
    an existing SowingEvent) targets a batch that already has one."""

    pass


class MixedSeedLotInSowingCommandError(DomainError):
    """NURSERY-OPS-001.1: every line of one Sowing Event must reference the
    SAME Seed Lot -- enforced here (before any row is written) and again at
    the DB layer (`enforce_sowing_event_line_insert_integrity`). Raised when
    a sowing command's lines reference more than one distinct seed_lot_id."""

    pass


class SeedingStationInvalidError(DomainError):
    """NURSERY-OPS-001: the referenced location is not an active
    `seeding_station` under a Nursery-classified Greenhouse in this
    tenant/farm."""

    pass


class SeedingMachineInvalidError(DomainError):
    """NURSERY-OPS-001: the referenced asset is not an active
    `seeding_machine` in this tenant/farm."""

    pass


class NoSowingWorkflowFoundError(DomainError):
    """NURSERY-OPS-001: no active workflow, with a published version whose
    seeding-category start stage requires seed_tray carriers, matches the
    selected Seed Lot's crop/variety."""

    pass


class GerminationChamberInvalidError(DomainError):
    """NURSERY-OPS-002A: the referenced location is not an active, occupiable
    `germination_chamber` under a Nursery-classified Greenhouse in this
    tenant/farm."""

    pass


class GerminationTrolleyInvalidError(DomainError):
    """NURSERY-OPS-002A: the referenced asset is not an active
    `germination_trolley` in this tenant/farm."""

    pass


class GerminationTraySlotInvalidError(DomainError):
    """NURSERY-OPS-002A / PILOT-UX-001B: the referenced AssetPosition is not
    a valid Seed Tray placement target for the selected Germination
    Trolley -- covers a `slot` that does not belong to the Trolley, a
    `shelf` that is not itself a valid Level target (e.g. it is a
    `legacy_level`, meaning it has child Slots and must be targeted through
    one of those Slots instead, never directly), or any other position kind."""

    pass


class GerminationLevelNotConfiguredError(DomainError):
    """PILOT-UX-001B: the referenced Level (`shelf`-kind AssetPosition) has
    zero child Slots AND `capacity IS NULL` -- an `invalid_level`. This is a
    Farm Setup configuration gap, never a valid one-tray placement target;
    NULL capacity must not be silently treated as capacity=1 for a Level."""

    pass


class GerminationPlacementMustUseGerminationOperationError(DomainError):
    """PILOT-UX-001B section 5: a Seed Tray Carrier may only be placed onto
    a Germination Trolley AssetPosition (Level or legacy Slot) through this
    module's own Germination placement operation -- never through the
    generic movement endpoint, which has no Germination-specific validation
    (sown-state, Trolley-currently-in-Chamber)."""

    pass


class TrayNotSownError(DomainError):
    """NURSERY-OPS-002A: the referenced carrier has no active
    sowing-origin BatchCarrierAssignment -- it is not a Sown Seed Tray."""

    pass


class TrolleyNotInGerminationError(DomainError):
    """NURSERY-OPS-002A: a Seed Tray may only be placed into a Trolley Slot
    while that Trolley itself currently occupies a valid Germination Chamber
    -- the generic Movement primitive would otherwise happily place a tray
    onto a Trolley sitting nowhere (or outside Germination) and call it
    "Germination placement", which this Germination-specific orchestration
    must not permit."""

    pass


class AmbiguousSowingWorkflowError(DomainError):
    """NURSERY-OPS-001: more than one candidate workflow matches the
    selected Seed Lot's crop/variety -- resolution is ambiguous, and this
    command never guesses which one an operator meant."""

    pass


class DuplicateObservationDefinitionCodeError(DomainError):
    pass


class ObservationDefinitionNotFoundError(DomainError):
    pass


class ObservationDefinitionValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ObservationEventNotFoundError(DomainError):
    pass


class ObservationCommandReusedWithDifferentPayloadError(DomainError):
    pass


class ObservationValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidObservationEffectiveTimeError(DomainError):
    pass


class TooManyObservationEntriesError(DomainError):
    pass


class QualityHoldNotFoundError(DomainError):
    pass


class QualityHoldCommandReusedWithDifferentPayloadError(DomainError):
    pass


class QualityHoldValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidQualityHoldEffectiveTimeError(DomainError):
    pass


class QualityHoldAlreadyReleasedError(DomainError):
    pass


class QualityHoldOpenError(DomainError):
    pass


class TransplantEventNotFoundError(DomainError):
    pass


class TransplantCommandReusedWithDifferentPayloadError(DomainError):
    pass


class TransplantValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidTransplantEffectiveTimeError(DomainError):
    pass


class SourceAssignmentNotFoundError(DomainError):
    pass


class SourceAssignmentAlreadyReleasedError(DomainError):
    pass


class DestinationCarrierAlreadyAssignedError(DomainError):
    pass


class TooManyTransplantLinesError(DomainError):
    pass


class SourceAssignmentHasNoSeedlingEntryError(DomainError):
    """NURSERY-OPS-004A section 5/21: modern transplant source authority
    derives entirely from SeedlingEntry + SeedlingDispositionEvents +
    SeedlingSourceCheckpoints -- a source assignment with no SeedlingEntry
    at all has no authoritative source quantity 004A can derive, and is
    rejected outright (never bounded against `sown_site_count`, never
    substituted with `seed_count`)."""
    pass


class TransplantCapacityExceededError(DomainError):
    """NURSERY-OPS-004B.1: raised when a Transplant destination line's
    `assigned_plant_count` exceeds its Carrier's CarrierSpecification.
    biological_position_count. Only ever raised when both facts are
    actually known and positive -- see `transplant_service.
    _record_transplant_core`. Distinct from `TransplantValidationError`,
    which covers the adjacent but different case of a required-
    specification destination Carrier missing/lacking a valid capacity
    fact at all (structural registration problem, not a quantity
    comparison)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IntersaladsTransplantCommandReusedWithDifferentPayloadError(DomainError):
    pass


class IntersaladsTransplantReplayStateConflictError(DomainError):
    """NURSERY-OPS-004B.1: raised on an exact-fingerprint replay of a
    composite InterSalads Transplant command whose underlying, previously-
    recorded per-destination Movement state cannot be reconstructed exactly
    as expected (a derived Movement command id resolves to no Movement at
    all, or to one whose occupant/destination does not match the requested
    destination Carrier/Location). This should be unreachable in normal
    operation -- every derived Movement id is created in the same
    transaction as the TransplantEvent it accompanies -- and exists only so
    a genuinely corrupted or externally-tampered-with state surfaces as a
    clear domain error rather than a silently wrong or fabricated replay
    response."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InsufficientAvailableGrowCubesError(DomainError):
    """VINES-OPS-001A: raised when an InterVines Transplant command requests
    more Grow Cubes than are currently available (active, unassigned) in
    the farm -- optionally scoped to one CarrierSpecification -- under lock.
    Raised before any write (no TransplantEvent, TransplantDestinationLine,
    or Movement row is ever created), so the caller's outer transaction has
    nothing to roll back: the whole command atomically fails closed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IntervinesTransplantReplayStateConflictError(DomainError):
    """VINES-OPS-001A: raised on a replay of a composite InterVines
    Transplant command (same `client_command_id`) whose already-committed
    Grow Cube placements cannot be reconciled with the replay request --
    either the previously-recorded `TransplantEvent`'s own destination lines
    don't match the requested `plant_count`/`source_assignment_id`/
    `destination_location_id`/`grow_cube_specification_id`, or a derived
    per-Grow-Cube Movement command id resolves to no Movement at all, or to
    one whose occupant/destination does not match. Mirrors
    `IntersaladsTransplantReplayStateConflictError`'s own role exactly, for
    the pool-allocated (server-chosen destination Carrier) shape this
    composite command uses instead of client-supplied destination Carrier
    ids."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BatchDerivationEventNotFoundError(DomainError):
    pass


class BatchDerivationCommandReusedWithDifferentPayloadError(DomainError):
    pass


class BatchDerivationValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidBatchDerivationEffectiveTimeError(DomainError):
    pass


class SourceBatchAlreadySupersededError(DomainError):
    pass


class TooManyBatchDerivationLinesError(DomainError):
    pass


class HarvestEventNotFoundError(DomainError):
    pass


class HarvestCommandReusedWithDifferentPayloadError(DomainError):
    pass


class HarvestValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidHarvestEffectiveTimeError(DomainError):
    pass


class TooManyHarvestLinesError(DomainError):
    pass


class DuplicateProduceLotCodeError(DomainError):
    pass


class HarvestedProduceLotNotFoundError(DomainError):
    pass


class HarvestSourceAssignmentNotFoundError(DomainError):
    pass


class PackingEventNotFoundError(DomainError):
    pass


class PackingCommandReusedWithDifferentPayloadError(DomainError):
    pass


class PackingValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidPackingEffectiveTimeError(DomainError):
    pass


class TooManyPackingInputLinesError(DomainError):
    pass


class PackingInputGradedProduceLotNotFoundError(DomainError):
    pass


class PackingCropVarietyMismatchError(DomainError):
    """Raised when input GradedProduceLots do not all share one exact
    crop/variety, or when the (already-mutually-consistent) input set does
    not match the referenced PackSpecification's own crop/variety scope."""

    pass


class PackingGradeVersionMismatchError(DomainError):
    """Raised when input GradedProduceLots do not all share one exact
    grade_definition_version_id, or when they do but it does not match the
    referenced PackSpecificationVersion's own pinned grade version (when
    one is set)."""

    pass


class PackSpecificationVersionNotUsableError(DomainError):
    """Raised when a PackingEvent references a PackSpecificationVersion
    that is draft, or whose [effective_from, effective_until) business
    window does not contain the event's own effective_time -- current
    recorded-time status is never consulted."""

    pass


class InsufficientGradedProduceLotBalanceError(DomainError):
    pass


class DuplicateFinishedGoodsLotCodeError(DomainError):
    pass


class FinishedGoodsLotNotFoundError(DomainError):
    pass


class DispatchEventNotFoundError(DomainError):
    pass


class DispatchCommandReusedWithDifferentPayloadError(DomainError):
    pass


class DispatchValidationError(DomainError):
    pass


class InvalidDispatchEffectiveTimeError(DomainError):
    pass


class DispatchFinishedGoodsLotNotFoundError(DomainError):
    pass


class DuplicateDispatchCodeError(DomainError):
    pass


class InsufficientFinishedGoodsBalanceError(DomainError):
    pass


class StorageLocationNotFoundError(DomainError):
    pass


class IneligibleStorageLocationError(DomainError):
    pass


class InactiveDestinationLocationError(DomainError):
    pass


class StorageMovementValidationError(DomainError):
    pass


class StorageCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InvalidStorageMovementEffectiveTimeError(DomainError):
    pass


class InsufficientUnplacedQuantityError(DomainError):
    pass


class InsufficientStorageLocationBalanceError(DomainError):
    pass


class TraceabilityIntegrityError(DomainError):
    """Raised when a traceability traversal encounters a state the schema's
    own invariants should make impossible: a lineage cycle, a required-edge
    reference that resolves to nothing, or a defensive recursion-depth
    guard being hit. Never raised for a legitimately empty or historically
    incomplete branch -- those are reported as limitations, not errors."""

    pass


class RecallCaseNotFoundError(DomainError):
    pass


class RecallCaseCommandReusedWithDifferentPayloadError(DomainError):
    pass


class RecallCaseValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidRecallCaseEffectiveTimeError(DomainError):
    pass


class DuplicateRecallCaseCodeError(DomainError):
    pass


class RecallCaseAlreadyClosedError(DomainError):
    pass


class RecallScopeStabilizationError(DomainError):
    """Raised when the recall-opening batch-descendant closure fails to
    stabilize within the defensive round bound -- a corruption/pathological-
    race guard only, never a normal business limit. Mirrors
    `TraceabilityIntegrityError`'s own fail-loud-never-silent contract."""

    pass


class RecallContainmentOpenError(DomainError):
    """Raised when a write operation (derivation, packing, storage release,
    dispatch) targets a crop batch, harvested produce lot, or finished-goods
    lot currently contained by an open recall case."""

    pass


class FarmSetupCommandReusedWithDifferentPayloadError(DomainError):
    pass


class FarmSetupValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SeedlingTableInvalidError(DomainError):
    """NURSERY-OPS-003A: the referenced location is not an active, occupiable
    `seedling_table` under a Nursery-classified Greenhouse in this
    tenant/farm."""

    pass


class SeedlingEntryValidationError(DomainError):
    """NURSERY-OPS-003A: the referenced assignment is not eligible for a
    Seedling entry (e.g. not a seed_tray carrier)."""

    pass


class NoCompletedGerminationHandoffError(DomainError):
    """NURSERY-OPS-003A: no completed GerminationOutcomeSnapshot exists for
    this assignment at or before the Seedling entry's effective_time --
    section 10/41: a Seedling entry can never substitute a provisional
    snapshot, Seeds Sown, or Sown Sites for a genuine completed handoff."""

    pass


class SeedlingEntryAlreadyExistsError(DomainError):
    """NURSERY-OPS-003A: section 8/22 -- at most one SeedlingEntry may ever
    exist for a given BatchCarrierAssignment. A later physical Movement
    (e.g. a future Table-to-Table move) is not another biological entry."""

    pass


class SeedlingEntryCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InvalidSeedlingEntryEffectiveTimeError(DomainError):
    pass


class SeedlingEntryPhysicalChronologyError(DomainError):
    """NURSERY-OPS-003A.1: the Tray's own physical Movement history has
    already advanced past the requested effective_time (a later Movement --
    through this command or a bare generic one -- already moved it
    somewhere else) -- a new Movement dated at/before that point would
    falsify already-recorded physical chronology. Movement itself is
    append-forward only (`movement_service._execute_movement_core` already
    rejects `effective_time` preceding the occupant's current active
    Occupancy); this error exists so that rejection surfaces through the
    SeedlingEntry command as an actionable domain error (422) instead of
    the underlying generic `InvalidEffectiveTimeError` propagating
    unmapped."""

    pass


class NoSeedlingEntryError(DomainError):
    """NURSERY-OPS-003B: the referenced assignment has no SeedlingEntry yet
    -- a biological disposition can only be recorded against a Tray that has
    genuinely entered Seedling operations (NURSERY-OPS-003A)."""

    pass


class SeedlingDispositionValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidSeedlingDispositionReasonError(DomainError):
    """NURSERY-OPS-003B: the reason_code is not one of the platform-seeded,
    Seedling-stage-approved codes (explicitly excludes NON_GERMINATION and
    TRANSPLANT_DAMAGE, which belong to Germination and future transplant
    reconciliation respectively -- never Seedling disposition)."""

    pass


class SeedlingDispositionAssignmentReleasedError(DomainError):
    """NURSERY-OPS-003B section 0.E/29: a NEW disposition or correction
    command is only permitted while the source BatchCarrierAssignment is
    still currently active -- a deliberate, temporary MVP safeguard until a
    future Seedling->InterSalads/InterVines handoff ticket freezes its own
    downstream input quantity. Exact replay of an already-successful command
    remains valid regardless (checked before this validation)."""

    pass


class InvalidSeedlingDispositionEffectiveTimeError(DomainError):
    pass


class SeedlingDispositionBalanceError(DomainError):
    """NURSERY-OPS-003B: the proposed event would drive the chronological
    running balance for this SeedlingEntry below zero or above the frozen
    starting quantity at some effective-time point -- checked service-side
    for a clean domain error; independently re-verified by the DB trigger
    (`enforce_seedling_disposition_event_insert_integrity`) as defense in
    depth against a direct-SQL bypass."""

    pass


class SeedlingDispositionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class SeedlingDispositionEventNotFoundError(DomainError):
    pass


class SeedlingDispositionNotReductionError(DomainError):
    """NURSERY-OPS-003B section 21/22: only a REDUCTION event may ever be
    the target of a correction/reversal -- a REVERSAL can never itself be
    corrected (chain stays flat)."""

    pass


class SeedlingDispositionPredatesCheckpointError(DomainError):
    """NURSERY-OPS-004A section 6/25: a disposition event whose own
    `effective_time` is at or before the latest `SeedlingSourceCheckpoint`
    for its `seedling_entry_id` has already been consumed into a
    downstream, immutable transplant handoff -- it may never be newly
    corrected (a REVERSAL sharing that event's own effective_time would
    retroactively change an already-frozen checkpoint boundary). Deliberately
    distinct from `SeedlingDispositionAssignmentReleasedError` -- the
    assignment may still be fully active (partial transplant, remainder >
    0); the reason this correction is blocked is that the fact itself
    predates a checkpoint, not that the assignment is released."""
    pass


class SeedlingDispositionAlreadyCorrectedError(DomainError):
    """NURSERY-OPS-003B section 21: a REDUCTION may be reversed/corrected at
    most once, ever."""

    pass


class TransplantCorrectionValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TransplantCorrectionTargetKindNotEligibleError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 2: only a RECORD or REPLACEMENT
    transplant event may ever be the direct target of a correction -- a
    REVERSAL may never itself be corrected."""

    pass


class TransplantAlreadyCorrectedError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 4: a given TransplantEvent may be
    directly corrected (reversed) at most once, ever."""

    pass


class TransplantCorrectionStageMismatchError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 20: correction is only eligible
    while the Batch's current active BatchStageRun.id still equals the
    target event's own active_batch_stage_run_id -- comparing only stage
    category is not sufficient (a batch that left and later re-entered an
    equivalent stage in another run remains ineligible)."""

    pass


class TransplantCorrectionNotChainTipError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 21: every SeedlingSourceCheckpoint
    created by the target Transplant must still be the structural chain
    tip for its seedling_entry_id -- a later Transplant, Seedling
    Disposition, or other checkpoint activity on an involved source blocks
    correction."""

    pass


class TransplantCorrectionDestinationConsumedError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 21: a target destination
    assignment already released/consumed by another biological lifecycle
    (e.g. Batch Derivation) blocks correction -- unless that release is
    being performed by this very correction."""

    pass


class TransplantCorrectionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class TransplantCorrectionReplayStateConflictError(DomainError):
    """TRANSPLANT-CORRECTION-001 section 28: an exact-fingerprint replay of
    a correction command whose underlying, previously-recorded REVERSAL/
    REPLACEMENT state cannot be reconstructed exactly as expected. Should
    be unreachable in normal operation -- exists so a genuinely corrupted
    or externally-tampered-with state surfaces as a clear domain error
    rather than a silently wrong replay response."""

    pass


class BatchStageHasUnresolvedSeedlingRemainderError(DomainError):
    """WORKFLOW-INTEGRITY-001: a CropBatch may not leave a BatchStageRun
    whose WorkflowStage has stage_category == 'transplanting' while any
    SeedlingEntry belonging to it still has positive current source
    availability (the structural SeedlingSourceCheckpoint chain-tip anchor
    plus applicable SeedlingDispositionEvent deltas, evaluated as of the
    transition's own effective_time -- never BatchCarrierAssignment release
    state, destination biology, or physical Movement/Occupancy). Partial
    Transplant remains legal; only leaving the transplanting stage while
    living remainder is unresolved is blocked."""

    def __init__(self, *, unresolved_source_count: int, total_unresolved_living_count: int) -> None:
        self.unresolved_source_count = unresolved_source_count
        self.total_unresolved_living_count = total_unresolved_living_count
        super().__init__(
            "Batch cannot leave the transplanting stage while living seedling remainder remains "
            f"unresolved ({total_unresolved_living_count} across {unresolved_source_count} source(s))"
        )


class SeedlingDispositionCorrectionStageContextUnavailableError(DomainError):
    """SEEDLING-DISPOSITION-LIFECYCLE-001 section 15/19: the target
    correction's own originating command predates this ticket's migration
    and therefore has no recorded `active_batch_stage_run_id` -- safe
    historical stage context is unavailable, and it is never inferred from
    the current assignment's `batch_stage_run_id`, the batch's current
    stage, event `effective_time`, or human stage labels. Correction is
    rejected outright rather than fabricating certainty."""

    pass


class SeedlingDispositionCorrectionStageMismatchError(DomainError):
    """SEEDLING-DISPOSITION-LIFECYCLE-001 section 15: correction of a
    Seedling Disposition event is only legal while the CropBatch's current
    active BatchStageRun is still exactly the same run active when the
    target's own owning command was recorded -- applies to every
    correction, exhausting or not, original or replacement. Closes the gap
    where a Disposition exhausts biology, the Batch legitimately leaves
    the transplanting stage (WORKFLOW-INTEGRITY-001), and a later
    correction would otherwise silently restore living biology into a
    stage the Batch has already left."""

    pass


class SeedlingDispositionCarrierReusedError(DomainError):
    """SEEDLING-DISPOSITION-LIFECYCLE-001 section 17/22: the physical Seed
    Tray Carrier this correction would restore biology onto has since been
    assigned to a later, unrelated use (`Carrier.latest_batch_carrier_
    assignment_id` no longer points to the released predecessor) --
    physical continuity with the old seedlings has been broken, and this
    remains blocked even if that later use has itself since been released
    and the Carrier is currently free again."""

    pass


class UnsupportedTransplantSourceCarrierTypeError(DomainError):
    """NURSERY-OPS-005A: a source assignment's Carrier is of a type not
    currently eligible to act as a Transplant source at all -- distinct
    from `SourceAssignmentHasNoSeedlingEntryError` (an ELIGIBLE seed_tray
    type that happens to have no resolvable SeedlingEntry). Initially:
    seed_tray and nursery_cultivation_plate are eligible;
    production_cultivation_plate and every other carrier type are not
    (having a population authority does not by itself imply Transplant-
    source eligibility -- see `transplant_source_authority`)."""

    pass


class TransplantCorrectionCarrierReusedError(DomainError):
    """NURSERY-OPS-005A: the physical Carrier a Transplant correction would
    restore biology onto has since been assigned to a later, unrelated use
    (`Carrier.latest_batch_carrier_assignment_id` no longer points to the
    released predecessor being restored) -- the same protection
    `SeedlingDispositionCarrierReusedError` already provides for Disposition
    correction, applied consistently to every Transplant correction
    restoration path (Seed-Tray-backed and Nursery-Plate-backed alike).
    Remains blocked even if that later use has itself since been released
    and the Carrier is currently free again."""

    pass


class BatchStageHasUnresolvedPreProductionRemainderError(DomainError):
    """NURSERY-OPS-005A: a CropBatch may not TRANSITION INTO a
    stage_category == 'production' stage while any supported pre-production
    biological source still has positive current availability -- Seed Tray
    (SeedlingEntry/SeedlingSourceCheckpoint authority) and Nursery
    Cultivation Plate (BatchCarrierAssignment/BatchCarrierPopulation
    Checkpoint authority) alike, evaluated as of the transition's own
    effective_time. Production Cultivation Plate population is deliberately
    excluded (that biology has already arrived in production); a released
    or already-exhausted pre-production source never blocks. Distinct from,
    and does not replace, `BatchStageHasUnresolvedSeedlingRemainderError`
    (which guards LEAVING a transplanting-category stage) -- mixed Nursery+
    Production physical placement remains legal right up until this
    specific transition is attempted."""

    def __init__(self, *, unresolved_source_count: int, total_unresolved_living_count: int) -> None:
        self.unresolved_source_count = unresolved_source_count
        self.total_unresolved_living_count = total_unresolved_living_count
        super().__init__(
            "Batch cannot transition into a production stage while unresolved pre-production biological "
            f"remainder remains ({total_unresolved_living_count} across {unresolved_source_count} source(s))"
        )


class LeafyProductionTransferReplayStateConflictError(DomainError):
    """NURSERY-OPS-005B: raised on an exact-fingerprint replay of a
    composite Leafy Production Transfer command whose underlying,
    previously-recorded per-destination Movement state cannot be
    reconstructed exactly as expected (a derived Movement command id
    resolves to no Movement at all, or to one whose occupant/destination
    does not match the requested destination Carrier/Location) -- the exact
    same semantic state `IntersaladsTransplantReplayStateConflictError`
    already covers for its own composite, kept as a distinct class only
    because it names a genuinely different command. This should be
    unreachable in normal operation and exists only so a genuinely
    corrupted or externally-tampered-with state surfaces as a clear domain
    error rather than a silently wrong or fabricated replay response."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProductionDispositionValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidProductionDispositionReasonError(DomainError):
    pass


class InvalidProductionDispositionEffectiveTimeError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProductionDispositionAssignmentReleasedError(DomainError):
    """LEAFY-OPS-001: a NEW disposition RECORD command may only target the
    currently-active BCA generation of a population lineage -- mirrors
    SeedlingDispositionAssignmentReleasedError's own MVP safeguard."""


class ProductionDispositionBalanceError(DomainError):
    """LEAFY-OPS-001: the proposed event would drive the chronological
    running authoritative living-population balance for this population
    lineage below zero or above the root's own opening quantity at some
    effective-time point -- checked service-side (defense-in-depth against
    the DB's own CHECK-violation backstop)."""


class ProductionDispositionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class ProductionDispositionEventNotFoundError(DomainError):
    pass


class ProductionDispositionNotReductionError(DomainError):
    """LEAFY-OPS-001: only a REDUCTION event may ever be the target of a
    correction/reversal -- a REVERSAL can never itself be corrected."""


class ProductionDispositionAlreadyCorrectedError(DomainError):
    """LEAFY-OPS-001: a REDUCTION may be reversed/corrected at most once,
    ever."""


class ProductionDispositionCarrierReusedError(DomainError):
    """LEAFY-OPS-001: the physical Production Cultivation Plate Carrier this
    correction would restore population onto has since been assigned to a
    later, unrelated use (`Carrier.latest_batch_carrier_assignment_id` no
    longer points to the predecessor being restored) -- mirrors
    SeedlingDispositionCarrierReusedError's own guard exactly."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NoPopulationRootError(DomainError):
    """LEAFY-OPS-001: the referenced BatchCarrierAssignment has no
    `population_root_batch_carrier_assignment_id` -- it is not a
    Transplant-destination-anchored population lineage member (e.g. a
    sowing-origin or batch-derivation-origin assignment), so Production
    Biological Disposition cannot be recorded against it."""


class UnsupportedProductionDispositionCarrierTypeError(DomainError):
    """LEAFY-OPS-001: Production Biological Disposition is only ever
    recorded against a `production_cultivation_plate`-typed Carrier's
    BatchCarrierAssignment -- the underlying population-root/ledger
    mechanism is carrier-agnostic, but the V1 service layer deliberately
    keeps this narrow (mirrors NURSERY-OPS-005B's own destination-type
    allowlist)."""


# --- HARVEST-OPS-001 --------------------------------------------------------------


class UnsupportedHarvestSourceCarrierTypeError(DomainError):
    """HARVEST-OPS-001: a Leafy Harvest source line is only ever recorded
    against a `production_cultivation_plate`-typed Carrier's
    BatchCarrierAssignment -- mirrors
    UnsupportedProductionDispositionCarrierTypeError exactly. Generic
    CMP-013 `record_harvest` has no such restriction and is unaffected."""


class HarvestPopulationInsufficientError(DomainError):
    """HARVEST-OPS-001: a Leafy Harvest source line's `whole_unit_count`
    either exceeds the Production Cultivation Plate's own current
    authoritative living population, or that population is already zero --
    heads/weight are never invented, and Harvest may never harvest more
    biology than is actually alive."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HarvestSourceLineNotFoundError(DomainError):
    pass


class HarvestCorrectionValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HarvestCorrectionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class HarvestCorrectionAlreadySupersededError(DomainError):
    """HARVEST-OPS-001: the correction predecessor (the original
    HarvestSourceLine, or a specific prior correction) the caller believes
    is current has already been superseded by another correction -- the
    caller must refresh and re-review, never silently retarget to the newer
    tip (mirrors the concurrency-conflict contract established for
    Production Disposition/InterSalads corrections)."""


class HarvestLedgerBalanceError(DomainError):
    """HARVEST-OPS-001: this correction's produce-lot ledger adjustment
    would leave the HarvestedProduceLot's own available balance negative --
    some quantity has already been consumed downstream in Packing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HarvestCarrierReusedError(DomainError):
    """HARVEST-OPS-001: the physical Production Cultivation Plate Carrier a
    Harvest correction would restore population onto has since been
    assigned to a later, unrelated use (`Carrier.latest_batch_carrier_
    assignment_id` no longer points to the predecessor being restored) --
    mirrors ProductionDispositionCarrierReusedError exactly."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- POSTHARVEST-OPS-001A ----------------------------------------------------------


class GradeDefinitionNotFoundError(DomainError):
    pass


class DuplicateGradeDefinitionCodeError(DomainError):
    pass


class GradeDefinitionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class GradeDefinitionVersionNotFoundError(DomainError):
    pass


class GradeDefinitionVersionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class GradeDefinitionVersionNotDraftError(DomainError):
    """Raised when ACTIVATE targets a version that is not currently draft
    (already active, already retired, or -- on an exact-fingerprint replay
    check -- some other command's version)."""


class GradeDefinitionVersionActivationReusedWithDifferentPayloadError(DomainError):
    pass


class GradeDefinitionVersionNotActiveError(DomainError):
    """Raised when RETIRE targets a version that is not currently active."""


class GradeDefinitionVersionRetirementReusedWithDifferentPayloadError(DomainError):
    pass


class InvalidGradeDefinitionVersionEffectiveTimeError(DomainError):
    """Raised for any of: an activation/retirement effective_time in the
    future; a retirement effective_time before its own version's
    effective_from; an activation effective_time before the version it
    would replace's own effective_from (an invalid window for the version
    being retired by replacement)."""


# --- POSTHARVEST-OPS-001B ----------------------------------------------------------


class PackagingUnitNotFoundError(DomainError):
    pass


class DuplicatePackagingUnitCodeError(DomainError):
    pass


class PackagingUnitCommandReusedWithDifferentPayloadError(DomainError):
    pass


class PackagingUnitRetirementReusedWithDifferentPayloadError(DomainError):
    pass


class PackagingUnitNotActiveError(DomainError):
    """Raised when RETIRE targets a PackagingUnit that is not currently
    active, or when a new PackSpecificationVersion is created referencing
    a PackagingUnit that is not currently active."""


class PackSpecificationNotFoundError(DomainError):
    pass


class DuplicatePackSpecificationCodeError(DomainError):
    pass


class PackSpecificationCommandReusedWithDifferentPayloadError(DomainError):
    pass


class PackSpecificationVersionNotFoundError(DomainError):
    pass


class PackSpecificationVersionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class PackSpecificationVersionValidationError(DomainError):
    """Generic domain-validation bucket for a PackSpecificationVersion
    create command -- mirrors this codebase's established one-class-per-
    command "ValidationError(reason)" idiom (e.g. PackingValidationError,
    HarvestValidationError). Covers: both pack-measure fields NULL, a
    non-positive nominal_net_weight_kg/whole_units_per_pack, a referenced
    GradeDefinitionVersion still in DRAFT, and a referenced
    GradeDefinitionVersion whose own GradeDefinition crop/variety scope is
    incompatible with the parent PackSpecification's stable scope."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PackSpecificationVersionNotDraftError(DomainError):
    """Raised when ACTIVATE targets a version that is not currently draft."""


class PackSpecificationVersionActivationReusedWithDifferentPayloadError(DomainError):
    pass


class PackSpecificationVersionNotActiveError(DomainError):
    """Raised when RETIRE targets a version that is not currently active."""


class PackSpecificationVersionRetirementReusedWithDifferentPayloadError(DomainError):
    pass


class InvalidPackSpecificationVersionEffectiveTimeError(DomainError):
    """Raised for any of: an activation/retirement effective_time in the
    future; a retirement effective_time before its own version's
    effective_from; an activation effective_time before the version it
    would replace's own effective_from."""


# --- POSTHARVEST-OPS-001C ----------------------------------------------------------


class GradingEventNotFoundError(DomainError):
    pass


class GradingCommandReusedWithDifferentPayloadError(DomainError):
    pass


class GradingValidationError(DomainError):
    """Generic domain-validation bucket for the record-grading command --
    mirrors PackingValidationError's own established shape. Covers: zero
    output lines with no reject/loss/sample either (a true no-op),
    duplicate exact grade-version outputs, non-positive output weight,
    zero processed weight (input_presented == remainder), weight/count
    reconciliation mismatch, invalid count mode, and source availability
    exceeded."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidGradingEffectiveTimeError(DomainError):
    pass


class TooManyGradingOutputsError(DomainError):
    pass


class GradingSourceProduceLotNotFoundError(DomainError):
    pass


class ProcessingHallLocationInvalidError(DomainError):
    """The referenced location is not an active `packing_hall`-typed
    Location in this tenant/farm."""


class DuplicateGradedProduceLotCodeError(DomainError):
    pass


class GradedProduceLotNotFoundError(DomainError):
    pass


class InsufficientHarvestedProduceLotBalanceError(DomainError):
    """Raised when input_presented_weight_kg (or count) exceeds the
    source HarvestedProduceLot's current available ledger balance --
    compared against the full PRESENTED quantity, never merely the
    processed quantity."""


# --- POSTHARVEST-OPS-001H ----------------------------------------------------------


class GradingReversalEventNotFoundError(DomainError):
    pass


class GradingReversalCommandReusedWithDifferentPayloadError(DomainError):
    pass


class GradingReversalValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidGradingReversalEffectiveTimeError(DomainError):
    pass


class GradingEventAlreadyReversedError(DomainError):
    """POSTHARVEST-OPS-001H: a GradingEvent may be reversed at most once,
    ever -- enforced by `ux_grading_reversal_events_grading_event_id`
    (DB-level)."""


class GradingReversalBlockedByActivePackingError(DomainError):
    """POSTHARVEST-OPS-001H: at least one output GradedProduceLot of the
    target GradingEvent is still consumed by an ACTIVE (non-reversed)
    PackingEvent -- the safe unwind order is Packing reversal first, then
    Grading reversal. A PackingEvent that has itself already been reversed
    does not block."""


class PackingReversalEventNotFoundError(DomainError):
    pass


class PackingReversalCommandReusedWithDifferentPayloadError(DomainError):
    pass


class PackingReversalValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InvalidPackingReversalEffectiveTimeError(DomainError):
    pass


class PackingEventAlreadyReversedError(DomainError):
    """POSTHARVEST-OPS-001H: a PackingEvent may be reversed at most once,
    ever -- enforced by `ux_packing_reversal_events_packing_event_id`
    (DB-level)."""


class PackingReversalBlockedByDownstreamActivityError(DomainError):
    """POSTHARVEST-OPS-001H: the target PackingEvent's own FinishedGoodsLot
    has either (a) any `FinishedGoodsLedgerEntry` beyond its own
    `packing_receipt` (currently only `dispatch_issue` exists, checked
    generically by `entry_kind` so any future kind is covered too), or (b)
    any `finished_goods_storage_movements` row at all, regardless of net
    placement -- a lot placed and later fully released nets to zero but the
    custody fact still happened and is never undone by any row in that
    table. Neither dispatch nor storage placement/release has a reversal
    mechanism in this ticket's scope, so neutralizing the lot's opening
    quantity out from under any confirmed downstream fact is refused
    outright -- never inferred safe from a live/net balance alone."""


# --- STORE-INV-001B: master data & Store foundation -------------------------


class InventoryCategoryNotFoundError(DomainError):
    pass


class DuplicateInventoryCategoryCodeError(DomainError):
    pass


class InventoryCategoryCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryCategoryDeactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryCategoryReactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryCategoryNotActiveError(DomainError):
    """Raised when DEACTIVATE targets an `InventoryCategory` that is not
    currently active."""


class InventoryCategoryNotInactiveError(DomainError):
    """Raised when REACTIVATE targets an `InventoryCategory` that is not
    currently inactive."""


class InventoryItemNotFoundError(DomainError):
    pass


class DuplicateInventoryItemCodeError(DomainError):
    pass


class InventoryItemCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemUpdateReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemDeactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemReactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemNotActiveError(DomainError):
    """Raised when DEACTIVATE targets an `InventoryItem` that is not
    currently active."""


class InventoryItemNotInactiveError(DomainError):
    """Raised when REACTIVATE targets an `InventoryItem` that is not
    currently inactive."""


class InventoryCategoryNotInTenantError(DomainError):
    """Raised when a supplied `inventory_category_id` does not resolve to
    an `InventoryCategory` owned by the caller's own tenant."""


class InventoryCategoryInactiveForAssignmentError(DomainError):
    """Raised when creating an InventoryItem, or reassigning an existing
    one, to an `InventoryCategory` that is not currently active -- mirrors
    `CarrierSpecificationInactiveError`'s own precedent. Never raised for
    an InventoryItem's own already-assigned category simply becoming
    inactive later; that combination remains permanently valid
    (docs/domain/STORE_INVENTORY_MODEL.md §5 -- category deactivation is
    never blocked by existing references)."""


class UnitOfMeasureNotFoundError(DomainError):
    """Raised when a supplied `base_uom_id` does not resolve to a known,
    system-seeded `UnitOfMeasure`."""


class InventoryItemTrackingPolicyInvalidError(DomainError):
    """Raised when `expiry_tracking_required`/`qc_release_required` is
    `true` while `lot_tracking_required` is `false` -- both are
    `InventoryLot`-level concepts and meaningless on non-lot-tracked
    material (`docs/domain/STORE_INVENTORY_MODEL.md` §5)."""


class LocationUpdateReusedWithDifferentPayloadError(DomainError):
    pass


class LocationDeactivationReusedWithDifferentPayloadError(DomainError):
    pass


class LocationReactivationReusedWithDifferentPayloadError(DomainError):
    pass


class LocationNotActiveError(DomainError):
    """Raised when DEACTIVATE targets a `Location` that is not currently
    active."""


class LocationNotInactiveError(DomainError):
    """Raised when REACTIVATE targets a `Location` that is not currently
    inactive."""


class LocationHasActiveOccupancyError(DomainError):
    """Raised when DEACTIVATE targets a `Location` that currently has one
    or more active `Occupancy` rows (docs/domain/LOCATION_MODEL.md,
    "Location maintenance lifecycle"). Closed/historical occupancy never
    raises this."""


class LocationHasActiveChildrenError(DomainError):
    """Raised when DEACTIVATE targets a `Location` that has one or more
    directly active child `Location` rows -- deactivation is explicit and
    non-cascading; the operator must retire the hierarchy bottom-up."""


class LocationParentNotActiveError(DomainError):
    """Raised when REACTIVATE targets a `Location` whose parent is not
    currently active."""


# --- STORE-INV-002A.1: InventoryItemPackaging ------------------------------

class InventoryItemPackagingNotFoundError(DomainError):
    pass


class DuplicateInventoryItemPackagingCodeError(DomainError):
    pass


class InventoryItemPackagingCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemPackagingUpdateReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemPackagingDeactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemPackagingReactivationReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemPackagingNotActiveError(DomainError):
    """Raised when DEACTIVATE targets an `InventoryItemPackaging` that is
    not currently active, or when a receipt line references an inactive
    packaging row."""


class InventoryItemPackagingNotInactiveError(DomainError):
    """Raised when REACTIVATE targets an `InventoryItemPackaging` that is
    not currently inactive."""


class InventoryItemPackagingStructurallyLockedError(DomainError):
    """Raised when an update attempts to change `package_quantity` once any
    `GoodsReceiptLine` already references this packaging row (mirrors
    `CarrierSpecificationStructurallyLockedError`)."""


class InventoryItemPackagingItemMismatchError(DomainError):
    """Raised when a `GoodsReceiptLine` references a packaging row that
    does not belong to the same `InventoryItem` as the line itself."""


# --- STORE-INV-002A.1: InventoryItemSeedProfile ("Seed Details") ----------

class InventoryItemSeedProfileNotFoundError(DomainError):
    pass


class InventoryItemSeedProfileAlreadyExistsError(DomainError):
    """Raised on CREATE when the `InventoryItem` already has a Seed
    Details row (at most one, ever, at a time)."""


class InventoryItemSeedProfileCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryItemSeedProfileStructurallyLockedError(DomainError):
    """Raised on UPDATE or removal once the `InventoryItem` has any posted
    `GoodsReceiptLine` -- Seed Details become fully immutable at that point
    (docs/domain/STORE_INVENTORY_MODEL.md §15/§F)."""


class InventoryItemSeedProfileCreationBlockedError(DomainError):
    """Raised on CREATE when the `InventoryItem` already has posted receipt
    history but never had Seed Details -- a historically non-seed item can
    never retroactively become one."""


# --- STORE-INV-002A.1: InventoryLot ----------------------------------------

class InventoryLotNotFoundError(DomainError):
    pass


class ConflictingInventoryLotIdentityError(DomainError):
    """Raised when a receipt line's `(manufacturer_name,
    manufacturer_lot_reference)` matches an existing `InventoryLot`'s
    canonical identity, but `manufacturing_date`/`expiry_date` disagree
    (a NULL-vs-known mismatch, or two different known values) --
    GrowCMP never silently creates a second lot under the same canonical
    identity and never silently merges disagreeing attribute facts."""


# --- STORE-INV-002A.1: Goods Receipt ---------------------------------------

class GoodsReceiptNotFoundError(DomainError):
    pass


class GoodsReceiptCommandReusedWithDifferentPayloadError(DomainError):
    pass


class GoodsReceiptLineValidationError(DomainError):
    """Raised for any structural problem with a single receipt line
    (invalid UOM/packaging entry shape, unknown UOM, tracking-policy
    violation, etc.) -- the whole receipt is rejected atomically."""


class GoodsReceiptItemNotActiveError(DomainError):
    """Raised when a receipt line references an `InventoryItem` that is not
    currently `active` -- an inactive item cannot receive new stock."""


class InventoryItemPolicyFrozenError(DomainError):
    """Raised when an update attempts to change `base_uom_id`/
    `lot_tracking_required`/`expiry_tracking_required`/`qc_release_required`
    once the `InventoryItem` has any posted `GoodsReceiptLine` -- the
    first-posted-receipt structural freeze (docs/domain/
    STORE_INVENTORY_MODEL.md §T)."""


# --- STORE-INV-002A.1: Quantity Cohort / Existence Ledger ------------------

class InventoryQuantityCohortNotFoundError(DomainError):
    pass


class InventoryExistenceLedgerEntryNotFoundError(DomainError):
    pass


class InsufficientCohortBalanceError(DomainError):
    """Raised when an adjustment, reversal, or split allocation would drive
    a cohort's current balance negative."""


class InventoryAdjustmentCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryExistenceReversalCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryExistenceReversalTargetAlreadyReversedError(DomainError):
    """Raised when a reversal targets a ledger entry that already has a
    reversal of its own -- at most one reversal per target, no
    reversal-of-reversal."""


class InventoryExistenceReversalOfReversalError(DomainError):
    """Raised when a reversal's own target is itself a `reversal` entry --
    the flat-chain invariant."""


class InventoryQuantityCohortSplitAllocationExceedsBalanceError(DomainError):
    """Raised when a split's total requested allocation exceeds the source
    cohort's current balance."""


# --- STORE-INV-002A.2: Quality disposition ---------------------------------

class InvalidQualityDispositionTransitionError(DomainError):
    """Raised when a requested disposition (or correction replacement) is
    not a legal transition from the cohort's current derived quality state
    (docs/domain/STORE_INVENTORY_MODEL.md §11's frozen state machine), or
    when the requested disposition value itself is not one of the ordinary
    human-decision kinds (`RELEASED`/`HELD`/`REJECTED`/`HOLD_RELEASED`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QualitySegregationOfDutiesError(DomainError):
    """Raised when an action whose net resulting state is usable
    (`RELEASED`/`HOLD_RELEASED`) is attempted by the same user who received
    the underlying Goods Receipt -- a distinct domain conflict, never
    surfaced as a generic permission-denied response (docs/domain/
    STORE_INVENTORY_MODEL.md §11's segregation-of-duties rule)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QualityDispositionNoCurrentHumanDecisionError(DomainError):
    """Raised by a correction command when the cohort has no current HUMAN
    disposition event to correct -- either no event exists at all (implicit
    RELEASED) or the current event is the automatic, permanently
    non-reversible opening `RECEIVED_QUARANTINED` fact."""


class QualityDispositionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class QualityCorrectionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class QualityPartialDispositionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class QualityPartialCorrectionCommandReusedWithDifferentPayloadError(DomainError):
    pass


class QualityDispositionEventNotFoundError(DomainError):
    """Raised when a correction command's `target_event_id` does not
    resolve to a real `QualityDispositionEvent` on this tenant's own
    target cohort."""


class QualityCorrectionTargetNotCurrentError(DomainError):
    """Raised when a correction command's `target_event_id` is a real,
    valid human decision but is no longer the CURRENT one -- another
    decision was recorded after the operator observed it. Never silently
    reinterpreted onto the newer decision (docs/domain/
    STORE_INVENTORY_MODEL.md §11)."""


# --- STORE-INV-002B: physical custody / putaway -----------------------------

class InventoryStorageCommandReusedWithDifferentPayloadError(DomainError):
    pass


class StorageBinNotFoundError(DomainError):
    """Raised when a referenced location does not resolve to a Location
    owned by this tenant/Farm."""


class IneligibleStorageBinError(DomainError):
    """Raised when a referenced location is not a `store_bin`-typed
    Location -- only a `store_bin` is ever a physical custody target."""


class InactiveStorageBinError(DomainError):
    """Raised when a destination `store_bin` is not currently active."""


class InsufficientNotPutAwayQuantityError(DomainError):
    """Raised when a putaway (or a partial Quality action targeting the
    "Not put away" bucket) requests more than the cohort's current
    not-put-away quantity."""


class InsufficientStorageBinBalanceError(DomainError):
    """Raised when a transfer, or a partial Quality action targeting a
    specific Bin bucket, requests more than that cohort's current balance
    in the named source Bin."""


class StorageBinsMustDifferError(DomainError):
    """Raised when a transfer's source and destination Bin are the same."""


class LocationHasActiveInventoryCustodyError(DomainError):
    """Raised when DEACTIVATE targets a `store_bin` Location that still
    holds nonzero consumable Inventory custody (docs/domain/
    STORE_INVENTORY_MODEL.md §10, STORE-INV-002B frozen rule) -- mirrors
    `LocationHasActiveOccupancyError`'s own precedent for the identity-
    based Occupancy engine, applied to the separate quantity-custody
    model."""


class ExistenceBelowCustodyError(DomainError):
    """Raised when an existence-decreasing Adjustment or Reversal would
    leave a cohort's existence quantity below its current physical
    custody quantity -- physical custody can never exceed existence
    (STORE-INV-002B frozen invariant). The remedy is a future stock-count
    correction workflow, not silently allowing this state."""


# --- STORE-INV-003: Reservation & Issue -------------------------------------


class InventoryReservationCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryReservationNotFoundError(DomainError):
    pass


class InventoryReservationLineNotFoundError(DomainError):
    pass


class InsufficientAvailableToIssueError(DomainError):
    """Raised when a Reservation create/expand, or a direct Issue, would
    leave the Farm/Item's own "Available to issue" quantity (usable
    in-Store quantity minus every OTHER active Reservation's remaining
    claim) negative."""


class InventoryReservationReleaseCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InsufficientReservationBalanceError(DomainError):
    """Raised when a Release or an Issue-against-reservation requests more
    than a Reservation line's current remaining balance."""


class InventoryIssueCommandReusedWithDifferentPayloadError(DomainError):
    pass


class InventoryIssueNotFoundError(DomainError):
    pass


class TooManyInventoryIssueLinesError(DomainError):
    pass


class InventoryIssueLineValidationError(DomainError):
    """Raised for any structural problem with a single Issue line -- wrong
    Item for the referenced Reservation line, a source Bin/cohort that does
    not belong to this tenant/Farm, or a non-positive quantity."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InventoryIssueSourceNotUsableError(DomainError):
    """Raised when an Issue line's source cohort is not currently usable
    (quarantined/held/rejected/expired) -- Quality safety always wins over
    Reservation/Issue (docs/domain/STORE_INVENTORY_MODEL.md §11)."""


class ReservationLineItemMismatchError(DomainError):
    """Raised when an Issue line's `reservation_line_id` targets a
    Reservation line for a different `InventoryItem` than the line's own."""


# --- STORE-INV-004: Consumption, Return & Scrap -----------------------------


class InventoryIssueLineNotFoundError(DomainError):
    """Raised when a referenced `issue_line_id` does not resolve to an
    `InventoryStorageMovement` row (`movement_kind = 'issue'`) owned by this
    tenant."""


class InsufficientIssueLineOutstandingError(DomainError):
    """Raised when a Consumption, Return, or Scrap-from-issued command
    requests more than an Issue line's own current outstanding balance
    (`issued - consumed - returned - scrapped`, never a stored aggregate)."""


class InventoryConsumptionSourceNotUsableError(DomainError):
    """Raised when a Consumption command's Issue line's own source cohort is
    not CURRENTLY usable (quarantined/held/rejected/expired) -- Quality
    safety always wins, mirroring `InventoryIssueSourceNotUsableError`.
    Return and Scrap of the same material remain permitted regardless."""


class InventoryMaterialEventCommandReusedWithDifferentPayloadError(DomainError):
    """Shared idempotency-conflict error for Consumption/Return/Scrap --
    mirrors `InventoryStorageCommandReusedWithDifferentPayloadError`'s own
    one-class-per-command-family precedent."""


class InventoryMaterialEventValidationError(DomainError):
    """Generic domain-validation bucket for a Consumption/Return/Scrap
    command's structural shape (source_kind/issue_line_id/
    source_location_id/destination_location_id combination, or a scrap with
    no reason)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InventoryExistenceReversalUnsupportedForEntryKindError(DomainError):
    """Raised when a generic existence-ledger reversal targets a
    `consumption` or `scrap` entry -- reversing either would restore
    existence without restoring the matching custody/Issue-line state
    (docs/domain/STORE_INVENTORY_MODEL.md), so this path is blocked outright
    rather than building an unsafe partial correction. A future coordinated
    correction workflow, if ever built, is a separate ticket."""


class InsufficientAvailableInterVinesPlantsError(DomainError):
    """VINES-OPS-001B: raised when a Nursery->Vines Production transfer
    requests more living plants than are currently available (active,
    unreleased Grow Cube BatchCarrierAssignments) at the named InterVines
    (Batch, Table) source group, under lock. Raised before any write."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InsufficientAvailableGrowBagsError(DomainError):
    """VINES-OPS-001B: raised when a Vines Production transfer requests more
    Grow Bag capacity than currently-available (active, unassigned) Grow
    Bags of the requested specification can provide, under lock. Raised
    before any write."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InsufficientAvailableGrowBagPositionsError(DomainError):
    """VINES-OPS-001B: raised when a Vines Production transfer requests more
    Grow Bags than there are currently-free Grow Bag Positions under the
    selected Grow Gutter, under lock. Raised before any write."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class VinesProductionTransferReplayStateConflictError(DomainError):
    """VINES-OPS-001B: raised on a replay of a composite Vines Production
    Transfer command (same `client_command_id`) whose already-committed
    Grow Bag/position placements cannot be reconciled with the replay
    request -- mirrors `IntervinesTransplantReplayStateConflictError`'s own
    role for this command's own server-allocated-on-BOTH-sides (source Grow
    Cubes AND destination Grow Bags/Positions) shape."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
