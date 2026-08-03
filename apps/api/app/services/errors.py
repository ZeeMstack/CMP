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


class StageVersionMismatchError(DomainError):
    pass


class WorkflowPublicationValidationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
