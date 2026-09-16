import io
import zipfile
from app.core.exceptions import CorruptedDocumentError
from app.validators.base import DocumentStructureValidator


class DocxStructureValidator(DocumentStructureValidator):
    """
    Validates structural integrity of Microsoft Word (.docx) documents.
    DOCX is an Open Packaging Convention (OPC) ZIP archive.
    Must contain valid ZIP tables, '[Content_Types].xml', and 'word/document.xml'.
    """

    REQUIRED_PARTS = {"[Content_Types].xml", "word/document.xml"}

    def validate_structure(self, file_bytes: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as archive:
                # Test archive integrity (CRC32 checksums of all entries)
                corrupted_file = archive.testzip()
                if corrupted_file is not None:
                    raise CorruptedDocumentError(
                        message=f"Corrupted file entry '{corrupted_file}' found in DOCX archive."
                    )

                namelist = set(archive.namelist())
                missing_parts = self.REQUIRED_PARTS - namelist

                if missing_parts:
                    raise CorruptedDocumentError(
                        message="File is a ZIP archive but lacks required DOCX document parts.",
                        details={"missing_parts": list(missing_parts)}
                    )

        except zipfile.BadZipFile as exc:
            raise CorruptedDocumentError(
                message="File is not a valid DOCX/ZIP archive or is corrupted.",
                details={"error": str(exc)}
            ) from exc
