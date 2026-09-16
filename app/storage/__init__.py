from app.core.config import settings
from app.storage.base import BaseStorage
from app.core.exceptions import (
    StorageDeleteError,
    StorageError,
    StorageFileNotFoundError,
    StorageWriteError,
)
from app.storage.local import LocalStorage


def get_storage() -> BaseStorage:
    """
    Dependency provider / Factory for the storage backend.
    Enables clean dependency injection in FastAPI routes and services.
    """
    return LocalStorage(
        upload_dir=settings.UPLOAD_DIR,
        chunk_size=settings.CHUNK_SIZE_BYTES,
        file_name_prefix=settings.STORAGE_FILE_NAME,
        max_file_size_bytes=settings.MAX_FILE_SIZE_BYTES,
    )


__all__ = [
    "BaseStorage",
    "LocalStorage",
    "StorageError",
    "StorageWriteError",
    "StorageFileNotFoundError",
    "StorageDeleteError",
    "get_storage",
]
