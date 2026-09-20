import uuid
from sqlalchemy import BigInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.schemas.document import DocumentStatus


class DocumentModel(Base, TimestampMixin):
    """
    SQLAlchemy ORM Model mapping to the 'documents' database table.
    Stores core metadata, file locations, and ingestion lifecycle states.
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique identifier matching the document_id across the system",
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original uploaded file name",
    )

    file_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Physical or storage path to the original document",
    )

    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        doc="Verified file size in bytes",
    )

    mime_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Validated MIME type of the document",
    )

    extension: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="File extension without leading dot (e.g. pdf, docx)",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default=DocumentStatus.UPLOADED.value,
        nullable=False,
        index=True,
        doc="Current document lifecycle state (uploaded, processing, parsed, failed)",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error message details if document processing or parsing fails",
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentModel(id={self.id}, filename='{self.filename}', "
            f"status='{self.status}', size={self.file_size_bytes})>"
        )
