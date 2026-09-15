from datetime import datetime, timezone
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class DocumentStatus(str, Enum):
    """
    Lifecycle status of a document in the ingestion pipeline.
    Avoids string primitives across the codebase.
    """
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PARSED = "parsed"
    FAILED = "failed"


class DocumentBase(BaseModel):
    """Base document metadata attributes shared across schemas."""
    filename: str = Field(
        ..., 
        description="Original name of the uploaded document",
        examples=["financial_report.pdf"]
    )
    extension: str = Field(
        ..., 
        description="File extension without the dot",
        examples=["pdf", "docx"]
    )
    mime_type: str = Field(
        ..., 
        description="Validated MIME type of the document",
        examples=["application/pdf"]
    )
    size_bytes: int = Field(
        ..., 
        description="File size in bytes",
        examples=[2097152]
    )


class DocumentMetadata(DocumentBase):
    """
    Metadata representation of the document.
    Useful for internal service communication and future database mapping.
    """
    document_id: UUID = Field(
        ..., 
        description="Unique identifier for the document"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of upload in UTC"
    )


class DocumentResponse(BaseModel):
    """
    DTO (Data Transfer Object) returned to the client upon successful upload.
    Hides internal storage paths and exposes only relevant consumer data.
    """
    document_id: UUID = Field(
        ..., 
        description="Unique identifier assigned to the document"
    )
    filename: str = Field(
        ..., 
        description="Original name of the uploaded file"
    )
    extension: str = Field(
        ..., 
        description="Document extension"
    )
    mime_type: str = Field(
        ..., 
        description="MIME type confirmed by validation"
    )
    size_bytes: int = Field(
        ..., 
        description="Total size in bytes"
    )
    status: DocumentStatus = Field(
        default=DocumentStatus.UPLOADED,
        description="Current processing status"
    )
    created_at: datetime = Field(
        ..., 
        description="UTC timestamp when the document was received"
    )
    message: str = Field(
        default="Document uploaded and validated successfully",
        description="Human-readable operation summary"
    )

    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True
    )
