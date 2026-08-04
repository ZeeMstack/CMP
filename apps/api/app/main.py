from fastapi import FastAPI

from app.api.assets import router as assets_router
from app.api.batch_derivations import router as batch_derivations_router
from app.api.carriers import router as carriers_router
from app.api.crop_batches import router as crop_batches_router
from app.api.crops import router as crops_router
from app.api.farms import router as farms_router
from app.api.health import router as health_router
from app.api.locations import router as locations_router
from app.api.memberships import router as memberships_router
from app.api.movements import router as movements_router
from app.api.observation_definitions import router as observation_definitions_router
from app.api.observations import router as observations_router
from app.api.production_systems import router as production_systems_router
from app.api.quality_holds import router as quality_holds_router
from app.api.ready import router as ready_router
from app.api.seed_lots import router as seed_lots_router
from app.api.sowings import router as sowings_router
from app.api.transplants import router as transplants_router
from app.api.workflows import router as workflows_router
from app.core.dev_auth import check_dev_auth_startup_invariant
from app.core.settings import Settings, settings


def create_app(cfg: Settings) -> FastAPI:
    check_dev_auth_startup_invariant(cfg)

    api = FastAPI(title="CMP API", version="0.1.0")
    api.include_router(health_router)
    api.include_router(ready_router)
    api.include_router(memberships_router)
    api.include_router(farms_router)
    api.include_router(locations_router)
    api.include_router(assets_router)
    api.include_router(carriers_router)
    api.include_router(movements_router)
    api.include_router(crops_router)
    api.include_router(production_systems_router)
    api.include_router(workflows_router)
    api.include_router(crop_batches_router)
    api.include_router(batch_derivations_router)
    api.include_router(seed_lots_router)
    api.include_router(sowings_router)
    api.include_router(observation_definitions_router)
    api.include_router(observations_router)
    api.include_router(quality_holds_router)
    api.include_router(transplants_router)

    if cfg.enable_dev_auth:
        from app.api.dev_bootstrap import router as dev_bootstrap_router

        api.include_router(dev_bootstrap_router)

    @api.get("/")
    def root() -> dict[str, str]:
        return {"service": "cmp-api", "env": cfg.env}

    return api


app = create_app(settings)
