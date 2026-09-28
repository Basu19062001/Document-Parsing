from datetime import datetime
import logging
import uuid
from pathlib import Path
from typing import Sequence
from uuid import UUID
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    CorruptedParsingError,
    DatabaseError,
    DocumentAlreadyProcessingError,
    DocumentNotFoundError,
    DocumentNotParsedError,
    ParsingError,
    StorageFileNotFoundError,
)
from app.models.document import DocumentModel
from app.parsers import ParserFactory
from app.repositories import DocumentRepository
from app.schemas import (
    DocumentParseResponse,
    DocumentResponse,
    DocumentStatus,
)
from app.schemas.parsing import ParsedDocument
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

        # Store clean, relative path in DB (e.g. 'uploads/<doc_id>/original.pdf')
        # This keeps database records portable across environments and prevents leaking server drive paths
        try:
            rel_file_path = Path(saved_path).relative_to(settings.BASE_DIR).as_posix()
        except ValueError:
            rel_file_path = Path(saved_path).as_posix()

        # Construct database entity
        doc_record = DocumentModel(
            id=document_id,
            filename=validation.filename,
            file_path=rel_file_path,
            file_size_bytes=bytes_written,
            mime_type=validation.mime_type,
            extension=validation.extension,
            status=DocumentStatus.UPLOADED.value,
        )

        # Persist metadata to database with Dual-Persistence Rollback
        try:
            persisted_doc = await self.repository.create(doc_record)
        except DatabaseError as db_err:
            logger.error(
                f"Database persistence failed for document_id={document_id}. "
                f"Executing dual-persistence storage rollback."
            )
            try:
                await self.storage.delete(document_id)
            except Exception as rollback_err:
                logger.critical(
                    f"CRITICAL: Storage rollback failed for doc_id={document_id}. "
                    f"Orphan file may exist! Rollback error: {rollback_err}"
                )
            raise db_err
        except Exception as exc:
            logger.error(
                f"Unexpected failure during DB persistence for document_id={document_id}. "
                f"Executing dual-persistence storage rollback. Error: {exc}"
            )
            try:
                await self.storage.delete(document_id)
            except Exception as rollback_err:
                logger.critical(
                    f"CRITICAL: Storage rollback failed for doc_id={document_id}. "
                    f"Orphan file may exist! Rollback error: {rollback_err}"
                )
            raise DatabaseError(
                message="An unexpected error occurred while persisting document metadata.",
                details={"document_id": str(document_id)},
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

    async def parse_document(
        self,
        document_id: UUID,
        force: bool = False,
        strict_mode: bool | None = None,
    ) -> DocumentParseResponse:
        """
        Orchestrates the document parsing workflow and state machine transitions:
        1. Validates document existence in PostgreSQL (throws DocumentNotFoundError).
        2. Enforces state machine concurrency guards (rejects concurrent PROCESSING;
           returns cached AST summary if already PARSED and not forced).
        3. Transitions status to PROCESSING.
        4. Resolves portable stored path to verified physical filesystem path.
        5. Obtains singleton parser strategy via ParserFactory.
        6. Executes non-blocking parsing.
        7. Persists the complete canonical AST into PostgreSQL JSONB.
        8. Returns a lightweight DocumentParseResponse (Command-Query Separation).
           The full canonical AST can be fetched at any time via get_parsed_document().

        Args:
            document_id: UUID of the document entity.
            force: If True, forces re-parsing even if already in PARSED state.
            strict_mode: Optional boolean override for parsing compliance.

        Returns:
            DocumentParseResponse containing status confirmation and extraction metrics.

        Raises:
            DocumentNotFoundError: If the document record does not exist.
            DocumentAlreadyProcessingError: If document is currently being parsed.
            StorageFileNotFoundError: If the source physical file is missing from disk.
            ParsingError: If extraction fails unrecoverably.
        """
        # Step 1: Verify document existence
        doc = await self.repository.get_by_id(document_id)
        if not doc:
            raise DocumentNotFoundError(
                message=f"Document with ID '{document_id}' was not found.",
                details={"document_id": str(document_id)},
            )

        # Step 2: Enforce Finite State Machine concurrency & idempotency
        if doc.status == DocumentStatus.PROCESSING.value:
            logger.warning(f"Rejecting parse request for doc_id={document_id}: already in PROCESSING state.")
            raise DocumentAlreadyProcessingError(
                message="Document is currently being parsed. Please wait for completion.",
                details={"document_id": str(document_id), "status": doc.status},
            )

        if doc.status == DocumentStatus.PARSED.value and not force:
            if doc.parsed_content:
                logger.info(f"Returning cached database AST summary for doc_id={document_id} (idempotent call).")
                elements_count = len(doc.parsed_content.get("elements", []))
                warnings_count = len(doc.parsed_content.get("warnings", []))
                parsed_at_raw = doc.parsed_content.get("parsed_at")
                parsed_at = datetime.fromisoformat(parsed_at_raw) if parsed_at_raw else doc.updated_at
                return DocumentParseResponse(
                    document_id=doc.id,
                    filename=doc.filename,
                    status=DocumentStatus.PARSED,
                    total_pages=doc.total_pages,
                    word_count=doc.word_count or 0,
                    char_count=doc.char_count or 0,
                    total_elements=elements_count,
                    warnings_count=warnings_count,
                    parsed_at=parsed_at,
                    message="Document already parsed (cached result)",
                )

        # Step 3: Transition state to PROCESSING
        logger.info(f"Transitioning doc_id={document_id} to PROCESSING status.")
        await self.repository.update_status(document_id, DocumentStatus.PROCESSING.value)

        # Step 4: Resolve physical file path on disk
        absolute_path = (settings.BASE_DIR / doc.file_path).resolve()
        if not absolute_path.exists():
            # Secondary fallback check relative to storage root
            fallback_path = (self.storage.base_dir / str(doc.id) / f"original.{doc.extension}").resolve()
            if fallback_path.exists():
                absolute_path = fallback_path
            else:
                logger.error(f"Source file missing from storage for doc_id={document_id} at '{absolute_path}'")
                err_msg = "Physical document file is missing from storage."
                await self.repository.update_status(
                    entity_id=document_id,
                    status=DocumentStatus.FAILED.value,
                    error_message=err_msg,
                )
                raise StorageFileNotFoundError(
                    message=err_msg,
                    details={"document_id": str(document_id), "expected_path": str(absolute_path)},
                )

        # Step 5: Resolve parser strategy from ParserFactory
        norm_ext = f".{doc.extension}" if not doc.extension.startswith(".") else doc.extension
        parser = ParserFactory.get_parser(mime_type=doc.mime_type, extension=norm_ext)
        logger.info(
            f"Resolved parser strategy '{parser.__class__.__name__}' for doc_id={document_id} "
            f"(MIME='{doc.mime_type}', Ext='{norm_ext}')"
        )

        # Step 6 & 7: Execute parsing and persist AST directly to PostgreSQL JSONB
        try:
            parsed_doc = await parser.parse(
                file_path=absolute_path,
                document_id=doc.id,
                filename=doc.filename,
                strict_mode=strict_mode,
            )

            # Serialize AST model to JSON-compatible dictionary for PostgreSQL JSONB
            ast_dict = parsed_doc.model_dump(mode="json")

            await self.repository.save_parsed_result(
                entity_id=doc.id,
                parsed_content=ast_dict,
                word_count=parsed_doc.word_count,
                char_count=parsed_doc.char_count,
                total_pages=parsed_doc.total_pages,
            )

            logger.info(
                f"Document parsing successfully persisted to PostgreSQL for doc_id={document_id} | "
                f"Elements={len(parsed_doc.elements)}, Words={parsed_doc.word_count}, "
                f"Warnings={len(parsed_doc.warnings)}"
            )
            return DocumentParseResponse(
                document_id=doc.id,
                filename=doc.filename,
                status=DocumentStatus.PARSED,
                total_pages=parsed_doc.total_pages,
                word_count=parsed_doc.word_count,
                char_count=parsed_doc.char_count,
                total_elements=len(parsed_doc.elements),
                warnings_count=len(parsed_doc.warnings),
                parsed_at=parsed_doc.parsed_at,
                message="Document parsed and persisted successfully",
            )

        except AppException as app_exc:
            # Domain parsing exception (EncryptedDocumentError, EmptyDocumentError, CorruptedParsingError)
            logger.warning(
                f"Domain parsing exception caught for doc_id={document_id}: {app_exc.message}"
            )
            await self.repository.update_status(
                entity_id=document_id,
                status=DocumentStatus.FAILED.value,
                error_message=app_exc.message,
            )
            raise

        except Exception as exc:
            # Unhandled parser crash
            logger.error(
                f"Unhandled parsing error for doc_id={document_id}: {exc}",
                exc_info=True,
            )
            sanitized_msg = "An unexpected error occurred while parsing the document."
            await self.repository.update_status(
                entity_id=document_id,
                status=DocumentStatus.FAILED.value,
                error_message=sanitized_msg,
            )
            raise ParsingError(
                message=sanitized_msg,
                details={"document_id": str(document_id)},
            ) from exc

    async def get_parsed_document(self, document_id: UUID) -> ParsedDocument:
        """
        Retrieves the persisted canonical AST of a parsed document from PostgreSQL JSONB.

        Args:
            document_id: UUID of the document entity.

        Returns:
            ParsedDocument containing the full AST elements and metrics.

        Raises:
            DocumentNotFoundError: If the document does not exist in database.
            DocumentAlreadyProcessingError: If parsing is still actively in progress.
            CorruptedParsingError: If previous parsing attempt failed.
            DocumentNotParsedError: If document is still in UPLOADED state.
        """
        doc = await self.repository.get_by_id(document_id)
        if not doc:
            raise DocumentNotFoundError(
                message=f"Document with ID '{document_id}' was not found.",
                details={"document_id": str(document_id)},
            )

        if doc.status == DocumentStatus.PROCESSING.value:
            raise DocumentAlreadyProcessingError(
                message="Document is currently being parsed. Please wait for completion.",
                details={"document_id": str(document_id), "status": doc.status},
            )

        if doc.status == DocumentStatus.FAILED.value:
            raise CorruptedParsingError(
                message=f"Document parsing failed previously: {doc.error_message or 'Unknown error'}",
                details={"document_id": str(document_id), "error_message": doc.error_message},
            )

        if doc.status == DocumentStatus.UPLOADED.value or not doc.parsed_content:
            raise DocumentNotParsedError(
                message="Document has not been parsed yet. Trigger the parse endpoint first.",
                details={"document_id": str(document_id), "status": doc.status},
            )

        return ParsedDocument.model_validate(doc.parsed_content)


