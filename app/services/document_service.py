import logging
import uuid
from typing import Sequence
from uuid import UUID
from fastapi import UploadFile

from app.core.exceptions import DatabaseError, DocumentNotFoundError
from app.models.document import DocumentModel
from app.repositories import DocumentRepository
from app.schemas import DocumentResponse, DocumentStatus
from app.storage import BaseStorage, get_storage
from app.validators import DocumentValidator, get_validator

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Business service layer orchestrating the document lifecycle:
    1. Validates file through the 6-stage validation pipeline.
    2. Generates a unique document_id (UUID4).
    3. Persists the file to storage (LocalStorage / S3 via BaseStorage).
    4. Persists document metadata into PostgreSQL via DocumentRepository.
    5. Dual-Persistence Rollback: Purges physical storage if DB transaction fails.
    6. Exposes query methods for document status and metadata inspection.
    """

    def __init__(
        self,
        repository: DocumentRepository,
        storage: BaseStorage | None = None,
        validator: DocumentValidator | None = None,
    ) -> None:
        self.repository: DocumentRepository = repository
        self.storage: BaseStorage = storage or get_storage()
        self.validator: DocumentValidator = validator or get_validator()

    async def upload_document(self, file: UploadFile) -> DocumentResponse:
        """
        Executes the end-to-end upload, validation, and dual-persistence workflow.

        Args:
            file: Incoming FastAPI UploadFile stream.

        Returns:
            DocumentResponse containing validated and persisted document metadata.

        Raises:
            DocumentValidationError: If any validation stage fails.
            StorageError: If saving the file to disk fails.
            DatabaseError: If database persistence fails (triggers storage rollback).
        """
        raw_filename = file.filename or "unknown"
        logger.info(f"Initiating document upload workflow for file: '{raw_filename}'")

        # Stage 1 to 6: Execute validation pipeline
        validation = await self.validator.validate(file)
        logger.info(
            f"Validation passed for '{validation.filename}' | "
            f"Format: {validation.extension.upper()} | Size: {validation.size_bytes} bytes"
        )

        # Generate unique document identity
        document_id = uuid.uuid4()
        logger.debug(f"Assigned document_id='{document_id}' to '{validation.filename}'")

        # Persist file using the storage strategy
        saved_path, bytes_written = await self.storage.save(
            file=file,
            document_id=document_id,
            extension=validation.extension,
        )
        logger.info(
            f"Document stored successfully on disk: doc_id={document_id} | "
            f"Path='{saved_path}' | Bytes={bytes_written}"
        )

        # Construct database entity
        doc_record = DocumentModel(
            id=document_id,
            filename=validation.filename,
            file_path=str(saved_path),
            file_size_bytes=bytes_written,
            mime_type=validation.mime_type,
            extension=validation.extension,
            status=DocumentStatus.UPLOADED.value,
        )

        # Persist metadata to database with Dual-Persistence Rollback
        try:
            persisted_doc = await self.repository.create(doc_record)
        except Exception as exc:
            logger.error(
                f"Database persistence failed for document_id={document_id}. "
                f"Executing dual-persistence storage rollback. Error: {exc}"
            )
            # Rollback: Clean up physical file to prevent orphan files
            await self.storage.delete(document_id)
            raise DatabaseError(
                message=f"Failed to record document metadata in database: {exc}",
                details={"document_id": str(document_id), "original_error": str(exc)},
            ) from exc

        logger.info(
            f"Upload workflow and DB persistence completed successfully for document_id={document_id}"
        )

        return DocumentResponse(
            document_id=persisted_doc.id,
            filename=persisted_doc.filename,
            extension=persisted_doc.extension,
            mime_type=persisted_doc.mime_type,
            size_bytes=persisted_doc.file_size_bytes,
            status=DocumentStatus(persisted_doc.status),
            created_at=persisted_doc.created_at,
            message="Document uploaded, validated, and persisted successfully",
        )

    async def get_document(self, document_id: UUID) -> DocumentResponse:
        """
        Retrieves document metadata by its unique identifier.

        Args:
            document_id: UUID of the document.

        Returns:
            DocumentResponse with metadata and current status.

        Raises:
            DocumentNotFoundError: If no record exists for the given ID.
        """
        doc = await self.repository.get_by_id(document_id)
        if not doc:
            raise DocumentNotFoundError(
                message=f"Document with ID '{document_id}' was not found.",
                details={"document_id": str(document_id)},
            )
        return DocumentResponse(
            document_id=doc.id,
            filename=doc.filename,
            extension=doc.extension,
            mime_type=doc.mime_type,
            size_bytes=doc.file_size_bytes,
            status=DocumentStatus(doc.status),
            created_at=doc.created_at,
            message="Document metadata retrieved successfully",
        )

    async def list_documents(
        self, skip: int = 0, limit: int = 20
    ) -> Sequence[DocumentResponse]:
        """
        Retrieves a paginated list of uploaded documents ordered by creation time descending.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            List of DocumentResponse DTOs.
        """
        docs = await self.repository.list_all(skip=skip, limit=limit)
        return [
            DocumentResponse(
                document_id=doc.id,
                filename=doc.filename,
                extension=doc.extension,
                mime_type=doc.mime_type,
                size_bytes=doc.file_size_bytes,
                status=DocumentStatus(doc.status),
                created_at=doc.created_at,
                message="Document metadata retrieved successfully",
            )
            for doc in docs
        ]

