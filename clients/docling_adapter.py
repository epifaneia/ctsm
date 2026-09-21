"""Wrapper de Docling para conversión PDF/DOCX → Markdown.

Configuración conservadora de memoria (batch_size=1 por tipo) para evitar
OOM en documentos grandes con tablas y OCR.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def markdown_from_pdf(path: Path, *, pdf_ocr: bool = False) -> str:
    """Convierte un PDF (o chunk de PDF) a Markdown via Docling."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        TableFormerMode,
        TableStructureOptions,
        ThreadedPdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_opts = ThreadedPdfPipelineOptions(
        ocr_batch_size=1,
        layout_batch_size=1,
        table_batch_size=1,
        queue_max_size=8,
        images_scale=0.5,
        generate_page_images=False,
        generate_picture_images=False,
        do_ocr=pdf_ocr,
        force_backend_text=(not pdf_ocr),
        table_structure_options=TableStructureOptions(mode=TableFormerMode.FAST),
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
    )
    _log.info("Docling (PDF): %s", path.name)
    result = converter.convert(str(path))
    return result.document.export_to_markdown()


def markdown_from_docx(path: Path) -> str:
    """Convierte un DOCX a Markdown via Docling."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    _log.info("Docling (DOCX): %s", path.name)
    result = converter.convert(str(path))
    return result.document.export_to_markdown()


def markdown_from_pptx(path: Path) -> str:
    """Convierte un PPTX/PPT a Markdown via Docling."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    _log.info("Docling (PPTX): %s", path.name)
    result = converter.convert(str(path))
    return result.document.export_to_markdown()
