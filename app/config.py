from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ResearchBridge"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    database_path: Path = Path("data/researchbridge.db")
    max_upload_files: int = 8
    max_upload_bytes: int = 15 * 1024 * 1024
    max_request_bytes: int = 32 * 1024 * 1024
    max_zip_files: int = 150
    max_zip_member_bytes: int = 512 * 1024
    max_zip_text_bytes: int = 2 * 1024 * 1024
    max_zip_declared_bytes: int = 20 * 1024 * 1024
    max_zip_compression_ratio: float = 100.0
    max_pdf_pages: int = 100
    max_pdf_text_bytes: int = 2 * 1024 * 1024
    overlap_semantic_threshold: float = 0.78
    collaboration_topic_threshold: float = 0.45

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
