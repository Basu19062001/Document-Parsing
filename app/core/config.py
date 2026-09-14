from pathlib import Path
from typing import Set
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    PROJECT_NAME: str = "Document Parsing Service"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Storage Settings
    # Resolves to the root project directory (where app/ and uploads/ live)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    STORAGE_FILE_NAME: str = "original"

    # Upload Constraints & Validation Settings
    MAX_FILE_SIZE_MB: int = 20
    CHUNK_SIZE_BYTES: int = 1024 * 1024  # 1MB chunk size for streaming file I/O

    ALLOWED_EXTENSIONS: Set[str] = {"pdf", "docx"}
    ALLOWED_MIME_TYPES: Set[str] = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    @computed_field
    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    # Future: PostgreSQL Database (Phase 2)
    DATABASE_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
