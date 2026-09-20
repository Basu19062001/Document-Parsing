from abc import ABC, abstractmethod
from typing import Generic, Optional, Sequence, TypeVar
from uuid import UUID

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """
    Abstract Base Repository interface (Repository Pattern).
    Defines generic data access operations, isolating storage mechanisms from business rules.
    """

    @abstractmethod
    async def create(self, entity: T) -> T:
        """Persists a new entity into the database."""
        pass

    @abstractmethod
    async def get_by_id(self, entity_id: UUID) -> Optional[T]:
        """Retrieves an entity by its primary key UUID."""
        pass

    @abstractmethod
    async def list_all(self, skip: int = 0, limit: int = 20) -> Sequence[T]:
        """Retrieves a paginated collection of entities."""
        pass

    @abstractmethod
    async def delete(self, entity_id: UUID) -> bool:
        """Deletes an entity by its UUID."""
        pass
