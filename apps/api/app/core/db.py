from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine() -> Engine:
    """FastAPI dependency exposing the module-level `engine` itself, for
    the rare read service (CMP-019 traceability) that must own its own
    dedicated connection/transaction rather than use the request-scoped
    `Session` from `get_db` -- overridable in tests exactly like `get_db`
    is, so integration tests can point it at `test_engine`."""
    return engine
