class DomainError(Exception):
    """Base class for application-level domain errors mapped to HTTP by routers."""


class DuplicateTenantCodeError(DomainError):
    pass


class DuplicateUserIdentityError(DomainError):
    pass


class DuplicateMembershipError(DomainError):
    pass


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
    """NURSERY-OPS-002A: the referenced AssetPosition is not an active
    `slot` belonging to the selected Germination Trolley."""

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


class PackingInputProduceLotNotFoundError(DomainError):
    pass


class PackingCropVarietyMismatchError(DomainError):
    pass


class InsufficientProduceLotBalanceError(DomainError):
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
