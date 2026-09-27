import asyncio
from collections import Counter
import logging
from pathlib import Path
import re
import statistics
from typing import Any
from uuid import UUID

import pdfminer.pdfdocument
import pdfminer.pdfparser
import pdfplumber

from app.core.config import settings
from app.core.exceptions import (
    CorruptedParsingError,
    EmptyDocumentError,
    EncryptedDocumentError,
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


class PDFParser(BaseParser):
    """
    Concrete Parser Strategy for Portable Document Format (.pdf) documents.

    Key Architectural Features:
    1. Table-First Extraction & Masking: Detects table bounding boxes first using
       line/curve analysis and masks them out before text extraction, preventing
       duplicate words and jumbled table cell text in paragraph streams.
    2. Header & Footer Marginal Noise Rejection: Strips repeated marginal noise
       in the top 5% and bottom 5% of each page canvas.
    3. Font-Size Mode Profiling: Uses document-wide statistical mode of word font sizes
       as baseline body text, classifying elevated font sizes into hierarchical
       Heading elements (H1 >= 1.7x, H2 >= 1.35x, H3 >= 1.15x).
    4. True Chronological Vertical Ordering: Interleaves extracted text blocks
       and tables based on their top-down vertical canvas coordinates (y-axis).
    5. Dynamic Section Breadcrumbs: Maintains an ancestral heading stack across pages
       so every paragraph, table, and list item carries its parent section path.
    6. Fault-Tolerant Page Isolation: Corrupted or unparseable individual pages are
       isolated; when strict mode is disabled, corrupted pages degrade into
       GenericElement placeholders with diagnostic warnings rather than aborting
       the entire document.
    7. Dual Table Representation: Extracts 2D matrix grids and produces GitHub
       Flavored Markdown for direct LLM ingestion.
    8. Non-Blocking Async Execution: Wraps synchronous extraction in asyncio.to_thread
       to keep the FastAPI event loop responsive.
    """

    async def parse(
        self,
        file_path: Path,
        document_id: UUID,
        filename: str,
        strict_mode: bool | None = None,
    ) -> ParsedDocument:
        """
        Asynchronously parses a .pdf file by offloading extraction to a worker thread.
        """
        is_strict = settings.PARSER_STRICT_MODE if strict_mode is None else strict_mode
        logger.info(
            f"Initiating PDF parsing for doc_id={document_id} ('{filename}') | "
            f"Mode: {'STRICT' if is_strict else 'FAULT-TOLERANT'}"
        )

        try:
            return await asyncio.to_thread(
                self._extract_pdf_sync,
                file_path=file_path,
                document_id=document_id,
                filename=filename,
                strict_mode=is_strict,
            )
        except (EncryptedDocumentError, EmptyDocumentError, CorruptedParsingError):
            raise
        except Exception as exc:
            logger.error(
                f"Unexpected error while parsing PDF doc_id={document_id} ('{filename}'): {exc}",
                exc_info=True,
            )
            raise ParsingError(
                message="An unexpected error occurred while parsing the PDF document.",
                details={"document_id": str(document_id), "filename": filename},
            ) from exc

    def _extract_pdf_sync(
        self,
        file_path: Path,
        document_id: UUID,
        filename: str,
        strict_mode: bool,
    ) -> ParsedDocument:
        """
        Synchronous core extraction logic executed inside a worker thread.
        """
        # Step 1: Open the PDF and detect encryption or structural corruption
        try:
            pdf = pdfplumber.open(str(file_path))
        except (
            pdfminer.pdfdocument.PDFPasswordIncorrect,
            pdfminer.pdfdocument.PDFEncryptionError,
        ) as enc_exc:
            logger.warning(f"PDF doc_id={document_id} is password protected: {enc_exc}")
            raise EncryptedDocumentError(
                message="The PDF document is encrypted or password-protected and cannot be parsed.",
                details={"document_id": str(document_id), "filename": filename},
            ) from enc_exc
        except (pdfminer.pdfparser.PDFSyntaxError, Exception) as exc:
            exc_str = str(exc).lower()
            if "password" in exc_str or "encrypt" in exc_str:
                logger.warning(f"PDF doc_id={document_id} password requirement detected: {exc}")
                raise EncryptedDocumentError(
                    message="The PDF document is encrypted or password-protected and cannot be parsed.",
                    details={"document_id": str(document_id), "filename": filename},
                ) from exc

            logger.error(f"Failed to open PDF doc_id={document_id} at '{file_path}': {exc}", exc_info=True)
            raise CorruptedParsingError(
                message="The PDF document is corrupted, malformed, or has an invalid cross-reference stream.",
                details={"document_id": str(document_id), "filename": filename},
            ) from exc

        try:
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise EmptyDocumentError(
                    message="The PDF document contains zero pages.",
                    details={"document_id": str(document_id), "filename": filename},
                )

            # Step 2: Calculate baseline body font size mode across the document
            body_font_mode = self._compute_document_body_font_mode(pdf)
            logger.debug(f"Computed baseline body font mode: {body_font_mode:.2f}pt for '{filename}'")

            elements: list[DocumentElement] = []
            warnings: list[str] = []
            heading_stack: list[tuple[int, str]] = []  # Tracks (level, heading_text) for breadcrumbs
            reading_order = 0
            total_words = 0
            total_chars = 0

            # Step 3: Process pages with fault-tolerant page isolation
            for page_idx, page in enumerate(pdf.pages):
                page_num = page_idx + 1

                try:
                    page_elements, p_words, p_chars = self._extract_page_elements(
                        page=page,
                        page_num=page_num,
                        body_font_mode=body_font_mode,
                        heading_stack=heading_stack,
                        start_reading_order=reading_order,
                    )

                    elements.extend(page_elements)
                    reading_order += len(page_elements)
                    total_words += p_words
                    total_chars += p_chars

                except Exception as page_exc:
                    if strict_mode:
                        logger.error(
                            f"Strict mode failure on page {page_num} of doc_id={document_id}: {page_exc}",
                            exc_info=True,
                        )
                        raise CorruptedParsingError(
                            message=f"Failed to parse page {page_num} in strict mode: {page_exc}",
                            details={"document_id": str(document_id), "page_number": page_num},
                        ) from page_exc

                    # Fault-tolerant isolation: insert placeholder and preserve existing pages
                    logger.warning(
                        f"Page {page_num} in doc_id={document_id} failed extraction ({page_exc}). "
                        f"Inserting GenericElement fallback placeholder."
                    )
                    current_breadcrumbs = [h[1] for h in heading_stack]
                    fallback_elem = GenericElement(
                        element_id=f"elem_{reading_order:04d}",
                        reading_order=reading_order,
                        page_number=page_num,
                        section_path=current_breadcrumbs,
                        raw_content=f"[Page {page_num} Unparseable Content: {str(page_exc)}]",
                        metadata={"error": str(page_exc), "page_number": page_num},
                    )
                    elements.append(fallback_elem)
                    reading_order += 1
                    warnings.append(
                        f"Page {page_num} could not be parsed due to a decompression/rendering error: {str(page_exc)}. "
                        "A fallback placeholder was inserted."
                    )

            # Step 4: Validate extracted content
            if not elements or total_words == 0:
                logger.warning(f"PDF document '{filename}' (doc_id={document_id}) yielded zero readable content.")
                raise EmptyDocumentError(
                    message="The PDF document contains no readable text or structural elements.",
                    details={"document_id": str(document_id), "filename": filename},
                )

            logger.info(
                f"PDF parsing completed for '{filename}': {len(elements)} elements, "
                f"{total_pages} pages, {total_words} words, {len(warnings)} warnings"
            )

            return ParsedDocument(
                document_id=document_id,
                filename=filename,
                elements=elements,
                total_pages=total_pages,
                word_count=total_words,
                char_count=total_chars,
                warnings=warnings,
            )

        finally:
            pdf.close()

    def _compute_document_body_font_mode(self, pdf: pdfplumber.PDF) -> float:
        """
        Samples word font sizes across pages to find the statistical mode (standard body text).
        """
        font_sizes: list[float] = []
        # Sample up to the first 10 pages for fast font profiling
        sample_pages = pdf.pages[:10]
        for page in sample_pages:
            try:
                words = page.extract_words(extra_attrs=["size"])
                for w in words:
                    size = w.get("size")
                    if size and size > 0:
                        font_sizes.append(round(float(size), 1))
            except Exception:
                continue

        if not font_sizes:
            return 10.0  # Safe default font size in points

        # Return the most frequent font size
        counter = Counter(font_sizes)
        mode_size, _ = counter.most_common(1)[0]
        return mode_size

    def _extract_page_elements(
        self,
        page: Any,
        page_num: int,
        body_font_mode: float,
        heading_stack: list[tuple[int, str]],
        start_reading_order: int,
    ) -> tuple[list[DocumentElement], int, int]:
        """
        Extracts structural elements (Headings, Paragraphs, Lists, Tables) from a single page canvas.
        Interleaves text blocks and tables in true top-down vertical reading order.
        """
        header_margin = page.height * 0.05
        footer_margin = page.height * 0.95

        # Item container: list of tuples (top_coordinate, item_type, data)
        # where item_type is "table" or "text_block"
        canvas_items: list[tuple[float, str, Any]] = []

        # =====================================================================
        # 1. TABLE DETECTION AND BBOX EXTRACTION
        # =====================================================================
        table_bboxes: list[tuple[float, float, float, float]] = []
        try:
            detected_tables = page.find_tables()
            for t in detected_tables:
                table_bboxes.append(t.bbox)  # (x0, top, x1, bottom)
                table_data = t.extract()
                if table_data:
                    canvas_items.append((t.bbox[1], "table", table_data))
        except Exception as tbl_err:
            logger.debug(f"Table detection on page {page_num} encountered notice: {tbl_err}")

        # =====================================================================
        # 2. WORD EXTRACTION WITH TABLE MASKING & MARGIN FILTERING
        # =====================================================================
        try:
            words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False)
        except Exception as words_err:
            logger.warning(f"Word extraction failed on page {page_num}: {words_err}")
            words = []

        filtered_words: list[dict[str, Any]] = []
        for w in words:
            top = float(w.get("top", 0.0))
            bottom = float(w.get("bottom", 0.0))
            x0 = float(w.get("x0", 0.0))
            x1 = float(w.get("x1", 0.0))
            mid_x = (x0 + x1) / 2.0
            mid_y = (top + bottom) / 2.0

            # Filter out top header and bottom footer marginal noise
            if top < header_margin or bottom > footer_margin:
                continue

            # Mask out words that reside inside detected table bounding boxes
            inside_table = False
            for tx0, ttop, tx1, tbottom in table_bboxes:
                if (tx0 - 1.0) <= mid_x <= (tx1 + 1.0) and (ttop - 1.0) <= mid_y <= (tbottom + 1.0):
                    inside_table = True
                    break

            if not inside_table:
                filtered_words.append(w)

        # =====================================================================
        # 3. RECONSTRUCT WORDS INTO LINES AND BLOCKS
        # =====================================================================
        text_blocks = self._cluster_words_into_blocks(filtered_words)
        for block in text_blocks:
            canvas_items.append((block["top"], "text_block", block))

        # =====================================================================
        # 4. SORT CANVAS ITEMS BY VERTICAL POSITION (TOP-TO-BOTTOM)
        # =====================================================================
        canvas_items.sort(key=lambda item: item[0])

        elements: list[DocumentElement] = []
        current_reading_order = start_reading_order
        page_words = 0
        page_chars = 0

        # =====================================================================
        # 5. TRANSFORM INTO CANONICAL AST ELEMENTS
        # =====================================================================
        for _, item_type, item_data in canvas_items:
            if item_type == "table":
                table_element = self._build_table_element(
                    raw_data=item_data,
                    reading_order=current_reading_order,
                    page_num=page_num,
                    section_path=[h[1] for h in heading_stack],
                )
                if table_element is not None:
                    elements.append(table_element)
                    current_reading_order += 1
                    for row in table_element.rows:
                        for cell in row:
                            page_words += len(cell.split())
                            page_chars += len(cell)

            elif item_type == "text_block":
                block_text: str = item_data["text"]
                block_size: float = item_data["size"]
                if not block_text.strip():
                    continue

                # Heading detection via font size ratio
                size_ratio = block_size / body_font_mode if body_font_mode > 0 else 1.0
                heading_level = self._resolve_heading_level_from_ratio(size_ratio)

                if heading_level is not None and len(block_text) < 200:
                    # Pop headings of same or deeper level from stack
                    while heading_stack and heading_stack[-1][0] >= heading_level:
                        heading_stack.pop()

                    parent_breadcrumbs = [h[1] for h in heading_stack]
                    heading_stack.append((heading_level, block_text))

                    element = HeadingElement(
                        element_id=f"elem_{current_reading_order:04d}",
                        reading_order=current_reading_order,
                        page_number=page_num,
                        section_path=parent_breadcrumbs,
                        text=block_text,
                        level=heading_level,
                        type=ElementType.TITLE if heading_level == 1 and page_num == 1 and current_reading_order <= 2 else ElementType.HEADING,
                    )
                else:
                    current_breadcrumbs = [h[1] for h in heading_stack]
                    # Check for list item pattern
                    if self._is_list_text(block_text):
                        is_ordered = bool(re.match(r"^(\d+[\.\)]|\([a-zA-Z0-9]+\))\s+", block_text))
                        element = ListElement(
                            element_id=f"elem_{current_reading_order:04d}",
                            reading_order=current_reading_order,
                            page_number=page_num,
                            section_path=current_breadcrumbs,
                            items=[block_text],
                            is_ordered=is_ordered,
                            depth=0,
                        )
                    else:
                        element = ParagraphElement(
                            element_id=f"elem_{current_reading_order:04d}",
                            reading_order=current_reading_order,
                            page_number=page_num,
                            section_path=current_breadcrumbs,
                            text=block_text,
                        )

                elements.append(element)
                current_reading_order += 1
                page_words += len(block_text.split())
                page_chars += len(block_text)

        return elements, page_words, page_chars

    def _cluster_words_into_blocks(self, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Groups raw word bounding boxes into lines, then clusters consecutive lines
        with matching font metrics and line-spacing into unified text blocks.
        """
        if not words:
            return []

        # Sort words primarily by top coordinate, secondarily by x0
        words_sorted = sorted(words, key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0))))

        # 1. Cluster words into lines
        lines: list[dict[str, Any]] = []
        current_line_words: list[dict[str, Any]] = []
        current_line_top: float | None = None
        current_line_bottom: float | None = None

        for w in words_sorted:
            w_top = float(w.get("top", 0))
            w_bottom = float(w.get("bottom", 0))
            w_size = float(w.get("size", 10))

            if current_line_top is None:
                current_line_words = [w]
                current_line_top = w_top
                current_line_bottom = w_bottom
            else:
                # If word top is close to the current line top (within half font size)
                tolerance = max(w_size * 0.45, 3.0)
                if abs(w_top - current_line_top) <= tolerance:
                    current_line_words.append(w)
                    current_line_top = min(current_line_top, w_top)
                    current_line_bottom = max(current_line_bottom or w_bottom, w_bottom)
                else:
                    # Flush completed line
                    lines.append(self._finalize_line(current_line_words, current_line_top, current_line_bottom))
                    current_line_words = [w]
                    current_line_top = w_top
                    current_line_bottom = w_bottom

        if current_line_words and current_line_top is not None and current_line_bottom is not None:
            lines.append(self._finalize_line(current_line_words, current_line_top, current_line_bottom))

        # 2. Cluster lines into coherent blocks (paragraphs / headings)
        blocks: list[dict[str, Any]] = []
        current_block: dict[str, Any] | None = None

        for line in lines:
            if current_block is None:
                current_block = {
                    "text": line["text"],
                    "top": line["top"],
                    "bottom": line["bottom"],
                    "size": line["size"],
                    "line_count": 1,
                }
            else:
                vertical_gap = line["top"] - current_block["bottom"]
                size_diff = abs(line["size"] - current_block["size"])
                # Same paragraph condition: font size matches and vertical gap is standard line spacing
                is_same_paragraph = (
                    size_diff <= 1.2
                    and -2.0 <= vertical_gap <= (current_block["size"] * 1.5)
                    and not self._is_list_text(line["text"])
                )

                if is_same_paragraph:
                    current_block["text"] += " " + line["text"]
                    current_block["bottom"] = line["bottom"]
                    current_block["line_count"] += 1
                else:
                    blocks.append(current_block)
                    current_block = {
                        "text": line["text"],
                        "top": line["top"],
                        "bottom": line["bottom"],
                        "size": line["size"],
                        "line_count": 1,
                    }

        if current_block is not None:
            blocks.append(current_block)

        return blocks

    def _finalize_line(
        self,
        words: list[dict[str, Any]],
        top: float,
        bottom: float,
    ) -> dict[str, Any]:
        """Constructs a single horizontal line record from sorted constituent words."""
        words_by_x = sorted(words, key=lambda w: float(w.get("x0", 0)))
        line_text = " ".join(w.get("text", "") for w in words_by_x).strip()
        sizes = [float(w.get("size", 10)) for w in words_by_x if w.get("size")]
        median_size = statistics.median(sizes) if sizes else 10.0

        return {
            "text": line_text,
            "top": top,
            "bottom": bottom,
            "size": median_size,
        }

    def _resolve_heading_level_from_ratio(self, ratio: float) -> int | None:
        """
        Maps the ratio of current font size to body font mode to Heading level.
        H1 >= 1.7x, H2 >= 1.35x, H3 >= 1.15x
        """
        if ratio >= 1.70:
            return 1
        elif ratio >= 1.35:
            return 2
        elif ratio >= 1.15:
            return 3
        return None

    def _is_list_text(self, text: str) -> bool:
        """Checks if text begins with a bullet point or numbered list indicator."""
        clean = text.strip()
        return bool(re.match(r"^([•\-\*–—]|\d+[\.\)]|\([a-zA-Z0-9]+\))\s+", clean))

    def _build_table_element(
        self,
        raw_data: list[list[str | None]],
        reading_order: int,
        page_num: int,
        section_path: list[str],
    ) -> TableElement | None:
        """
        Extracts 2D cell text matrix and renders clean GitHub Flavored Markdown.
        """
        cleaned_rows: list[list[str]] = []
        for row in raw_data:
            if not row:
                continue
            cleaned_cells = [
                (cell or "").strip().replace("\n", " ").replace("|", "\\|")
                for cell in row
            ]
            if any(c for c in cleaned_cells):
                cleaned_rows.append(cleaned_cells)

        if not cleaned_rows:
            return None

        if len(cleaned_rows) >= 2:
            headers = cleaned_rows[0]
            data_rows = cleaned_rows[1:]
        else:
            headers = [f"Column {i + 1}" for i in range(len(cleaned_rows[0]))]
            data_rows = cleaned_rows

        markdown = self._render_markdown_table(headers, data_rows)

        return TableElement(
            element_id=f"elem_{reading_order:04d}",
            reading_order=reading_order,
            page_number=page_num,
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
            padded_row = row + [""] * (col_count - len(row))
            truncated_row = padded_row[:col_count]
            row_lines.append("| " + " | ".join(truncated_row) + " |")

        return "\n".join([header_line, separator_line] + row_lines)
