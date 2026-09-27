from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ElementType(str, Enum):
    """Semantic category of an extracted document component."""
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST_ITEM = "list_item"
    UNKNOWN = "unknown"


class BaseElement(BaseModel):
    """
    Abstract base element for all structural document AST nodes.
    Maintains sequential reading order and ancestor section breadcrumb hierarchy.
    """
    element_id: str = Field(
        ...,
        description="Unique sequential identifier (e.g. 'elem_0001')",
        examples=["elem_0001"],
    )
    reading_order: int = Field(
        ...,
        ge=0,
        description="0-indexed position in natural document reading sequence",
        examples=[0],
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed source page number (populated for PDFs, None for DOCX)",
        examples=[1],
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="Ancestral heading breadcrumb hierarchy (e.g. ['Chapter 1', 'Section 1.2'])",
        examples=[["1. Executive Summary", "1.1 Financial Highlights"]],
    )

    model_config = ConfigDict(frozen=True)


class HeadingElement(BaseElement):
    """
    Represents a section heading or document title with level hierarchy.
    """
    type: Literal[ElementType.HEADING, ElementType.TITLE] = Field(
        default=ElementType.HEADING,
        description="Element discriminator: heading or title",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Text content of the heading",
        examples=["1. Executive Summary"],
    )
    level: int = Field(
        ...,
        ge=1,
        le=6,
        description="Heading level depth (1 for H1, 2 for H2, up to 6 for H6)",
        examples=[1],
    )


class ParagraphElement(BaseElement):
    """
    Represents a standard text block or body paragraph.
    """
    type: Literal[ElementType.PARAGRAPH] = Field(
        default=ElementType.PARAGRAPH,
        description="Element discriminator: paragraph",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Text content of the paragraph",
        examples=["Total revenue grew by 24% year-over-year to $145M."],
    )


class TableElement(BaseElement):
    """
    Dual-representation table structure:
    Provides structured 2D cell grid for database/analytics
    and pre-rendered GitHub Flavored Markdown for LLM prompt ingestion.
    """
    type: Literal[ElementType.TABLE] = Field(
        default=ElementType.TABLE,
        description="Element discriminator: table",
    )
    headers: list[str] = Field(
        default_factory=list,
        description="Extracted table column header labels",
        examples=[["Quarter", "Revenue (M$)", "YoY Growth"]],
    )
    rows: list[list[str]] = Field(
        default_factory=list,
        description="2D matrix of row cells",
        examples=[[["Q1", "$120", "+15%"], ["Q2", "$145", "+24%"]]],
    )
    markdown: str = Field(
        ...,
        description="Pre-rendered GitHub Flavored Markdown table string optimized for LLM reading",
        examples=["| Quarter | Revenue (M$) | YoY Growth |\n|---|---|---|\n| Q1 | $120 | +15% |\n| Q2 | $145 | +24% |"],
    )


class ListElement(BaseElement):
    """
    Represents a bulleted or numbered list item collection.
    """
    type: Literal[ElementType.LIST_ITEM] = Field(
        default=ElementType.LIST_ITEM,
        description="Element discriminator: list_item",
    )
    items: list[str] = Field(
        ...,
        min_length=1,
        description="List entry text items",
        examples=[["First key milestone", "Second key milestone"]],
    )
    is_ordered: bool = Field(
        default=False,
        description="True if numbered sequence, False if unordered bullet list",
        examples=[False],
    )
    depth: int = Field(
        default=0,
        ge=0,
        description="Indentation or bullet nesting depth level (0-indexed)",
        examples=[0],
    )


class GenericElement(BaseElement):
    """
    Defensive fallback element for unrecognized or unclassified components
    (e.g., vector shapes, complex math formulas, signature blocks, custom tags).
    Prevents parser crashes while preserving raw text and diagnostic metadata.
    """
    type: Literal[ElementType.UNKNOWN] = Field(
        default=ElementType.UNKNOWN,
        description="Element discriminator: unknown or unclassified",
    )
    raw_content: str = Field(
        default="",
        description="Raw text or string representation of the unclassified content",
        examples=["[Complex Vector Shape: Signature Block]"],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic metadata (e.g. original XML tag, bounding box, parser warnings)",
        examples=[{"source_tag": "w:drawing", "note": "Unclassified vector shape"}],
    )


# Discriminated Union: Pydantic v2 automatically resolves concrete types via the 'type' field
DocumentElement = Annotated[
    Union[HeadingElement, ParagraphElement, TableElement, ListElement, GenericElement],
    Field(discriminator="type"),
]


class ParsedDocument(BaseModel):
    """
    Canonical Abstract Syntax Tree (AST) representing a fully parsed document.
    Unified output contract produced by all parser strategies (PDF, DOCX).
    """
    document_id: UUID = Field(
        ...,
        description="Unique identifier of the parent document",
    )
    filename: str = Field(
        ...,
        description="Original filename of the document",
        examples=["financial_report.pdf"],
    )
    elements: list[DocumentElement] = Field(
        default_factory=list,
        description="Sequential list of parsed AST elements in natural reading order",
    )
    total_pages: int | None = Field(
        default=None,
        ge=1,
        description="Total page count (for PDFs, None for DOCX)",
        examples=[12],
    )
    word_count: int = Field(
        default=0,
        ge=0,
        description="Total words extracted across all text elements",
        examples=[3450],
    )
    char_count: int = Field(
        default=0,
        ge=0,
        description="Total characters extracted across all text elements",
        examples=[22100],
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal extraction warnings recorded during fault-tolerant parsing",
        examples=[["Page 6: Corrupted stream replaced with generic element placeholder"]],
    )
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when parsing completed",
    )

    model_config = ConfigDict(frozen=True)
