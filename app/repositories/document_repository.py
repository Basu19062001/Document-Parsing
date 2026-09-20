import logging
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentModel
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository[DocumentModel]):
    """
    Concrete data repository for DocumentModel operations in PostgreSQL.
    Encapsulates all SQLAlchemy queries for the 'documents' table.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entity: DocumentModel) -> DocumentModel:
        """Persists a new document record into PostgreSQL."""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        logger.debug(f"Persisted DocumentModel record: id={entity.id}, filename='{entity.filename}'")
        return entity

    async def get_by_id(self, entity_id: UUID) -> Optional[DocumentModel]:
        """Finds a document record by its UUID primary key."""
        query = select(DocumentModel).where(DocumentModel.id == entity_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        entity_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[DocumentModel]:
        """Updates the ingestion status and error details for a document."""
        document = await self.get_by_id(entity_id)
        if not document:
            return None
        document.status = status
        if error_message is not None:
            document.error_message = error_message
        await self.session.flush()
        await self.session.refresh(document)
        logger.debug(f"Updated status for doc_id={entity_id} to '{status}'")
        return document

    async def list_all(self, skip: int = 0, limit: int = 20) -> Sequence[DocumentModel]:
        """Retrieves a paginated collection of documents ordered by creation date descending."""
        query = (
            select(DocumentModel)
            .order_by(DocumentModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def delete(self, entity_id: UUID) -> bool:
        """Deletes a document record from PostgreSQL."""
        document = await self.get_by_id(entity_id)
        if not document:
            return False
        await self.session.delete(document)
        await self.session.flush()
        logger.debug(f"Deleted DocumentModel record for doc_id={entity_id}")
        return True
