from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only JWS algorithms CMP's OIDC bearer-token verification may ever be
# configured to accept -- all asymmetric/public-key. "none" and any HMAC
# (HS*) algorithm are structurally excluded: a shared-secret or unsigned
# algorithm is never valid for a public-key/JWKS trust model, and this must
# hold regardless of what an operator sets OIDC_ALLOWED_ALGORITHMS to.
_ASYMMETRIC_JWT_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://cmp:cmp@localhost:5432/cmp"
    db_connect_timeout_seconds: int = Field(default=5, gt=0)
    enable_dev_auth: bool = False
    test_database_url: str | None = None

    # Provider-neutral OIDC bearer-token verification config (AUTH-001A).
    # Deliberately generic -- issuer/audience/JWKS-URL, not a vendor SDK --
    # so the specific identity provider can be selected/changed later
    # (docs/domain/MULTI_TENANCY.md, docs/product/OPEN_QUESTIONS.md) without
    # touching this settings shape or the verification code that reads it.
    # These verify API *access* tokens for the CMP resource/audience, not
    # ID tokens -- `oidc_audience` must be the CMP API's own audience
    # identifier, never a frontend OIDC client ID.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    # Explicit asymmetric-only allowlist -- "none" and HMAC/shared-secret
    # algorithms (HS256 etc.) are never valid for a public-key/JWKS trust
    # model and must never appear here.
    oidc_allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    oidc_clock_skew_seconds: int = Field(default=60, ge=0)
    oidc_jwks_cache_ttl_seconds: int = Field(default=300, gt=0)
    # Minimum interval between JWKS refreshes triggered specifically by an
    # unknown `kid` (as opposed to the normal TTL-based refresh above).
    # Bounds the outbound-request cost of an unknown-kid spray while still
    # letting a genuinely rotated-in key be discovered promptly.
    oidc_jwks_min_refresh_interval_seconds: int = Field(default=30, ge=0)

    @field_validator("oidc_allowed_algorithms")
    @classmethod
    def _reject_non_asymmetric_algorithms(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("oidc_allowed_algorithms must not be empty")
        disallowed = [alg for alg in value if alg not in _ASYMMETRIC_JWT_ALGORITHMS]
        if disallowed:
            raise ValueError(
                f"oidc_allowed_algorithms may only contain asymmetric JWS algorithms "
                f"{sorted(_ASYMMETRIC_JWT_ALGORITHMS)}; rejected: {disallowed!r}. "
                "'none' and HMAC (HS*) algorithms are never permitted, regardless of configuration."
            )
        return value


settings = Settings()


def check_oidc_startup_invariant(cfg: "Settings | None" = None) -> None:
    """A production-shaped deployment (`env != 'development'`) must have
    real bearer-auth configuration present -- otherwise it would boot with
    neither dev auth (already blocked outside development) nor real auth
    available, which must be a hard startup failure, not a silent
    "everything 401s forever" runtime surprise discovered later. This is
    the complementary half of `check_dev_auth_startup_invariant`: that one
    keeps dev auth out of production, this one keeps production from
    running with no authentication mechanism configured at all."""
    cfg = cfg or settings
    if cfg.env == "development":
        return
    missing = [
        name
        for name, value in (
            ("OIDC_ISSUER", cfg.oidc_issuer),
            ("OIDC_AUDIENCE", cfg.oidc_audience),
            ("OIDC_JWKS_URL", cfg.oidc_jwks_url),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Missing required OIDC configuration outside development: {', '.join(missing)}. "
            "A non-development deployment must not start without real bearer-auth configuration "
            "-- there is no silent fallback to dev identity."
        )
