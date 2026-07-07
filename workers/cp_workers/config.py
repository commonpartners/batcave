"""Environment-driven configuration. Loaded once at import time via python-dotenv."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    companies_house_api_key: str | None = field(default_factory=lambda: _env("COMPANIES_HOUSE_API_KEY"))
    supabase_url: str | None = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_role_key: str | None = field(default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY"))
    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    resend_api_key: str | None = field(default_factory=lambda: _env("RESEND_API_KEY"))
    digest_to: str = field(default_factory=lambda: _env("DIGEST_TO", ""))
    google_places_api_key: str | None = field(default_factory=lambda: _env("GOOGLE_PLACES_API_KEY"))
    brave_search_api_key: str | None = field(default_factory=lambda: _env("BRAVE_SEARCH_API_KEY"))

    @property
    def digest_recipients(self) -> list[str]:
        return [addr.strip() for addr in self.digest_to.split(",") if addr.strip()]


settings = Settings()
