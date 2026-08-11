from pydantic_settings import BaseSettings
from pathlib import Path
import os


class Settings(BaseSettings):
    app_name: str = "QoderRoute"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8010

    database_url: str = "sqlite+aiosqlite:///./data/qoderroute.db"

    jwt_secret: str = "qoderroute-super-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    qodercli_path: str = ""
    qoder_poll_interval: int = 300
    account_cooldown_seconds: int = 30
    max_consecutive_failures: int = 3

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    data_dir: str = str(Path(__file__).parent.parent.parent / "data")

    # Optional trial worker script (not shipped in the public build).
    # Set QODER_WORKER_SCRIPT to enable the worker API.
    worker_script: str = os.environ.get("QODER_WORKER_SCRIPT", "")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()