from pathlib import Path
from typing import Set
from urllib.parse import quote_plus
from pydantic import computed_field, model_validator
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

    # Database Configuration (PostgreSQL + asyncpg)
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "document_parsing_db"
    DATABASE_URL: str | None = None

    # Connection Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        """
        Dynamically builds DATABASE_URL from individual credentials if not explicitly provided.
        Safely encodes passwords containing special characters (e.g. @, :, /).
        """
        if not self.DATABASE_URL:
            encoded_password = quote_plus(self.DB_PASSWORD)
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DB_USER}:{encoded_password}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        return self

    # Documentation Access Credentials (HTTP Basic Auth)
    DOCS_USERNAME: str = "admin"
    DOCS_PASSWORD: str = "admin123"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
