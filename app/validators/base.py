from abc import ABC, abstractmethod


class DocumentStructureValidator(ABC):
    """
    Abstract Strategy for format-specific structural validation.
    Enforces that the document is well-formed, complete, and uncorrupted.
    """

    @abstractmethod
    def validate_structure(self, file_bytes: bytes) -> None:
        """
        Validates the deep structural integrity of the file bytes.
        
        Args:
            file_bytes: Raw binary content of the file.

        Raises:
            CorruptedDocumentError: If the document structure is broken or incomplete.
        """
        pass
