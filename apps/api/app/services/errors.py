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
