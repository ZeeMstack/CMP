from fastapi import FastAPI

from app.api.assets import router as assets_router
from app.api.carriers import router as carriers_router
from app.api.farms import router as farms_router
from app.api.health import router as health_router
from app.api.locations import router as locations_router
from app.api.memberships import router as memberships_router
from app.api.movements import router as movements_router
from app.api.ready import router as ready_router
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

    if cfg.enable_dev_auth:
        from app.api.dev_bootstrap import router as dev_bootstrap_router

        api.include_router(dev_bootstrap_router)

    @api.get("/")
    def root() -> dict[str, str]:
        return {"service": "cmp-api", "env": cfg.env}

    return api


app = create_app(settings)
