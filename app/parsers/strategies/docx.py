import asyncio
import logging
import re
from pathlib import Path
from uuid import UUID
from typing import Any

import docx
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.config import settings
from app.core.exceptions import (
    CorruptedParsingError,
    EmptyDocumentError,
    ParsingError,
)
from app.parsers.base import BaseParser
from app.schemas.parsing import (
    DocumentElement,
    ElementType,
    GenericElement,
    HeadingElement,
    ListElement,
    ParagraphElement,
    ParsedDocument,
    TableElement,
)

logger = logging.getLogger(__name__)


class DocxParser(BaseParser):
    """
    Concrete Parser Strategy for Microsoft Word (.docx) documents.

    Key Features:
    1. Interleaved XML Reading Order: Navigates doc.element.body to preserve
       the exact sequence of paragraphs, tables, and lists.
    2. Style-Based Heading Detection: Maps Word styles ('Heading 1', 'Title')
       directly to hierarchical HeadingElements with level depths.
    3. Dynamic Section Breadcrumbs: Maintains an ancestral heading stack so
       every paragraph and table carries its parent section path for RAG context.
    4. Dual Table Representation: Extracts 2D cell matrices and renders clean
       GitHub Flavored Markdown for direct LLM ingestion.
    5. Non-Blocking Async Execution: Uses asyncio.to_thread to keep the FastAPI
       event loop unblocked during CPU-bound OpenXML extraction.
    6. Exception Translation: Converts low-level zipfile and lxml errors into
       clean domain exceptions (CorruptedParsingError, EmptyDocumentError).
    """

    async def parse(
        self,
        file_path: Path,
        document_id: UUID,
        filename: str,
        strict_mode: bool | None = None,
    ) -> ParsedDocument:
        """
        Asynchronously parses a .docx file by offloading extraction to a worker thread.
        """
        is_strict = settings.PARSER_STRICT_MODE if strict_mode is None else strict_mode
        logger.info(
            f"Initiating DOCX parsing for doc_id={document_id} ('{filename}') | "
            f"Mode: {'STRICT' if is_strict else 'FAULT-TOLERANT'}"
        )

        try:
            return await asyncio.to_thread(
                self._extract_docx_sync,
                file_path=file_path,
                document_id=document_id,
                filename=filename,
                strict_mode=is_strict,
            )
        except (CorruptedParsingError, EmptyDocumentError):
            raise
        except Exception as exc:
            logger.error(
                f"Unexpected error while parsing DOCX doc_id={document_id} ('{filename}'): {exc}",
                exc_info=True,
            )
            raise ParsingError(
                message="An unexpected error occurred while parsing the Word document.",
                details={"document_id": str(document_id), "filename": filename},
            ) from exc

    def _extract_docx_sync(
        self,
        file_path: Path,
        document_id: UUID,
        filename: str,
        strict_mode: bool,
    ) -> ParsedDocument:
        """
        Synchronous core extraction logic executed inside a worker thread.
        """
        try:
            doc: DocxDocument = docx.Document(str(file_path))
        except Exception as exc:
            logger.error(
                f"Failed to open DOCX package for doc_id={document_id} at '{file_path}': {exc}",
                exc_info=True,
            )
            raise CorruptedParsingError(
                message="The Word document (.docx) is corrupted or contains invalid XML packaging.",
                details={"document_id": str(document_id), "filename": filename},
            ) from exc

        elements: list[DocumentElement] = []
        warnings: list[str] = []
        heading_stack: list[tuple[int, str]] = []  # Tracks (level, heading_text) for breadcrumbs
        reading_order = 0
        total_words = 0
        total_chars = 0

        # Iterate over XML body elements in true chronological reading order
        for child in doc.element.body:
            try:
                # =============================================================
                # 1. PARAGRAPH OR HEADING OR LIST ITEM
                # =============================================================
                if isinstance(child, CT_P):
                    paragraph = Paragraph(child, doc)
                    text = paragraph.text.strip()
                    if not text:
                        continue  # Skip empty spacing paragraphs

                    style_name = paragraph.style.name if paragraph.style else "Normal"

                    # Check for Heading or Title
                    heading_level = self._resolve_heading_level(style_name)
                    if heading_level is not None:
                        # Pop headings of same or deeper level first to find true parent
                        while heading_stack and heading_stack[-1][0] >= heading_level:
                            heading_stack.pop()

                        parent_breadcrumbs = [item[1] for item in heading_stack]
                        heading_stack.append((heading_level, text))

                        element = HeadingElement(
                            element_id=f"elem_{reading_order:04d}",
                            reading_order=reading_order,
                            page_number=None,
                            section_path=parent_breadcrumbs,
                            text=text,
                            level=heading_level,
                            type=ElementType.TITLE if heading_level == 1 and style_name.lower() == "title" else ElementType.HEADING,
                        )
                    else:
                        current_breadcrumbs = [item[1] for item in heading_stack]
                        if self._is_list_item(paragraph, style_name):
                            # List Item
                            is_ordered = bool(re.match(r"^(\d+[\.\)]|\([a-zA-Z0-9]+\))\s+", text))
                            element = ListElement(
                                element_id=f"elem_{reading_order:04d}",
                                reading_order=reading_order,
                                page_number=None,
                                section_path=current_breadcrumbs,
                                items=[text],
                                is_ordered=is_ordered,
                                depth=self._calculate_list_depth(paragraph),
                            )
                        else:
                            # Standard Body Paragraph
                            element = ParagraphElement(
                                element_id=f"elem_{reading_order:04d}",
                                reading_order=reading_order,
                                page_number=None,
                                section_path=current_breadcrumbs,
                                text=text,
                            )

                    elements.append(element)
                    reading_order += 1
                    total_words += len(text.split())
                    total_chars += len(text)

                # =============================================================
                # 2. TABLE
                # =============================================================
                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    current_breadcrumbs = [item[1] for item in heading_stack]
                    table_element = self._extract_table(
                        table=table,
                        reading_order=reading_order,
                        section_path=current_breadcrumbs,
                    )
                    if table_element is not None:
                        elements.append(table_element)
                        reading_order += 1
                        # Count words in table cells
                        for row in table_element.rows:
                            for cell in row:
                                total_words += len(cell.split())
                                total_chars += len(cell)

                # =============================================================
                # 3. OTHER / UNKNOWN XML BLOCKS (Drawings, Shapes, Custom XML)
                # =============================================================
                else:
                    tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    # Ignore standard Word wrappers that contain no printable content
                    if tag_name in {"sectPr"}:
                        continue

                    if strict_mode:
                        logger.error(f"Unrecognized XML tag in strict mode: '{tag_name}'")
                        raise CorruptedParsingError(
                            message=f"Document contains unsupported XML element '{tag_name}' in strict mode.",
                            details={"tag": tag_name},
                        )

                    # Defensive Fault-Tolerance: Record as GenericElement
                    logger.debug(f"Handling unclassified XML element '{tag_name}' as GenericElement")
                    current_breadcrumbs = [item[1] for item in heading_stack]
                    elements.append(
                        GenericElement(
                            element_id=f"elem_{reading_order:04d}",
                            reading_order=reading_order,
                            page_number=None,
                            section_path=current_breadcrumbs,
                            raw_content=f"[{tag_name}]",
                            metadata={"xml_tag": tag_name},
                        )
                    )
                    reading_order += 1
                    warnings.append(f"Unclassified element '{tag_name}' preserved as generic fallback.")

            except CorruptedParsingError:
                raise
            except Exception as element_err:
                if strict_mode:
                    logger.error(f"Failed to parse element in strict mode: {element_err}", exc_info=True)
                    raise CorruptedParsingError(
                        message=f"Failed to parse document element: {element_err}",
                        details={"element_index": reading_order},
                    ) from element_err

                # Fault-tolerant degradation
                logger.warning(
                    f"Recovered from corrupted element at reading_order={reading_order}: {element_err}"
                )
                warnings.append(f"Element at index {reading_order} was corrupted and skipped.")

        # =====================================================================
        # 4. VALIDATE EXTRACTED OUTPUT
        # =====================================================================
        if not elements or total_words == 0:
            logger.warning(f"DOCX document '{filename}' (doc_id={document_id}) yielded zero readable content.")
            raise EmptyDocumentError(
                message="The Word document (.docx) contains no readable text or tables.",
                details={"document_id": str(document_id), "filename": filename},
            )

        logger.info(
            f"DOCX parsing completed for '{filename}': {len(elements)} elements, "
            f"{total_words} words, {len(warnings)} warnings"
        )

        return ParsedDocument(
            document_id=document_id,
            filename=filename,
            elements=elements,
            total_pages=None,  # DOCX files do not have fixed pages without layout rasterization
            word_count=total_words,
            char_count=total_chars,
            warnings=warnings,
        )

    def _resolve_heading_level(self, style_name: str) -> int | None:
        """
        Determines the heading level depth from the Word paragraph style name.
        Returns 1 for Title / Heading 1, 2 for Heading 2, etc., or None if not a heading.
        """
        name_lower = style_name.lower().strip()

        if name_lower in {"title", "document title"}:
            return 1

        match = re.match(r"^heading\s*(\d+)$", name_lower)
        if match:
            level = int(match.group(1))
            return min(max(level, 1), 6)  # Clamp between H1 and H6

        return None

    def _is_list_item(self, paragraph: Paragraph, style_name: str) -> bool:
        """Checks if a paragraph represents a bulleted or numbered list."""
        name_lower = style_name.lower()
        if "list" in name_lower or "bullet" in name_lower:
            return True

        # Check raw XML for numbering properties (<w:numPr>)
        pPr = paragraph._p.get_or_add_pPr()
        return pPr.find(docx.oxml.ns.qn("w:numPr")) is not None

    def _calculate_list_depth(self, paragraph: Paragraph) -> int:
        """Determines the indentation nesting level for a list item."""
        try:
            pPr = paragraph._p.get_or_add_pPr()
            numPr = pPr.find(docx.oxml.ns.qn("w:numPr"))
            if numPr is not None:
                ilvl = numPr.find(docx.oxml.ns.qn("w:ilvl"))
                if ilvl is not None:
                    return int(ilvl.get(docx.oxml.ns.qn("w:val"), 0))
        except Exception:
            pass
        return 0

    def _extract_table(
        self,
        table: Table,
        reading_order: int,
        section_path: list[str],
    ) -> TableElement | None:
        """
        Extracts 2D cell text matrix and builds GitHub Flavored Markdown for a table.
        """
        raw_rows: list[list[str]] = []
        for row in table.rows:
            row_cells = [cell.text.strip().replace("\n", " ").replace("|", "\\|") for cell in row.cells]
            # Ignore completely blank rows
            if any(cell for cell in row_cells):
                raw_rows.append(row_cells)

        if not raw_rows:
            return None

        # First row is treated as header if there are 2 or more rows
        if len(raw_rows) >= 2:
            headers = raw_rows[0]
            data_rows = raw_rows[1:]
        else:
            # Single-row table: generate generic column headers
            headers = [f"Column {i + 1}" for i in range(len(raw_rows[0]))]
            data_rows = raw_rows

        markdown = self._render_markdown_table(headers, data_rows)

        return TableElement(
            element_id=f"elem_{reading_order:04d}",
            reading_order=reading_order,
            page_number=None,
            section_path=section_path,
            headers=headers,
            rows=data_rows,
            markdown=markdown,
        )

    def _render_markdown_table(self, headers: list[str], rows: list[list[str]]) -> str:
        """
        Constructs a GitHub Flavored Markdown table string.
        """
        col_count = len(headers)
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join(["---"] * col_count) + " |"

        row_lines: list[str] = []
        for row in rows:
            # Normalize row length to match column count
            padded_row = row + [""] * (col_count - len(row))
            truncated_row = padded_row[:col_count]
            row_lines.append("| " + " | ".join(truncated_row) + " |")

        return "\n".join([header_line, separator_line] + row_lines)
