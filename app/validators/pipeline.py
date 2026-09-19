import logging
from dataclasses import dataclass
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import (
    EmptyFileError,
    FileSizeLimitExceededError,
    InvalidMagicBytesError,
    InvalidMimeTypeError,
    UnsupportedExtensionError,
)
from app.validators.strategies import get_structure_validator

logger = logging.getLogger("app.validators.pipeline")


@dataclass(frozen=True)
class ValidationResult:
    """Immutable result object produced by a successful validation pipeline."""
    filename: str
    extension: str
    mime_type: str
    size_bytes: int


# Mapping of allowed extensions to expected MIME types and Magic Bytes
_EXPECTED_MIME_TYPES: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",  # Some clients or OS send ZIP mime type for docx
    },
}

_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF-",
    "docx": b"PK\x03\x04",
}


class DocumentValidator:
    """
    Orchestrates the 6-stage document validation pipeline.
    Ensures that uploaded documents are well-formed, safe, and uncorrupted.
    """

    def __init__(
        self,
        max_file_size_bytes: int | None = None,
        chunk_size_bytes: int | None = None,
    ) -> None:
        self.max_file_size_bytes = max_file_size_bytes or settings.MAX_FILE_SIZE_BYTES
        self.chunk_size_bytes = chunk_size_bytes or settings.CHUNK_SIZE_BYTES

    async def validate(self, file: UploadFile) -> ValidationResult:
        """
        Executes the 6-stage validation pipeline on the uploaded file.
        
        Stages:
            1. Presence & Empty Check
            2. File Size Pre-validation
            3. Extension Whitelist Check
            4. MIME Type Consistency Check
            5. File Signature / Magic-Byte Check
            6. Deep Document Structural Integrity Check
            7. Accept & Return ValidationResult
        """
        raw_filename = file.filename or "unknown"
        logger.debug(f"Starting 6-stage validation pipeline for file: '{raw_filename}'")

        # =====================================================================
        # Stage 1: Presence Check
        # =====================================================================
        if file is None or not file.filename or not file.filename.strip():
            logger.warning("Stage 1 Failed: File is missing or filename is empty.")
            raise EmptyFileError("No document was provided or filename is empty.")

        filename = file.filename.strip()

        # =====================================================================
        # Stage 2: Fast File Size Pre-check (if size reported by client)
        # =====================================================================
        if file.size is not None and file.size > self.max_file_size_bytes:
            logger.warning(
                f"Stage 2 Failed: Reported file size ({file.size} bytes) "
                f"exceeds limit ({self.max_file_size_bytes} bytes)."
            )
            raise FileSizeLimitExceededError(
                f"File size ({file.size} bytes) exceeds limit of {self.max_file_size_bytes} bytes.",
                details={"file_size_bytes": file.size, "max_limit_bytes": self.max_file_size_bytes}
            )

        # =====================================================================
        # Stage 3: Extension Whitelist Validation
        # =====================================================================
        if "." not in filename:
            logger.warning(f"Stage 3 Failed: Filename '{filename}' has no extension.")
            raise UnsupportedExtensionError(
                "Document filename lacks an extension.",
                details={"filename": filename}
            )

        extension = filename.rsplit(".", 1)[-1].lower()
        if extension not in settings.ALLOWED_EXTENSIONS:
            logger.warning(
                f"Stage 3 Failed: Extension '.{extension}' not allowed. Permitted: {settings.ALLOWED_EXTENSIONS}"
            )
            raise UnsupportedExtensionError(
                f"Extension '.{extension}' is not permitted. Allowed: {list(settings.ALLOWED_EXTENSIONS)}",
                details={"extension": extension, "allowed": list(settings.ALLOWED_EXTENSIONS)}
            )

        # =====================================================================
        # Stage 4: MIME Type Consistency Validation
        # =====================================================================
        content_type = (file.content_type or "").lower().strip()
        expected_mimes = _EXPECTED_MIME_TYPES.get(extension, set())

        if content_type not in expected_mimes:
            logger.warning(
                f"Stage 4 Failed: MIME type '{content_type}' is invalid for extension '.{extension}'."
            )
            raise InvalidMimeTypeError(
                f"MIME type '{content_type}' is invalid for extension '.{extension}'.",
                details={
                    "received_mime_type": content_type,
                    "expected_mime_types": list(expected_mimes)
                }
            )

        # =====================================================================
        # Read content safely with size tracking & non-destructive seek
        # =====================================================================
        try:
            # Stage 5: File Signature / Magic-Byte Check
            magic_prefix = _MAGIC_BYTES[extension]
            header = await file.read(len(magic_prefix))
            
            if len(header) == 0:
                logger.warning(f"Stage 5 Failed: File '{filename}' is empty (0 bytes).")
                raise EmptyFileError("Uploaded file contains 0 bytes.")

            if header != magic_prefix:
                logger.warning(
                    f"Stage 5 Failed: Magic byte mismatch for '.{extension}'. "
                    f"Expected {magic_prefix}, got {header}."
                )
                raise InvalidMagicBytesError(
                    f"File signature mismatch for '.{extension}'. File content does not match extension.",
                    details={"extension": extension}
                )

            logger.debug(f"Stage 5 Passed: Magic bytes confirmed for '.{extension}'")

            # Read remaining bytes for Stage 6 while tracking size
            chunks: list[bytes] = [header]
            total_bytes = len(header)

            while chunk := await file.read(self.chunk_size_bytes):
                total_bytes += len(chunk)
                if total_bytes > self.max_file_size_bytes:
                    logger.warning(
                        f"Stage 2 Failed during stream read: Total bytes ({total_bytes}) "
                        f"exceeded maximum limit of {self.max_file_size_bytes} bytes."
                    )
                    raise FileSizeLimitExceededError(
                        f"File size exceeded maximum limit of {self.max_file_size_bytes} bytes.",
                        details={"max_limit_bytes": self.max_file_size_bytes}
                    )
                chunks.append(chunk)

            file_content = b"".join(chunks)

            # =================================================================
            # Stage 6: Actual Document Structure Validation (Strategy Pattern)
            # =================================================================
            logger.debug(f"Stage 6: Dispatching deep structural check for '{filename}' ({extension})")
            structure_validator = get_structure_validator(extension)
            structure_validator.validate_structure(file_content)
            logger.debug(f"Stage 6 Passed: Structural integrity confirmed for '{filename}'")

            # =================================================================
            # Stage 7: Accept
            # =================================================================
            logger.info(
                f"Validation Pipeline Complete: '{filename}' accepted ({extension}, {total_bytes} bytes)"
            )
            return ValidationResult(
                filename=filename,
                extension=extension,
                mime_type=content_type,
                size_bytes=total_bytes,
            )

        finally:
            # Clean Code: Always rewind the file stream pointer so downstream 
            # storage or parsers can read the stream from byte 0.
            await file.seek(0)
