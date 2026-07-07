from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///data/database.sqlite3"
    CHANNEL_USERNAME: str = "@Moezabj7"
    NEWS_CHANNEL_ID: str = "-1003830457482"

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]


settings = Settings()
