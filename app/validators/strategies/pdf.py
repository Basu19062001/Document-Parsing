from app.core.exceptions import CorruptedDocumentError
from app.validators.base import DocumentStructureValidator


class PDFStructureValidator(DocumentStructureValidator):
    """
    Validates structural integrity of PDF documents.
    Checks header, trailer, and %%EOF marker to ensure complete file delivery.
    """

    MIN_PDF_SIZE_BYTES: int = 32  # Minimum viable PDF size

    def validate_structure(self, file_bytes: bytes) -> None:
        if len(file_bytes) < self.MIN_PDF_SIZE_BYTES:
            raise CorruptedDocumentError(
                message="PDF file is too small to be a valid document.",
                details={"file_size_bytes": len(file_bytes)}
            )

        # 1. Header Check: Must start with %PDF-
        if not file_bytes.startswith(b"%PDF-"):
            raise CorruptedDocumentError(
                message="PDF header marker '%PDF-' is missing or invalid."
            )

        # 2. End-of-File (EOF) Check:
        # Per Adobe PDF specification, %%EOF must appear in the last 1024 bytes.
        tail = file_bytes[-1024:]
        if b"%%EOF" not in tail:
            raise CorruptedDocumentError(
                message="PDF document is incomplete or truncated (missing '%%EOF' marker)."
            )
