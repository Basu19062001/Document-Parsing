import logging
import uuid
from datetime import datetime, timezone
from fastapi import UploadFile

from app.schemas import DocumentResponse, DocumentStatus
from app.storage import BaseStorage, get_storage
from app.validators import DocumentValidator, get_validator

logger = logging.getLogger("app.service.document")


class DocumentService:
    """
    Business service layer orchestrating the document upload workflow:
    1. Validates file through the 6-stage validation pipeline.
    2. Generates a unique document_id (UUID4).
    3. Persists the file to storage (LocalStorage / S3 via BaseStorage).
    4. Constructs and returns the DocumentResponse DTO.
    """

    def __init__(
        self,
        storage: BaseStorage | None = None,
        validator: DocumentValidator | None = None,
    ) -> None:
        # Dependency Inversion: Accepts interfaces, falls back to default providers
        self.storage: BaseStorage = storage or get_storage()
        self.validator: DocumentValidator = validator or get_validator()

    async def upload_document(self, file: UploadFile) -> DocumentResponse:
        """
        Executes the end-to-end upload and validation workflow for an incoming document.

        Args:
            file: Incoming FastAPI UploadFile stream.

        Returns:
            DocumentResponse containing validated document metadata.

        Raises:
            DocumentValidationError: If any validation stage fails.
            StorageError: If saving the file to storage fails.
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

        # Assemble the public response contract
        response = DocumentResponse(
            document_id=document_id,
            filename=validation.filename,
            extension=validation.extension,
            mime_type=validation.mime_type,
            size_bytes=bytes_written,
            status=DocumentStatus.UPLOADED,
            created_at=datetime.now(timezone.utc),
            message="Document uploaded and validated successfully",
        )

        logger.info(f"Upload workflow completed successfully for document_id={document_id}")
        return response
