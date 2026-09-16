from app.validators.base import DocumentStructureValidator
from app.validators.pipeline import DocumentValidator, ValidationResult

# Default singleton instance for convenience and dependency injection
_validator = DocumentValidator()


async def validate_document(file) -> ValidationResult:
    """Convenience function to run the 6-stage validation pipeline on an UploadFile."""
    return await _validator.validate(file)


def get_validator() -> DocumentValidator:
    """Factory provider for FastAPI dependency injection."""
    return _validator


__all__ = [
    "DocumentValidator",
    "ValidationResult",
    "DocumentStructureValidator",
    "validate_document",
    "get_validator",
]
