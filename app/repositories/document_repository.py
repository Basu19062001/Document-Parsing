import logging
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseError
from app.models.document import DocumentModel
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository[DocumentModel]):
    """
    Concrete data repository for DocumentModel operations in PostgreSQL.
    Encapsulates all SQLAlchemy queries for the 'documents' table.
    Applies the Exception Translation pattern to convert low-level SQLAlchemy
    errors into domain-level DatabaseError exceptions.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entity: DocumentModel) -> DocumentModel:
        """Persists a new document record into PostgreSQL."""
        try:
            self.session.add(entity)
            await self.session.flush()
            await self.session.refresh(entity)
            logger.debug(
                f"Persisted DocumentModel record: id={entity.id}, filename='{entity.filename}'"
            )
            return entity
        except SQLAlchemyError as exc:
            logger.error(
                f"Failed to persist DocumentModel record id={entity.id}: {exc}",
                exc_info=True,
            )
            raise DatabaseError(
                message=f"Database error while saving document: {exc}",
                details={
                    "operation": "create",
                    "document_id": str(entity.id),
                    "filename": entity.filename,
                },
            ) from exc

    async def get_by_id(self, entity_id: UUID) -> Optional[DocumentModel]:
        """Finds a document record by its UUID primary key."""
        try:
            query = select(DocumentModel).where(DocumentModel.id == entity_id)
            result = await self.session.execute(query)
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                f"Failed to fetch DocumentModel record id={entity_id}: {exc}",
                exc_info=True,
            )
            raise DatabaseError(
                message=f"Database error while fetching document: {exc}",
                details={"operation": "get_by_id", "document_id": str(entity_id)},
            ) from exc

    async def update_status(
        self,
        entity_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[DocumentModel]:
        """Updates the ingestion status and error details for a document."""
        try:
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
        except DatabaseError:
            raise
        except SQLAlchemyError as exc:
            logger.error(
                f"Failed to update status for document id={entity_id}: {exc}",
                exc_info=True,
            )
            raise DatabaseError(
                message=f"Database error while updating document status: {exc}",
                details={
                    "operation": "update_status",
                    "document_id": str(entity_id),
                    "status": status,
                },
            ) from exc

    async def list_all(self, skip: int = 0, limit: int = 20) -> Sequence[DocumentModel]:
        """Retrieves a paginated collection of documents ordered by creation date descending."""
        try:
            query = (
                select(DocumentModel)
                .order_by(DocumentModel.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            result = await self.session.execute(query)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.error(
                f"Failed to retrieve documents page (skip={skip}, limit={limit}): {exc}",
                exc_info=True,
            )
            raise DatabaseError(
                message=f"Database error while retrieving documents: {exc}",
                details={"operation": "list_all", "skip": skip, "limit": limit},
            ) from exc

    async def delete(self, entity_id: UUID) -> bool:
        """Deletes a document record from PostgreSQL."""
        try:
            document = await self.get_by_id(entity_id)
            if not document:
                return False
            await self.session.delete(document)
            await self.session.flush()
            logger.debug(f"Deleted DocumentModel record for doc_id={entity_id}")
            return True
        except DatabaseError:
            raise
        except SQLAlchemyError as exc:
            logger.error(
                f"Failed to delete document id={entity_id}: {exc}",
                exc_info=True,
            )
            raise DatabaseError(
                message=f"Database error while deleting document: {exc}",
                details={"operation": "delete", "document_id": str(entity_id)},
            ) from exc

