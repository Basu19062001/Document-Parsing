import logging
from typing import ClassVar

from app.core.exceptions import UnsupportedParserError
from app.parsers.base import BaseParser
from app.parsers.strategies.docx import DocxParser
from app.parsers.strategies.pdf import PDFParser

logger = logging.getLogger(__name__)


class ParserFactory:
    """
    Centralized Factory and Strategy Registry for document parsers.

    Architectural Responsibilities:
    1. Factory Pattern & Strategy Resolution: Dynamically maps incoming documents
       to the appropriate BaseParser strategy via two-tier fallback (MIME type -> extension).
    2. Singleton Strategy Re-use: Maintains singleton parser instances across the application
       lifecycle to eliminate object allocation churn and garbage collection pressure (O(1) space).
    3. O(1) Instantaneous Dispatch: Performs constant-time dictionary lookups.
    4. Open-Closed Extensibility (OCP): Provides a clean registration API so future
       parsers (e.g. TXT, Markdown, HTML, OCR) can be plugged in without modifying consumer code.
    5. Clean Exception Translation: Converts unsupported format requests into domain-level
       UnsupportedParserError (HTTP 415) with structured diagnostic details.
    """

    _mime_registry: ClassVar[dict[str, BaseParser]] = {}
    _extension_registry: ClassVar[dict[str, BaseParser]] = {}
    _initialized: ClassVar[bool] = False

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Lazily initializes the default built-in parser strategies."""
        if not cls._initialized:
            cls.register_parser(DocxParser())
            cls.register_parser(PDFParser())
            cls._initialized = True
            logger.debug(
                f"ParserFactory initialized with {len(cls._extension_registry)} extensions "
                f"and {len(cls._mime_registry)} MIME types."
            )

    @classmethod
    def register_parser(cls, parser: BaseParser, override: bool = False) -> None:
        """
        Registers a parser strategy singleton across all its declared MIME types and extensions.

        Args:
            parser: Concrete instance of BaseParser.
            override: If True, allows overwriting existing mappings.
        """
        for mime in parser.SUPPORTED_MIME_TYPES:
            norm_mime = mime.strip().lower()
            if norm_mime in cls._mime_registry and not override:
                logger.warning(f"MIME type '{norm_mime}' is already registered. Skipping override.")
            else:
                cls._mime_registry[norm_mime] = parser
                logger.debug(f"Registered MIME '{norm_mime}' -> {parser.__class__.__name__}")

        for ext in parser.SUPPORTED_EXTENSIONS:
            norm_ext = ext.strip().lower()
            if not norm_ext.startswith("."):
                norm_ext = f".{norm_ext}"

            if norm_ext in cls._extension_registry and not override:
                logger.warning(f"Extension '{norm_ext}' is already registered. Skipping override.")
            else:
                cls._extension_registry[norm_ext] = parser
                logger.debug(f"Registered Extension '{norm_ext}' -> {parser.__class__.__name__}")

    @classmethod
    def get_parser(
        cls,
        mime_type: str | None = None,
        extension: str | None = None,
    ) -> BaseParser:
        """
        Resolves the appropriate BaseParser strategy via a two-tier fallback algorithm.

        Algorithm:
        1. Normalize inputs (lowercase, strip, ensure leading dot on extension).
        2. Tier 1: Look up normalized MIME type (ignoring generic octet-stream).
        3. Tier 2: If MIME type lookup misses or is generic, fall back to file extension lookup.
        4. If both lookups fail, raise UnsupportedParserError (HTTP 415).

        Args:
            mime_type: MIME type string (e.g. 'application/pdf').
            extension: File extension string (e.g. '.pdf' or 'pdf').

        Returns:
            Resolved singleton BaseParser instance.

        Raises:
            UnsupportedParserError: If no registered parser strategy matches.
        """
        cls._ensure_initialized()

        norm_mime = mime_type.strip().lower() if mime_type else ""
        norm_ext = extension.strip().lower() if extension else ""
        if norm_ext and not norm_ext.startswith("."):
            norm_ext = f".{norm_ext}"

        # Tier 1: Specific MIME type lookup (skip generic octet-stream)
        generic_mimes = {"application/octet-stream", "binary/octet-stream"}
        if norm_mime and norm_mime not in generic_mimes:
            if norm_mime in cls._mime_registry:
                return cls._mime_registry[norm_mime]

        # Tier 2: File extension fallback lookup
        if norm_ext and norm_ext in cls._extension_registry:
            return cls._extension_registry[norm_ext]

        # Tier 3: Edge-case MIME lookup (if octet-stream was the only hint and registered)
        if norm_mime and norm_mime in cls._mime_registry:
            return cls._mime_registry[norm_mime]

        logger.warning(
            f"Parser resolution failed for MIME='{mime_type}', Extension='{extension}'"
        )
        raise UnsupportedParserError(
            message=f"No parser strategy is available for document format (MIME: '{mime_type}', Extension: '{extension}').",
            details={
                "requested_mime_type": mime_type,
                "requested_extension": extension,
                "supported_extensions": cls.get_supported_extensions(),
                "supported_mime_types": cls.get_supported_mime_types(),
            },
        )

    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """Returns a sorted list of unique supported file extensions."""
        cls._ensure_initialized()
        return sorted(list(cls._extension_registry.keys()))

    @classmethod
    def get_supported_mime_types(cls) -> list[str]:
        """Returns a sorted list of unique supported MIME types."""
        cls._ensure_initialized()
        return sorted(list(cls._mime_registry.keys()))

    @classmethod
    def reset_registry(cls) -> None:
        """Clears all registered parsers and resets initialization state (primarily for unit testing)."""
        cls._mime_registry.clear()
        cls._extension_registry.clear()
        cls._initialized = False
