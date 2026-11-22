"""Muhit sozlamalari. Barcha sirlar faqat environment variables orqali beriladi."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    """Render `postgres://` yoki `postgresql://` beradi; asyncpg drayveriga o'tkazamiz."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    database_url: str = "postgresql+asyncpg://abu:abu_dev_pass@localhost:5432/abu_bot"
    secret_key: str = "dev-secret-change-me"

    bot_token: str = ""
    bot_username: str = "premiumabu_bot"
    webapp_url: str = ""  # deploydan keyin: https://<render-url>
    webhook_secret: str = ""  # webhook URL yo'li va Telegram secret_token uchun
    admin_telegram_ids: str = ""  # vergul bilan: 123,456 (superadmin bootstrap)
    support_username: str = ""

    cors_origins: str = ""
    max_upload_bytes: int = 2_000_000
    init_data_max_age: int = 86400
    rate_limit_per_minute: int = 240

    # To'lov provayderlari (bo'sh bo'lsa -> not_configured)
    manual_card_info: str = ""  # karta rekvizitlari matni (env'da)
    manual_card_number: str = ""  # masalan 8600 1234 5678 9012
    manual_card_holder: str = ""  # karta egasi ismi
    manual_payment_contact: str = "@mirzkbrv17"  # to'lov tasdig'i uchun aloqa
    click_service_id: str = ""
    click_merchant_id: str = ""
    click_merchant_user_id: str = ""
    click_secret_key: str = ""
    mock_provider_enabled: bool = False  # faqat dev/test
    mock_webhook_secret: str = "mock-secret"
    stars_enabled: bool = False  # Telegram Stars o'chirilgan (karta orqali to'lov ishlatiladi)

    run_scheduler: bool = True
    redis_url: str = ""  # ixtiyoriy; hozircha ishlatilmaydi

    @property
    def db_url(self) -> str:
        return normalize_db_url(self.database_url)

    @property
    def admin_ids(self) -> set[int]:
        out = set()
        for p in self.admin_telegram_ids.split(","):
            p = p.strip()
            if p.isdigit():
                out.add(int(p))
        return out

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
