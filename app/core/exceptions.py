from typing import Any, Dict, Optional


class AppException(Exception):
    """
    Base exception for all application and domain errors.
    Carries machine-readable error codes and HTTP status codes for global handling.
    """
    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


# =====================================================================
# Storage Layer Exceptions
# =====================================================================

class StorageError(AppException):
    """Base error for storage operations."""
    def __init__(
        self,
        message: str,
        error_code: str = "STORAGE_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class StorageWriteError(StorageError):
    """Raised when writing file chunks to storage fails."""
    def __init__(
        self, 
        message: str = "Failed to write file to storage.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="STORAGE_WRITE_FAILED",
            status_code=500,
            details=details,
        )


class StorageFileNotFoundError(StorageError):
    """Raised when a requested file does not exist in storage."""
    def __init__(
        self, 
        message: str = "The requested file was not found in storage.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="STORAGE_FILE_NOT_FOUND",
            status_code=404,
            details=details,
        )


class StorageDeleteError(StorageError):
    """Raised when deleting a file or directory fails."""
    def __init__(
        self, 
        message: str = "Failed to delete file or directory from storage.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="STORAGE_DELETE_FAILED",
            status_code=500,
            details=details,
        )


# =====================================================================
# Document Validation Exceptions (The 6-Stage Pipeline)
# =====================================================================

class DocumentValidationError(AppException):
    """Base error for all document validation failures."""
    def __init__(
        self,
        message: str,
        error_code: str = "VALIDATION_FAILED",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class EmptyFileError(DocumentValidationError):
    """Stage 1: File is missing or empty (0 bytes)."""
    def __init__(
        self, 
        message: str = "Uploaded file is empty.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="FILE_EMPTY",
            status_code=400,
            details=details,
        )


class FileSizeLimitExceededError(DocumentValidationError):
    """Stage 2: File exceeds the maximum allowed size (e.g. 20MB)."""
    def __init__(
        self, 
        message: str = "File size exceeds the maximum permitted limit.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="FILE_TOO_LARGE",
            status_code=413,  # Payload Too Large
            details=details,
        )


class UnsupportedExtensionError(DocumentValidationError):
    """Stage 3: File extension is not whitelisted."""
    def __init__(
        self, 
        message: str = "File extension is not supported.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_FILE_EXTENSION",
            status_code=415,  # Unsupported Media Type
            details=details,
        )


class InvalidMimeTypeError(DocumentValidationError):
    """Stage 4: MIME type header is invalid or does not match extension."""
    def __init__(
        self, 
        message: str = "File MIME type is invalid or unsupported.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_MIME_TYPE",
            status_code=415,  # Unsupported Media Type
            details=details,
        )


class InvalidMagicBytesError(DocumentValidationError):
    """Stage 5: Magic bytes / file signature does not match expected format."""
    def __init__(
        self, 
        message: str = "File signature does not match the claimed file type.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_FILE_SIGNATURE",
            status_code=422,  # Unprocessable Entity
            details=details,
        )


class CorruptedDocumentError(DocumentValidationError):
    """Stage 6: Document structure is broken, corrupted, or unreadable."""
    def __init__(
        self, 
        message: str = "Document structure is corrupted or unreadable.", 
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            message=message,
            error_code="CORRUPTED_DOCUMENT_STRUCTURE",
            status_code=422,  # Unprocessable Entity
            details=details,
        )
