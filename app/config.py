"""Central settings, loaded from environment / .env.

Nothing else in the app reads os.environ directly — import `settings` from here.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_secret_key: str = ""

    # Razorpay (Test Mode)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Gemini (Phase 2)
    gemini_api_key: str = ""

    # Twilio (Phase 2)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""

    app_env: str = "dev"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def rest_url(self) -> str:
        """PostgREST base, e.g. https://<ref>.supabase.co/rest/v1"""
        return self.supabase_url.rstrip("/") + "/rest/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
