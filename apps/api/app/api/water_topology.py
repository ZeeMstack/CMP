import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_topology import (
    CircuitDeliveryPointLinkOpen,
    IrrigationCircuitCreate,
    IrrigationCircuitRead,
    ReservoirCircuitLinkOpen,
    ReservoirCreate,
    ReservoirRead,
    ReturnPointReservoirLinkOpen,
    TopologyLinkClose,
    TopologyLinkRead,
    WaterDeliveryPointCreate,
    WaterDeliveryPointRead,
    WaterReturnPointCreate,
    WaterReturnPointRead,
    WaterSourceCreate,
    WaterSourceRead,
    WaterSourceReservoirLinkOpen,
)
from app.services import water_topology_service
from app.services.errors import (
    DuplicateIrrigationCircuitCodeError,
    DuplicateReservoirCodeError,
    DuplicateWaterDeliveryPointCodeError,
    DuplicateWaterReturnPointCodeError,
    DuplicateWaterSourceCodeError,
    FarmNotFoundError,
    IrrigationCircuitNotFoundError,
    LocationNotFoundError,
    ReservoirNotFoundError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
    WaterDeliveryPointNotFoundError,
    WaterReturnPointNotFoundError,
    WaterSourceNotFoundError,
    WaterTopologyLinkAlreadyClosedError,
    WaterTopologyLinkNotFoundError,
)

router = APIRouter(tags=["water-topology"])


# --- WaterSource ---------------------------------------------------------------------


@router.post("/farms/{farm_id}/water-sources", response_model=WaterSourceRead, status_code=status.HTTP_201_CREATED)
def register_water_source(
    farm_id: uuid.UUID,
    payload: WaterSourceCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> WaterSourceRead:
    try:
        return water_topology_service.register_water_source(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, source_type=payload.source_type, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except DuplicateWaterSourceCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Water source code already exists") from exc


@router.get("/farms/{farm_id}/water-sources", response_model=list[WaterSourceRead])
def list_water_sources(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[WaterSourceRead]:
    return water_topology_service.list_water_sources(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/water-sources/{water_source_id}", response_model=WaterSourceRead)
def get_water_source(
    water_source_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> WaterSourceRead:
    try:
        return water_topology_service.get_water_source(db, tenant_id=ctx.tenant_id, water_source_id=water_source_id)
    except WaterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Water source not found") from exc


# --- Reservoir -----------------------------------------------------------------------


@router.post("/farms/{farm_id}/reservoirs", response_model=ReservoirRead, status_code=status.HTTP_201_CREATED)
def register_reservoir(
    farm_id: uuid.UUID,
    payload: ReservoirCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> ReservoirRead:
    try:
        return water_topology_service.register_reservoir(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, reservoir_type=payload.reservoir_type, nominal_capacity=payload.nominal_capacity,
            nominal_capacity_uom_id=payload.nominal_capacity_uom_id, linked_asset_id=payload.linked_asset_id,
            location_id=payload.location_id, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Location not found") from exc
    except (UnitOfMeasureNotFoundError, UnitOfMeasureKindMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except DuplicateReservoirCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reservoir code already exists") from exc


@router.get("/farms/{farm_id}/reservoirs", response_model=list[ReservoirRead])
def list_reservoirs(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[ReservoirRead]:
    return water_topology_service.list_reservoirs(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/reservoirs/{reservoir_id}", response_model=ReservoirRead)
def get_reservoir(
    reservoir_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> ReservoirRead:
    try:
        return water_topology_service.get_reservoir(db, tenant_id=ctx.tenant_id, reservoir_id=reservoir_id)
    except ReservoirNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservoir not found") from exc


# --- IrrigationCircuit -----------------------------------------------------------------


@router.post(
    "/farms/{farm_id}/irrigation-circuits", response_model=IrrigationCircuitRead,
    status_code=status.HTTP_201_CREATED,
)
def register_irrigation_circuit(
    farm_id: uuid.UUID,
    payload: IrrigationCircuitCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> IrrigationCircuitRead:
    try:
        return water_topology_service.register_irrigation_circuit(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, system_type=payload.system_type, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except DuplicateIrrigationCircuitCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Irrigation circuit code already exists") from exc


@router.get("/farms/{farm_id}/irrigation-circuits", response_model=list[IrrigationCircuitRead])
def list_irrigation_circuits(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[IrrigationCircuitRead]:
    return water_topology_service.list_irrigation_circuits(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/irrigation-circuits/{irrigation_circuit_id}", response_model=IrrigationCircuitRead)
def get_irrigation_circuit(
    irrigation_circuit_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> IrrigationCircuitRead:
    try:
        return water_topology_service.get_irrigation_circuit(
            db, tenant_id=ctx.tenant_id, irrigation_circuit_id=irrigation_circuit_id
        )
    except IrrigationCircuitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Irrigation circuit not found") from exc


# --- WaterDeliveryPoint -----------------------------------------------------------------


@router.post(
    "/farms/{farm_id}/water-delivery-points", response_model=WaterDeliveryPointRead,
    status_code=status.HTTP_201_CREATED,
)
def register_water_delivery_point(
    farm_id: uuid.UUID,
    payload: WaterDeliveryPointCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> WaterDeliveryPointRead:
    try:
        return water_topology_service.register_water_delivery_point(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, location_id=payload.location_id, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Location not found") from exc
    except DuplicateWaterDeliveryPointCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delivery point code already exists") from exc


@router.get("/farms/{farm_id}/water-delivery-points", response_model=list[WaterDeliveryPointRead])
def list_water_delivery_points(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[WaterDeliveryPointRead]:
    return water_topology_service.list_water_delivery_points(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


# --- WaterReturnPoint -------------------------------------------------------------------


@router.post(
    "/farms/{farm_id}/water-return-points", response_model=WaterReturnPointRead,
    status_code=status.HTTP_201_CREATED,
)
def register_water_return_point(
    farm_id: uuid.UUID,
    payload: WaterReturnPointCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> WaterReturnPointRead:
    try:
        return water_topology_service.register_water_return_point(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, location_id=payload.location_id, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Location not found") from exc
    except DuplicateWaterReturnPointCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Return point code already exists") from exc


@router.get("/farms/{farm_id}/water-return-points", response_model=list[WaterReturnPointRead])
def list_water_return_points(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[WaterReturnPointRead]:
    return water_topology_service.list_water_return_points(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


# --- Effective-dated topology links -------------------------------------------------------


def _link_conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/farms/{farm_id}/water-topology-links/water-source-reservoir", response_model=TopologyLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def open_water_source_reservoir_link(
    farm_id: uuid.UUID,
    payload: WaterSourceReservoirLinkOpen,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.open_water_source_reservoir_link(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            water_source_id=payload.water_source_id, reservoir_id=payload.reservoir_id,
            effective_from=payload.effective_from, reason=payload.reason,
        )
    except (WaterSourceNotFoundError, ReservoirNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post(
    "/water-topology-links/water-source-reservoir/{link_id}/close", response_model=TopologyLinkRead,
)
def close_water_source_reservoir_link(
    link_id: uuid.UUID,
    payload: TopologyLinkClose,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.close_water_source_reservoir_link(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, link_id=link_id,
            effective_to=payload.effective_to,
        )
    except WaterTopologyLinkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found") from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post(
    "/farms/{farm_id}/water-topology-links/reservoir-circuit", response_model=TopologyLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def open_reservoir_circuit_link(
    farm_id: uuid.UUID,
    payload: ReservoirCircuitLinkOpen,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.open_reservoir_circuit_link(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            reservoir_id=payload.reservoir_id, irrigation_circuit_id=payload.irrigation_circuit_id,
            effective_from=payload.effective_from, reason=payload.reason,
        )
    except (ReservoirNotFoundError, IrrigationCircuitNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post("/water-topology-links/reservoir-circuit/{link_id}/close", response_model=TopologyLinkRead)
def close_reservoir_circuit_link(
    link_id: uuid.UUID,
    payload: TopologyLinkClose,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.close_reservoir_circuit_link(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, link_id=link_id,
            effective_to=payload.effective_to,
        )
    except WaterTopologyLinkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found") from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post(
    "/farms/{farm_id}/water-topology-links/circuit-delivery-point", response_model=TopologyLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def open_circuit_delivery_point_link(
    farm_id: uuid.UUID,
    payload: CircuitDeliveryPointLinkOpen,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.open_circuit_delivery_point_link(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            irrigation_circuit_id=payload.irrigation_circuit_id,
            water_delivery_point_id=payload.water_delivery_point_id, effective_from=payload.effective_from,
            reason=payload.reason,
        )
    except (IrrigationCircuitNotFoundError, WaterDeliveryPointNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post("/water-topology-links/circuit-delivery-point/{link_id}/close", response_model=TopologyLinkRead)
def close_circuit_delivery_point_link(
    link_id: uuid.UUID,
    payload: TopologyLinkClose,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.close_circuit_delivery_point_link(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, link_id=link_id,
            effective_to=payload.effective_to,
        )
    except WaterTopologyLinkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found") from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post(
    "/farms/{farm_id}/water-topology-links/return-point-reservoir", response_model=TopologyLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def open_return_point_reservoir_link(
    farm_id: uuid.UUID,
    payload: ReturnPointReservoirLinkOpen,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.open_return_point_reservoir_link(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            water_return_point_id=payload.water_return_point_id, return_reservoir_id=payload.return_reservoir_id,
            effective_from=payload.effective_from, reason=payload.reason,
        )
    except (WaterReturnPointNotFoundError, ReservoirNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


@router.post("/water-topology-links/return-point-reservoir/{link_id}/close", response_model=TopologyLinkRead)
def close_return_point_reservoir_link(
    link_id: uuid.UUID,
    payload: TopologyLinkClose,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_MANAGE)),
) -> TopologyLinkRead:
    try:
        return water_topology_service.close_return_point_reservoir_link(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, link_id=link_id,
            effective_to=payload.effective_to,
        )
    except WaterTopologyLinkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found") from exc
    except WaterTopologyLinkAlreadyClosedError as exc:
        raise _link_conflict(exc) from exc


# --- PILOT-WATER-001B: farm-wide topology link reads (current + historical) -----------


@router.get("/farms/{farm_id}/water-topology-links/water-source-reservoir", response_model=list[TopologyLinkRead])
def list_water_source_reservoir_links(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[TopologyLinkRead]:
    return water_topology_service.list_water_source_reservoir_links(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/farms/{farm_id}/water-topology-links/reservoir-circuit", response_model=list[TopologyLinkRead])
def list_reservoir_circuit_links(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[TopologyLinkRead]:
    return water_topology_service.list_reservoir_circuit_links(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/farms/{farm_id}/water-topology-links/circuit-delivery-point", response_model=list[TopologyLinkRead])
def list_circuit_delivery_point_links(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[TopologyLinkRead]:
    return water_topology_service.list_circuit_delivery_point_links(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/farms/{farm_id}/water-topology-links/return-point-reservoir", response_model=list[TopologyLinkRead])
def list_return_point_reservoir_links(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[TopologyLinkRead]:
    return water_topology_service.list_return_point_reservoir_links(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
