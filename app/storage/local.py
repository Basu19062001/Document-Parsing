import shutil
from pathlib import Path
from uuid import UUID
from fastapi import UploadFile

from app.core.config import settings
from app.storage.base import BaseStorage
from app.core.exceptions import StorageDeleteError, StorageWriteError


class LocalStorage(BaseStorage):
    """
    Concrete implementation of BaseStorage using the local filesystem.
    Stores files under: <upload_dir>/<document_id>/original.<extension>
    """

    def __init__(
        self,
        upload_dir: Path | None = None,
        chunk_size: int | None = None,
        file_name_prefix: str | None = None,
        max_file_size_bytes: int | None = None,
    ) -> None:
        self.upload_dir: Path = upload_dir or settings.UPLOAD_DIR
        self.chunk_size: int = chunk_size or settings.CHUNK_SIZE_BYTES
        self.file_name_prefix: str = file_name_prefix or settings.STORAGE_FILE_NAME
        self.max_file_size_bytes: int = max_file_size_bytes or settings.MAX_FILE_SIZE_BYTES

    def get_document_dir(self, document_id: UUID) -> Path:
        """Returns the directory path dedicated to a specific document."""
        return self.upload_dir / str(document_id)

    def get_file_path(self, document_id: UUID, extension: str) -> Path:
        """Returns the full path to the stored original file."""
        return self.get_document_dir(document_id) / f"{self.file_name_prefix}.{extension}"

    def exists(self, document_id: UUID, extension: str) -> bool:
        """Checks if the document file exists on disk."""
        return self.get_file_path(document_id, extension).is_file()

    async def save(
        self, 
        file: UploadFile, 
        document_id: UUID, 
        extension: str
    ) -> tuple[Path, int]:
        """
        Saves an uploaded file stream to disk in chunks to prevent memory spikes.
        Performs automatic cleanup (rollback) if any failure occurs.
        """
        doc_dir = self.get_document_dir(document_id)
        file_path = self.get_file_path(document_id, extension)
        bytes_written = 0

        try:
            # Ensure document directory exists
            doc_dir.mkdir(parents=True, exist_ok=True)

            # Stream chunks to disk
            with open(file_path, "wb") as destination:
                while chunk := await file.read(self.chunk_size):
                    bytes_written += len(chunk)

                    # Defensive check during write
                    if bytes_written > self.max_file_size_bytes:
                        raise StorageWriteError(
                            f"File size exceeded maximum limit of {self.max_file_size_bytes} bytes."
                        )

                    destination.write(chunk)

            return file_path, bytes_written

        except Exception as exc:
            # Transactional Rollback: Remove corrupted or partially written directory
            await self.delete(document_id)
            if isinstance(exc, StorageWriteError):
                raise
            raise StorageWriteError(f"Failed to write file to local disk: {exc}") from exc

        finally:
            # Rewind file pointer so other components (validators/parsers) can read if needed
            await file.seek(0)

    async def delete(self, document_id: UUID) -> bool:
        """
        Deletes the entire document directory and all its contents.
        """
        doc_dir = self.get_document_dir(document_id)
        if not doc_dir.exists():
            return False

        try:
            shutil.rmtree(doc_dir)
            return True
        except Exception as exc:
            raise StorageDeleteError(
                f"Failed to delete document directory '{doc_dir}': {exc}"
            ) from exc
