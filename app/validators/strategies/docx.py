import io
import logging
import zipfile
from app.core.exceptions import CorruptedDocumentError
from app.validators.base import DocumentStructureValidator

logger = logging.getLogger("app.validators.docx")


class DocxStructureValidator(DocumentStructureValidator):
    """
    Validates structural integrity of Microsoft Word (.docx) documents.
    DOCX is an Open Packaging Convention (OPC) ZIP archive.
    Must contain valid ZIP tables, '[Content_Types].xml', and 'word/document.xml'.
    """

    REQUIRED_PARTS = {"[Content_Types].xml", "word/document.xml"}

    def validate_structure(self, file_bytes: bytes) -> None:
        logger.debug(f"Verifying DOCX structural integrity (size={len(file_bytes)} bytes)")

        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as archive:
                # Test archive integrity (CRC32 checksums of all entries)
                corrupted_file = archive.testzip()
                if corrupted_file is not None:
                    logger.warning(f"DOCX rejected: corrupted archive entry '{corrupted_file}' found.")
                    raise CorruptedDocumentError(
                        message=f"Corrupted file entry '{corrupted_file}' found in DOCX archive."
                    )

                namelist = set(archive.namelist())
                missing_parts = self.REQUIRED_PARTS - namelist

                if missing_parts:
                    logger.warning(f"DOCX rejected: missing required parts {missing_parts}")
                    raise CorruptedDocumentError(
                        message="File is a ZIP archive but lacks required DOCX document parts.",
                        details={"missing_parts": list(missing_parts)}
                    )

            logger.debug("DOCX structural validation successful (ZIP CRC32 and OPC XML parts confirmed)")

        except zipfile.BadZipFile as exc:
            logger.warning(f"DOCX rejected: invalid ZIP archive header: {exc}")
            raise CorruptedDocumentError(
                message="File is not a valid DOCX/ZIP archive or is corrupted.",
                details={"error": str(exc)}
            ) from exc
