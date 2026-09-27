from uuid import UUID
from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.schemas import DocumentResponse
from app.schemas.parsing import ParsedDocument
from app.services import DocumentService, get_document_service

router = APIRouter()


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and validate a document",
    description=(
        "Uploads a PDF or DOCX document, executes the 6-stage validation pipeline "
        "(empty check, size <= 20MB, extension whitelist, MIME type check, magic bytes, "
        "and deep document structure validation), stores the physical file, "
        "and registers the initial document metadata record in PostgreSQL."
    ),
)
async def upload_document(
    file: UploadFile = File(
        ...,
        description="The document file to upload (.pdf or .docx, max 20MB)",
    ),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    """
    Thin HTTP Controller:
    Delegates all validation, ID generation, and persistence to DocumentService.
    """
    return await service.upload_document(file)


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get document metadata and status",
    description="Retrieves the ingestion state, file metadata, and lifecycle status for a document.",
)
async def get_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    """
    Retrieves document metadata by its UUID.
    """
    return await service.get_document(document_id)


@router.post(
    "/{document_id}/parse",
    response_model=ParsedDocument,
    status_code=status.HTTP_200_OK,
    summary="Parse document content into canonical AST",
    description=(
        "Executes format-specific parsing strategy (DocxParser or PDFParser), resolves "
        "hierarchical breadcrumbs, extracts 2D tables as Markdown, and stores the "
        "canonical AST into PostgreSQL JSONB. Idempotent by default: returns cached AST "
        "if already parsed, unless 'force=true' is specified."
    ),
)
async def parse_document(
    document_id: UUID,
    force: bool = Query(
        default=False,
        description="Force re-parsing even if document was previously parsed successfully",
    ),
    service: DocumentService = Depends(get_document_service),
) -> ParsedDocument:
    """
    Triggers parsing workflow, state machine transition (PROCESSING -> PARSED/FAILED),
    and PostgreSQL JSONB persistence.
    """
    return await service.parse_document(
        document_id=document_id,
        force=force,
    )


@router.get(
    "/{document_id}/parsed",
    response_model=ParsedDocument,
    status_code=status.HTTP_200_OK,
    summary="Retrieve canonical AST of a parsed document",
    description=(
        "Retrieves the pre-parsed canonical AST and extraction metrics directly from "
        "PostgreSQL JSONB in O(1) time without re-running CPU parsing."
    ),
)
async def get_parsed_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> ParsedDocument:
    """
    Fetches the persisted canonical AST from PostgreSQL JSONB.
    """
    return await service.get_parsed_document(document_id)
