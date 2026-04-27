"""PoC PDF Reader for the LCORE-1471 spike.

Mirrors the production HTMLReader in `lightspeed_rag_content/html/html_reader.py`
but configures docling for PDF input. This is throwaway PoC code -- it will be
adapted into the real `lightspeed_rag_content/pdf/` package by the implementation
ticket; do not import it from anywhere else.

Run:
    uv run python pdf_reader.py <input.pdf> [<output.md>]
"""

import logging
import sys
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

LOG = logging.getLogger(__name__)


def make_converter() -> DocumentConverter:
    """Construct a docling DocumentConverter configured for PDF.

    Defaults chosen for the BYOK use case:
        do_ocr=False               -- text-extractable PDFs only (LCORE-1471 scope)
        do_table_structure=True    -- tables are common in customer docs; cheap quality win
        table_structure_options.mode='accurate' -- accuracy over speed
        do_picture_*=False         -- vector search does not need images
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = "accurate"

    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )


def convert(pdf_path: Path) -> tuple[str, float]:
    """Convert a PDF file to Markdown. Returns (markdown, seconds)."""
    converter = make_converter()
    t0 = time.monotonic()
    result = converter.convert(str(pdf_path))
    markdown = result.document.export_to_markdown()
    elapsed = time.monotonic() - t0
    return markdown, elapsed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <input.pdf> [<output.md>]", file=sys.stderr)
        sys.exit(2)

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else in_path.with_suffix(".md")

    markdown, elapsed = convert(in_path)
    out_path.write_text(markdown, encoding="utf-8")

    chars = len(markdown)
    lines = markdown.count("\n") + 1
    print(f"converted {in_path} -> {out_path}")
    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  output:  {chars} chars, {lines} lines")
