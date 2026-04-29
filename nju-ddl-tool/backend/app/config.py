from functools import lru_cache
from pathlib import Path
import os


class Settings:
    app_name = "NJU DDL Tool"
    database_url = os.getenv("NJU_DDL_DATABASE_URL", "sqlite:///./nju_ddl_tool.db")
    secret = os.getenv("NJU_DDL_SECRET", "dev-secret-change-me")
    cors_origins = [
        origin.strip()
        for origin in os.getenv(
            "NJU_DDL_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip()
    ]
    playwright_headless = os.getenv("NJU_DDL_PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    browser_user_data_dir = Path(os.getenv("NJU_DDL_BROWSER_DIR", "./browser-sessions"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
