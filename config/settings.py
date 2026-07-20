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
    GEMINI_API_KEYS: str = ""
    GROQ_API_KEY: str = ""
    GROQ_API_KEYS: str = ""

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def gemini_keys(self) -> List[str]:
        return [x.strip() for x in self.GEMINI_API_KEYS.split(",") if x.strip()]

    @property
    def groq_keys(self) -> List[str]:
        keys = [x.strip() for x in self.GROQ_API_KEYS.split(",") if x.strip()]
        if self.GROQ_API_KEY and self.GROQ_API_KEY not in keys:
            keys.insert(0, self.GROQ_API_KEY)
        return keys


settings = Settings()
