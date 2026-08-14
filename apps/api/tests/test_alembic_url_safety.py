"""ALEMBIC-SAFETY-001: fail-closed Alembic database URL resolution tests
(see INCIDENT-001 for the forensic background this closes).

Verifies `migrations/_alembic_url_safety.py`'s `resolve_explicit_alembic_url`
directly (fast, precise coverage of missing/blank/placeholder URLs), plus
end-to-end proof that explicit `cmp_test` targeting still works, that an
explicitly-supplied dev URL is accepted at the resolution layer without
ever connecting (the fail-closed rule blocks IMPLICIT targeting only, not
deliberate explicit use), and a direct regression test against the real
`migrations/env.py` reproducing the exact INCIDENT-001 mechanism.

No bare `alembic` CLI command is used anywhere in this file or was used
to produce this file's own verification. Every `Config` is constructed
explicitly in-process, mirroring this suite's established safe pattern
(`tests/conftest.py:migrations_alembic_config`, `tests/test_migrations.py`'s
own local `_cfg()`)."""
import importlib.util
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent

# Must match migrations/env.py's own loader exactly: registering under the
# same sys.modules name means this test's AlembicUrlNotConfiguredError is
# class-identical to the one migrations/env.py raises for real (via
# command.current/upgrade/downgrade below), whichever side loads the
# module first -- otherwise pytest.raises(AlembicUrlNotConfiguredError)
# would never match an exception raised from env.py's own separately
# (independently) loaded copy of the same file.
_ALEMBIC_URL_SAFETY_MODULE_NAME = "cmp_alembic_url_safety"


def _load_alembic_url_safety():
    if _ALEMBIC_URL_SAFETY_MODULE_NAME in sys.modules:
        return sys.modules[_ALEMBIC_URL_SAFETY_MODULE_NAME]
    path = API_ROOT / "migrations" / "_alembic_url_safety.py"
    spec = importlib.util.spec_from_file_location(_ALEMBIC_URL_SAFETY_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ALEMBIC_URL_SAFETY_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_safety = _load_alembic_url_safety()
resolve_explicit_alembic_url = _safety.resolve_explicit_alembic_url
AlembicUrlNotConfiguredError = _safety.AlembicUrlNotConfiguredError
PLACEHOLDER_URL = _safety.PLACEHOLDER_URL


def _bare_cfg() -> Config:
    """A bare-CLI-equivalent Config: the real alembic.ini and script_location,
    no sqlalchemy.url override -- exactly what `python -m alembic ...`
    constructs from this repository's own alembic.ini today."""
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    return cfg


def _test_cfg() -> Config:
    cfg = _bare_cfg()
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


# =====================================================================
# A/B/C: missing / blank / placeholder URL must be rejected
# =====================================================================


@pytest.mark.integration
def test_missing_url_rejected() -> None:
    """(A) No sqlalchemy.url configured at all."""
    cfg = Config()  # no ini file at all -- get_main_option returns None for anything unset
    assert cfg.get_main_option("sqlalchemy.url") is None
    with pytest.raises(AlembicUrlNotConfiguredError, match="must be supplied explicitly"):
        resolve_explicit_alembic_url(cfg)


@pytest.mark.integration
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_url_rejected(blank: str) -> None:
    """(B) sqlalchemy.url explicitly set to an empty/whitespace-only string."""
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", blank)
    with pytest.raises(AlembicUrlNotConfiguredError, match="must be supplied explicitly"):
        resolve_explicit_alembic_url(cfg)


@pytest.mark.integration
def test_placeholder_url_rejected() -> None:
    """(C) sqlalchemy.url is still the stock alembic.ini placeholder --
    the exact value a completely untouched alembic.ini ships with, and
    the exact value the OLD (pre-ALEMBIC-SAFETY-001) code used to
    silently fall back away from onto settings.database_url."""
    cfg = _bare_cfg()
    assert cfg.get_main_option("sqlalchemy.url") == PLACEHOLDER_URL
    with pytest.raises(AlembicUrlNotConfiguredError, match="must be supplied explicitly"):
        resolve_explicit_alembic_url(cfg)


@pytest.mark.integration
def test_safety_exception_message_never_includes_a_url_or_password() -> None:
    """The message must make the required action obvious without ever
    echoing back a URL (which could contain a password) -- true by
    construction (the message is a fixed string, never interpolated with
    the rejected value), verified here directly."""
    with pytest.raises(AlembicUrlNotConfiguredError) as exc_info:
        resolve_explicit_alembic_url(_bare_cfg())
    message = str(exc_info.value)
    assert "://" not in message
    assert "password" not in message.lower()
    assert "must be supplied explicitly" in message
    assert "refusing to select a database automatically" in message


# =====================================================================
# D: explicit cmp_test URL works end-to-end
# =====================================================================


@pytest.mark.integration
def test_explicit_test_database_url_is_returned_unchanged() -> None:
    cfg = _test_cfg()
    assert resolve_explicit_alembic_url(cfg) == settings.test_database_url


@pytest.mark.integration
def test_explicit_test_database_url_upgrades_cmp_test_to_dynamic_head(
    test_engine, alembic_head_restore
) -> None:
    """End-to-end proof that env.py's real fail-closed check does not
    break the safe, explicit-URL path: current_database() confirms
    cmp_test, and the upgrade reaches the dynamically-resolved head --
    never a hardcoded revision string, so this stays correct as later
    tickets add revisions on top of whichever one is head today."""
    cfg = _test_cfg()
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "cmp_test"

    command.upgrade(cfg, "head")

    expected_head = ScriptDirectory.from_config(cfg).get_current_head()
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == expected_head


# =====================================================================
# E: explicit dev URL is ACCEPTED by the resolution layer, but this test
# never connects to cmp -- resolve_explicit_alembic_url is a pure
# string-validation function with no engine/connection logic of its own.
# =====================================================================


@pytest.mark.integration
def test_explicit_dev_database_url_is_accepted_without_connecting() -> None:
    """The fail-closed rule blocks IMPLICIT targeting only. A caller who
    deliberately, explicitly supplies settings.database_url must still be
    allowed through this resolution layer (a legitimate, rare, deliberate
    operation remains possible by caller choice) -- proven here without
    ever opening a connection to cmp, since resolve_explicit_alembic_url
    never creates an engine."""
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    assert resolve_explicit_alembic_url(cfg) == settings.database_url


# =====================================================================
# F/H: INCIDENT-001 regression -- exercises the REAL migrations/env.py,
# not just the extracted helper, via a genuine Alembic command entrypoint.
# =====================================================================


@pytest.mark.integration
def test_incident_001_regression_real_env_py_never_falls_back_to_dev_database() -> None:
    """Direct regression test for INCIDENT-001. A Config reaching the
    REAL migrations/env.py (not just the extracted helper) with no
    explicit sqlalchemy.url -- exactly what a bare `python -m alembic
    current` CLI invocation constructs -- must fail with the new safety
    exception before migrations/env.py reaches fileConfig, target_metadata
    binding, or run_migrations_online()'s own engine_from_config(...) call
    (all of which sit textually after the safety check in env.py, and none
    of which this exception path ever reaches).

    This test fails against the pre-ALEMBIC-SAFETY-001 code: the old
    env.py had no such exception type at all -- it would instead have
    silently mutated this exact Config's sqlalchemy.url to
    settings.database_url via config.set_main_option(...) and gone on to
    open a real connection to cmp, exactly as happened during
    INCIDENT-001."""
    cfg = _bare_cfg()

    with pytest.raises(AlembicUrlNotConfiguredError, match="must be supplied explicitly"):
        command.current(cfg)

    # The old code's incident mechanism was a *mutation* of the Config
    # object toward settings.database_url. Prove that never happened here:
    # the Config's own sqlalchemy.url is still exactly what it started as.
    assert cfg.get_main_option("sqlalchemy.url") == PLACEHOLDER_URL
    assert cfg.get_main_option("sqlalchemy.url") != settings.database_url
