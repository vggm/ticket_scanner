"""Configuración de la aplicación, leída del entorno o de .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str
    aistudio_key: str | None = None
    ticket_model: str = "google:gemini-3.5-flash-lite"
    ticket_retry_model: str = "google:gemini-3.8-flash"
    ticket_fallback_model: str = ""
    ollama_base_url: str = "http://ollama:11434/v1"
    image_max_side: int = 2048
    max_upload_mb: int = 10
    debug_db_path: Path = Path("/data/debug.db")
    debug_save_images: bool = False
    debug_images_dir: Path = Path("/data/images")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
