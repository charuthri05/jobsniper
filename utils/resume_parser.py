"""
Resume PDF parser utility.

Extracts plain text from a PDF resume file using pypdf.
"""

from pathlib import Path

from pypdf import PdfReader


def parse_resume_pdf(pdf_path: str) -> str:
    """Extract plain text from a PDF resume file. Returns the full text.

    Args:
        pdf_path: Path to the PDF file on disk.

    Returns:
        The concatenated plain text extracted from all pages.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the file is not a valid PDF or contains no extractable text.
    """
    path = Path(pdf_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    if not path.suffix.lower() == ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {path.suffix}")

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ValueError(f"Could not read PDF file '{path}': {exc}") from exc

    if len(reader.pages) == 0:
        raise ValueError(f"PDF file has no pages: {path}")

    pages_text = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        except Exception as exc:
            # Log warning but continue with remaining pages
            print(f"  [warning] Could not extract text from page {page_num}: {exc}")

    full_text = "\n".join(pages_text).strip()

    if not full_text:
        raise ValueError(
            f"No extractable text found in '{path}'. "
            "The PDF may contain only images or scanned content."
        )

    return full_text
