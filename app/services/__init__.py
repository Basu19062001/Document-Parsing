from fastapi import Depends

from app.repositories import DocumentRepository, get_document_repository
from app.services.document_service import DocumentService
from app.storage import BaseStorage, get_storage
from app.validators import DocumentValidator, get_validator


def get_document_service(
    repository: DocumentRepository = Depends(get_document_repository),
    storage: BaseStorage = Depends(get_storage),
    validator: DocumentValidator = Depends(get_validator),
) -> DocumentService:
    """
    Factory provider for FastAPI dependency injection.
    Creates DocumentService with injected repository, storage, and validator strategies.
    """
    return DocumentService(
        repository=repository,
        storage=storage,
        validator=validator,
    )


__all__ = [
    "DocumentService",
    "get_document_service",
]

