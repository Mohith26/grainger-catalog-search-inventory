"""Environment-driven configuration for the StockFind service.

All settings come from ``STOCKFIND_*`` environment variables (or a local
``.env``). Nothing sensitive is hard-coded: the JWT secret must be supplied by
the environment, and the app refuses to boot on the placeholder default unless
explicitly in debug mode.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    """Immutable runtime settings loaded once from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="STOCKFIND_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    pg_dsn: str = "postgresql://stockfind:stockfind@localhost:5470/stockfind"

    jwt_secret: str = PLACEHOLDER_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 3600

    search_rate_limit: str = "120/minute"
    reserve_rate_limit: str = "60/minute"

    seed: int = 42
    seed_on_start: bool = False

    # Search ranking blend weights (lexical FTS vs. fuzzy typo-tolerance).
    rank_weight_lexical: float = 0.7
    rank_weight_fuzzy: float = 0.3
    # A candidate must clear this fuzzy score (0-100) to enter the typo-tolerant pass.
    fuzzy_min_score: float = 60.0

    max_page_size: int = 100
    default_page_size: int = 20

    debug: bool = False

    def require_real_secret(self) -> None:
        """Fail fast if a real deployment is running on the placeholder secret."""
        if not self.debug and self.jwt_secret == PLACEHOLDER_JWT_SECRET:
            raise RuntimeError(
                "STOCKFIND_JWT_SECRET is the placeholder default. Set a real "
                "secret via the environment before running outside debug mode."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
