from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID
from fastapi import UploadFile


class BaseStorage(ABC):
    """
    Abstract storage interface (Strategy Pattern).
    Defines the contract that any storage backend (Local, S3, GCS) must fulfill.
    """

    @abstractmethod
    async def save(
        self, 
        file: UploadFile, 
        document_id: UUID, 
        extension: str
    ) -> tuple[Path, int]:
        """
        Saves an uploaded file stream into storage.
        
        Args:
            file: The incoming FastAPI UploadFile object.
            document_id: The unique UUID assigned to this document.
            extension: The validated file extension (without dot).

        Returns:
            A tuple of (saved_file_path, total_bytes_written).
        """
        pass

    @abstractmethod
    def get_file_path(self, document_id: UUID, extension: str) -> Path:
        """
        Retrieves the path or identifier of the stored original file.

        Args:
            document_id: Unique UUID of the document.
            extension: File extension of the stored document.

        Returns:
            Path to the stored file.
        """
        pass

    @abstractmethod
    def exists(self, document_id: UUID, extension: str) -> bool:
        """
        Checks whether the document exists in storage.

        Args:
            document_id: Unique UUID of the document.
            extension: File extension of the document.

        Returns:
            True if the file exists, False otherwise.
        """
        pass

    @abstractmethod
    async def delete(self, document_id: UUID) -> bool:
        """
        Deletes the document and its directory from storage (cleanup / rollback).

        Args:
            document_id: Unique UUID of the document to delete.

        Returns:
            True if successfully deleted, False if directory didn't exist.
        """
        pass
