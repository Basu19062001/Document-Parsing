from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.base import BaseRepository
from app.repositories.document_repository import DocumentRepository


def get_document_repository(
    session: AsyncSession = Depends(get_db),
) -> DocumentRepository:
    """
    FastAPI dependency provider for DocumentRepository.
    Injects an active AsyncSession managed by get_db().
    """
    return DocumentRepository(session=session)


__all__ = [
    "BaseRepository",
    "DocumentRepository",
    "get_document_repository",
]
