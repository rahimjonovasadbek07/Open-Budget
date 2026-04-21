from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    BOT_TOKEN: str
    ADMIN_IDS: str = ""

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "budget_bot"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""

    WEBHOOK_URL: str = ""
    WEBHOOK_PATH: str = "/webhook"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8080

    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    @property
    def db_dsn(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def use_webhook(self) -> bool:
        return bool(self.WEBHOOK_URL)


@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
