"""All configuration comes from environment variables (or bot/.env). See .env.example."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # WhatsApp Cloud API (official, Meta)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    graph_api_version: str = "v26.0"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: float = 20
    gemini_thinking_budget: int | None = 0

    # Google Sheets (orders)
    google_sheet_id: str = ""
    google_service_account_json: str = "service-account.json"  # path, or the raw JSON itself
    orders_tab: str = "orders"
    # sheets = Google Sheet · db = the bot database (Supabase) · csv = local test file
    orders_backend: Literal["sheets", "db", "csv"] = "sheets"
    csv_path: str = "orders.csv"

    # People / secrets
    owner_whatsapp: str = ""
    order_api_key: str = ""

    # Website → bot
    allowed_origins: str = "http://localhost:5173,http://localhost:4173"
    max_orders_per_ip_per_hour: int = 10

    # Bot state: Postgres in production (free hosts have ephemeral disks), SQLite for local dev only.
    state_backend: Literal["postgres", "sqlite"] = "sqlite"
    database_url: str = ""
    sqlite_path: str = "bot-state.db"

    # Serverless hosts (Vercel): process each WhatsApp message before answering Meta (no background work).
    process_inline: bool = False

    # Conversation limits
    max_replies_per_hour: int = 20
    history_size: int = 20

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
