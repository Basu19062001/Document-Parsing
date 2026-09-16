from app.core.exceptions import UnsupportedExtensionError
from app.validators.base import DocumentStructureValidator
from app.validators.strategies.docx import DocxStructureValidator
from app.validators.strategies.pdf import PDFStructureValidator

_STRATEGIES: dict[str, DocumentStructureValidator] = {
    "pdf": PDFStructureValidator(),
    "docx": DocxStructureValidator(),
}


def get_structure_validator(extension: str) -> DocumentStructureValidator:
    """
    Factory / Registry function to retrieve the appropriate 
    structural validation strategy based on the file extension.
    """
    normalized_ext = extension.lower().strip().lstrip(".")
    validator = _STRATEGIES.get(normalized_ext)
    if not validator:
        raise UnsupportedExtensionError(
            message=f"No structural validator registered for extension '{extension}'.",
            details={"extension": extension}
        )
    return validator


__all__ = [
    "DocumentStructureValidator",
    "PDFStructureValidator",
    "DocxStructureValidator",
    "get_structure_validator",
]
