from app.services.document_service import DocumentService
from app.storage import get_storage
from app.validators import get_validator

def get_document_service() -> DocumentService:
    """
    Factory provider for FastAPI dependency injection.
    Creates DocumentService with injected storage and validator strategies.
    """
    storage = get_storage()
    validator = get_validator()
    return DocumentService(
        storage=storage,      
        validator=validator,
    )


__all__ = [
    "DocumentService",
    "get_document_service",
]
