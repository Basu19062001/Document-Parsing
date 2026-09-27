from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from app.schemas.parsing import ParsedDocument


class BaseParser(ABC):
    """
    Abstract Strategy Interface for document parsers (Strategy Pattern).

    Every concrete parser (e.g. PDFParser, DocxParser) must implement this contract,
    converting raw physical documents into the canonical ParsedDocument AST.
    """

    SUPPORTED_MIME_TYPES: list[str] = []
    SUPPORTED_EXTENSIONS: list[str] = []

    @abstractmethod
    async def parse(
        self,
        file_path: Path,
        document_id: UUID,
        filename: str,
        strict_mode: bool | None = None,
    ) -> ParsedDocument:
        """
        Parses a document file from storage and returns the normalized ParsedDocument AST.

        Args:
            file_path: Path to the validated physical file on local storage.
            document_id: Unique UUID assigned to the document entity.
            filename: Original human-readable filename.
            strict_mode: Optional boolean override for parsing behavior.
                - False (default): Fault-tolerant extraction (skips / placeholders corrupted pages).
                - True: Strict compliance mode (aborts with CorruptedParsingError on failure).

        Returns:
            ParsedDocument containing the ordered list of DocumentElements,
            breadcrumb hierarchies, and extracted statistics.

        Raises:
            EncryptedDocumentError: If the document is password-protected or locked.
            EmptyDocumentError: If the document contains zero extractable text/tables (scanned image).
            CorruptedParsingError: If internal streams/XML are corrupt and strict mode is active.
            ParsingError: For general unrecoverable extraction failures.
        """
        pass
