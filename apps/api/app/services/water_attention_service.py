"""PILOT-WATER-001B section 28: "Today on the Farm" WATER ATTENTION read
model. Conservative by design (mirrors PILOT-OPS-001/PILOT-AGRO-001B's own
"be conservative, never manufacture alerts" precedent) -- every item here
is derived from an explicit, already-recorded fact, never a fabricated
threshold WATER-001A never defined (e.g. no "calibration interval" or
"measurement frequency" rule exists anywhere in that domain, so this
module never claims something is "overdue" by one). No table is written
to; no Farm Work Item is ever created here.

Three genuine signals:
  1. An ACTIVE Irrigation Circuit with no CURRENTLY active Reservoir
     mapping (a real, structural topology gap -- water cannot reach it).
  2. An ACTIVE Water Instrument that has never once been calibrated (zero
     `InstrumentCalibrationEvent` rows -- a plain fact, not a threshold).
  3. The latest Measurement at a Reservoir-anchored Sampling Point falling
     outside that Reservoir's most recent Nutrient Mix's own referenced
     Recipe Version target (EC/pH only, the two metrics a Recipe Version
     actually carries a target for) -- only ever computed when both a
     real recent Mix-with-Recipe-reference AND a real recent Measurement
     exist for that Reservoir; never inferred from an assumed "current
     recipe" WATER-001A has no such assignment concept for."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument_calibration_event import InstrumentCalibrationEvent
from app.models.irrigation_circuit import IrrigationCircuit
from app.models.nutrient_mix import NutrientMix
from app.models.nutrient_recipe_version import NutrientRecipeVersion
from app.models.reservoir import Reservoir
from app.models.sampling_point import SamplingPoint
from app.models.water_instrument import WaterInstrument
from app.models.water_measurement import WaterMeasurement
from app.models.water_topology_link import ReservoirCircuitLink


def _circuits_missing_current_topology(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    active_circuit_ids = set(
        db.execute(
            select(IrrigationCircuit.id).where(
                IrrigationCircuit.tenant_id == tenant_id, IrrigationCircuit.farm_id == farm_id,
                IrrigationCircuit.status == "active",
            )
        ).scalars()
    )
    fed_circuit_ids = set(
        db.execute(
            select(ReservoirCircuitLink.irrigation_circuit_id).where(
                ReservoirCircuitLink.tenant_id == tenant_id, ReservoirCircuitLink.farm_id == farm_id,
                ReservoirCircuitLink.effective_to.is_(None),
            )
        ).scalars()
    )
    missing_ids = active_circuit_ids - fed_circuit_ids
    if not missing_ids:
        return []
    rows = db.execute(select(IrrigationCircuit).where(IrrigationCircuit.id.in_(missing_ids))).scalars()
    return [
        {
            "kind": "CIRCUIT_MISSING_RESERVOIR", "irrigation_circuit_id": row.id, "code": row.code, "name": row.name,
            "message": f"Circuit {row.code} is active but has no current Reservoir feeding it.",
        }
        for row in rows
    ]


def _instruments_never_calibrated(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    calibrated_instrument_ids = set(
        db.execute(
            select(InstrumentCalibrationEvent.water_instrument_id).where(
                InstrumentCalibrationEvent.tenant_id == tenant_id, InstrumentCalibrationEvent.farm_id == farm_id,
            )
        ).scalars()
    )
    active_instruments = db.execute(
        select(WaterInstrument).where(
            WaterInstrument.tenant_id == tenant_id, WaterInstrument.farm_id == farm_id,
            WaterInstrument.status == "active",
        )
    ).scalars()
    return [
        {
            "kind": "INSTRUMENT_NEVER_CALIBRATED", "water_instrument_id": row.id,
            "message": "Instrument has no recorded calibration.",
        }
        for row in active_instruments
        if row.id not in calibrated_instrument_ids
    ]


def _measurements_outside_recipe_target(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    reservoirs = db.execute(
        select(Reservoir).where(Reservoir.tenant_id == tenant_id, Reservoir.farm_id == farm_id, Reservoir.status == "active")
    ).scalars()
    items: list[dict] = []
    for reservoir in reservoirs:
        latest_mix = db.execute(
            select(NutrientMix)
            .where(
                NutrientMix.tenant_id == tenant_id, NutrientMix.reservoir_id == reservoir.id,
                NutrientMix.nutrient_recipe_version_id.is_not(None),
            )
            .order_by(NutrientMix.effective_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_mix is None:
            continue
        version = db.execute(
            select(NutrientRecipeVersion).where(NutrientRecipeVersion.id == latest_mix.nutrient_recipe_version_id)
        ).scalar_one_or_none()
        if version is None or (version.target_ec is None and version.target_ph is None):
            continue

        sampling_point_ids = list(
            db.execute(
                select(SamplingPoint.id).where(
                    SamplingPoint.tenant_id == tenant_id, SamplingPoint.reservoir_id == reservoir.id,
                )
            ).scalars()
        )
        if not sampling_point_ids:
            continue

        for metric, target in (("EC", version.target_ec), ("PH", version.target_ph)):
            if target is None:
                continue
            latest_measurement = db.execute(
                select(WaterMeasurement)
                .where(
                    WaterMeasurement.tenant_id == tenant_id, WaterMeasurement.metric == metric,
                    WaterMeasurement.sampling_point_id.in_(sampling_point_ids),
                )
                .order_by(WaterMeasurement.effective_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_measurement is None:
                continue
            # A conservative +/-10% band around the single target value --
            # WATER-001A's target_ec/target_ph is one number, not a stored
            # range, so a fixed proportional band is the only comparison
            # possible without inventing a per-recipe tolerance field.
            tolerance = abs(target) * Decimal("0.10")
            if abs(latest_measurement.value - target) > tolerance:
                items.append(
                    {
                        "kind": "MEASUREMENT_OUTSIDE_RECIPE_TARGET", "reservoir_id": reservoir.id,
                        "sampling_point_id": latest_measurement.sampling_point_id, "metric": metric,
                        "measured_value": latest_measurement.value, "target_value": target,
                        "nutrient_recipe_version_id": version.id,
                        "message": (
                            f"Reservoir {reservoir.code}: latest {metric} {latest_measurement.value} is outside "
                            f"the {latest_mix.effective_at.date()} Mix's Recipe target {target}."
                        ),
                    }
                )
    return items


def get_water_attention(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[dict]:
    return [
        *_circuits_missing_current_topology(db, tenant_id=tenant_id, farm_id=farm_id),
        *_instruments_never_calibrated(db, tenant_id=tenant_id, farm_id=farm_id),
        *_measurements_outside_recipe_target(db, tenant_id=tenant_id, farm_id=farm_id),
    ]
