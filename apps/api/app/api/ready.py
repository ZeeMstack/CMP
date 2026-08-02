import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ready")
def get_ready(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Readiness check failed: %s", type(exc).__name__)
        response.status_code = 503
        return {"status": "not_ready"}
    return {"status": "ready"}
