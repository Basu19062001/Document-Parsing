from fastapi import APIRouter, Depends, File, UploadFile, status

from app.schemas import DocumentResponse
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
        "and deep document structure validation), and permanently stores the original file."
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
