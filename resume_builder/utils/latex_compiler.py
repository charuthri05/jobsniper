"""LaTeX compilation utilities."""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CompilationResult:
    """Result of LaTeX compilation."""

    success: bool
    pdf_path: Optional[Path] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_content: str = ""

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


def find_pdflatex() -> Optional[str]:
    """Find pdflatex binary path."""
    # First try the system PATH
    path = shutil.which("pdflatex")
    if path:
        return path

    # Check common TeX installation paths across platforms
    common_paths = [
        "/Library/TeX/texbin/pdflatex",  # macOS MacTeX/BasicTeX (symlink, always works)
        "/usr/local/texlive/2026basic/bin/universal-darwin/pdflatex",
        "/usr/local/texlive/2026/bin/universal-darwin/pdflatex",
        "/usr/local/texlive/2025basic/bin/universal-darwin/pdflatex",
        "/usr/local/texlive/2025/bin/universal-darwin/pdflatex",
        "/usr/texbin/pdflatex",
        # Windows MiKTeX
        r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
        # Linux
        "/usr/bin/pdflatex",
    ]

    for tex_path in common_paths:
        if Path(tex_path).exists():
            return tex_path

    return None


def compile_latex(
    tex_file: Path,
    output_dir: Optional[Path] = None,
    output_name: Optional[str] = None,
    compile_twice: bool = True,
    clean_aux: bool = True,
    aux_extensions: Optional[list[str]] = None,
    timeout: int = 120,
) -> CompilationResult:
    """
    Compile a LaTeX file to PDF.

    Args:
        tex_file: Path to the .tex file
        output_dir: Directory for output (defaults to tex_file's directory)
        output_name: Name for output PDF (without .pdf extension)
        compile_twice: Run pdflatex twice for references
        clean_aux: Remove auxiliary files after compilation
        aux_extensions: List of auxiliary file extensions to clean
        timeout: Timeout in seconds for each pdflatex run

    Returns:
        CompilationResult with success status and any errors
    """
    pdflatex = find_pdflatex()
    if not pdflatex:
        return CompilationResult(
            success=False,
            errors=["pdflatex not found. Install TeX distribution (e.g., MacTeX, TeX Live)"],
        )

    tex_file = Path(tex_file).resolve()
    if not tex_file.exists():
        return CompilationResult(
            success=False,
            errors=[f"TeX file not found: {tex_file}"],
        )

    output_dir = output_dir or tex_file.parent
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if aux_extensions is None:
        aux_extensions = [".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz"]

    # Build pdflatex command
    # Use -interaction=nonstopmode to continue past minor errors
    # Don't use -halt-on-error - let pdflatex try to produce output despite errors
    cmd = [
        pdflatex,
        "-interaction=nonstopmode",
        f"-output-directory={output_dir}",
        str(tex_file),
    ]

    errors = []
    warnings = []
    log_content = ""

    # Run pdflatex (twice if requested for references)
    runs = 2 if compile_twice else 1
    for run in range(1, runs + 1):
        logger.debug(f"pdflatex run {run}/{runs}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(tex_file.parent),
            )

            log_content = result.stdout + "\n" + result.stderr

            if result.returncode != 0:
                # Parse errors from output
                run_errors = parse_latex_errors(log_content)
                errors.extend(run_errors)

                if run_errors:
                    logger.error(f"pdflatex run {run} failed with errors")
                    break

        except subprocess.TimeoutExpired:
            errors.append(f"pdflatex timed out after {timeout} seconds")
            break

        except Exception as e:
            errors.append(f"pdflatex execution failed: {e}")
            break

    # Check for output PDF
    base_name = tex_file.stem
    pdf_file = output_dir / f"{base_name}.pdf"

    if not pdf_file.exists() and not errors:
        errors.append(f"PDF not generated: {pdf_file}")

    # Rename PDF if requested
    final_pdf = pdf_file
    if output_name and pdf_file.exists():
        final_pdf = output_dir / f"{output_name}.pdf"
        # Skip rename if names match (case-insensitive — macOS filesystem)
        if final_pdf.name.lower() != pdf_file.name.lower() and final_pdf != pdf_file:
            try:
                if final_pdf.exists():
                    final_pdf.unlink()
                pdf_file.rename(final_pdf)
                logger.info(f"Renamed PDF to: {final_pdf.name}")
            except OSError as e:
                logger.warning(f"Could not rename PDF: {e}")
                final_pdf = pdf_file  # fall back to original name

    # Parse warnings from log
    if log_content:
        warnings = parse_latex_warnings(log_content)

    # Clean auxiliary files
    if clean_aux and final_pdf.exists():
        cleaned = clean_auxiliary_files(output_dir, base_name, aux_extensions)
        if cleaned:
            logger.debug(f"Cleaned {len(cleaned)} auxiliary files")

    # Success is primarily determined by whether PDF was generated
    # pdflatex with -nonstopmode often produces valid PDFs despite minor errors
    success = final_pdf.exists()

    # Only treat as failure if PDF wasn't created AND there are fatal errors
    if not success and not errors:
        errors.append(f"PDF not generated: {final_pdf}")

    return CompilationResult(
        success=success,
        pdf_path=final_pdf if success else None,
        errors=errors if not success else [],  # Only report errors if PDF failed
        warnings=warnings + (errors if success else []),  # Treat as warnings if PDF succeeded
        log_content=log_content,
    )


def parse_latex_errors(log_content: str) -> list[str]:
    """Extract error messages from pdflatex output."""
    errors = []

    # Look for common error patterns
    error_patterns = [
        r"^!\s*(.+?)$",  # Lines starting with !
        r"^l\.(\d+)\s+(.+?)$",  # Line number errors
        r"Emergency stop",
        r"Fatal error",
        r"No file (.+?)\.aux",
    ]

    for pattern in error_patterns:
        matches = re.findall(pattern, log_content, re.MULTILINE)
        for match in matches:
            if isinstance(match, tuple):
                error_msg = " ".join(str(m) for m in match)
            else:
                error_msg = str(match)

            # Skip common non-critical messages
            if any(skip in error_msg.lower() for skip in ["rerun", "undefined references"]):
                continue

            if error_msg and error_msg not in errors:
                errors.append(error_msg.strip())

    return errors[:10]  # Limit to first 10 errors


def parse_latex_warnings(log_content: str) -> list[str]:
    """Extract warning messages from pdflatex output."""
    warnings = []

    warning_patterns = [
        r"LaTeX Warning:\s*(.+?)(?:\n|$)",
        r"Package .+? Warning:\s*(.+?)(?:\n|$)",
        r"Overfull \\hbox.+",
        r"Underfull \\hbox.+",
    ]

    for pattern in warning_patterns:
        matches = re.findall(pattern, log_content)
        for match in matches:
            warning = match.strip() if isinstance(match, str) else str(match)
            if warning and warning not in warnings:
                warnings.append(warning)

    return warnings[:20]  # Limit to first 20 warnings


def clean_auxiliary_files(
    directory: Path,
    base_name: str,
    extensions: list[str],
) -> list[Path]:
    """Remove auxiliary files from compilation."""
    cleaned = []

    for ext in extensions:
        aux_file = directory / f"{base_name}{ext}"
        if aux_file.exists():
            try:
                aux_file.unlink()
                cleaned.append(aux_file)
            except Exception as e:
                logger.warning(f"Could not remove {aux_file}: {e}")

    return cleaned


def _page_count_from_log(log_content: str) -> int:
    """Parse the page count from pdflatex's 'Output written on X.pdf (N pages, ...)' line."""
    match = re.search(r"Output written on \S+\s*\((\d+)\s*pages?", log_content)
    return int(match.group(1)) if match else 0


def _drop_last_project_block(tex_content: str) -> tuple[str, bool]:
    """Remove the last \\resumeProjectHeading block (heading + its bullet list).

    A project block in the template looks like:
        \\resumeProjectHeading
            {...title...}{...}
        \\resumeItemListStart
            \\resumeItem{...}
            \\resumeItem{...}
        \\resumeItemListEnd

    We find the last \\resumeProjectHeading, scan forward to the next
    \\resumeItemListEnd, and remove everything from the start of the heading's
    line through the newline after \\resumeItemListEnd.

    Returns (new_content, dropped_something).
    """
    starts = [m.start() for m in re.finditer(r"\\resumeProjectHeading\b", tex_content)]
    if not starts:
        return tex_content, False

    last_start = starts[-1]
    end_match = re.search(r"\\resumeItemListEnd\b", tex_content[last_start:])
    if not end_match:
        return tex_content, False

    end_pos = last_start + end_match.end()

    # Expand left to the start of the heading's line
    line_start = tex_content.rfind("\n", 0, last_start) + 1

    # Expand right past one trailing newline so we don't leave a blank line
    trailing = end_pos
    while trailing < len(tex_content) and tex_content[trailing] in " \t":
        trailing += 1
    if trailing < len(tex_content) and tex_content[trailing] == "\n":
        trailing += 1

    return tex_content[:line_start] + tex_content[trailing:], True


def compile_with_page_fit(
    tex_file: Path,
    max_pages: int = 2,
    max_drop_attempts: int = 4,
    output_dir: Optional[Path] = None,
    output_name: Optional[str] = None,
    compile_twice: bool = True,
    clean_aux: bool = True,
    aux_extensions: Optional[list[str]] = None,
    timeout: int = 120,
) -> CompilationResult:
    """Compile LaTeX, then iteratively drop trailing project blocks until the
    output fits within max_pages.

    The LLM that writes the LaTeX cannot see the compiled page count, so even
    with explicit prompting it often overflows. This wrapper provides
    deterministic backstop: after the first compile, if the PDF is > max_pages,
    drop the last project block from the .tex and recompile. Repeat up to
    max_drop_attempts times.

    Only touches \\resumeProjectHeading blocks. Never modifies Experience,
    Skills, or Education sections. Writes the modified .tex back to disk so it
    matches the final PDF.
    """
    kwargs = dict(
        output_dir=output_dir,
        output_name=output_name,
        compile_twice=compile_twice,
        clean_aux=clean_aux,
        aux_extensions=aux_extensions,
        timeout=timeout,
    )

    result = compile_latex(tex_file, **kwargs)
    if not result.success:
        return result

    pages = _page_count_from_log(result.log_content)
    if pages == 0 or pages <= max_pages:
        return result

    logger.info(f"Resume compiled to {pages} pages (over {max_pages}); dropping projects and recompiling")

    tex_content = tex_file.read_text(encoding="utf-8")

    for attempt in range(1, max_drop_attempts + 1):
        new_content, dropped = _drop_last_project_block(tex_content)
        if not dropped:
            logger.warning("No more project blocks to drop; returning current result")
            break

        tex_content = new_content
        tex_file.write_text(tex_content, encoding="utf-8")

        result = compile_latex(tex_file, **kwargs)
        if not result.success:
            return result

        pages = _page_count_from_log(result.log_content)
        logger.info(f"Page-fit attempt {attempt}: {pages} pages")
        if pages <= max_pages:
            logger.info(f"Resume fit within {max_pages} pages after {attempt} project drop(s)")
            return result

    return result


def check_pdflatex_available() -> tuple[bool, str]:
    """Check if pdflatex is available and return version info."""
    pdflatex = find_pdflatex()

    if not pdflatex:
        return False, "pdflatex not found"

    try:
        result = subprocess.run(
            [pdflatex, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.split("\n")[0] if result.stdout else "unknown version"
        return True, f"{pdflatex} ({version})"

    except Exception as e:
        return False, f"Error checking pdflatex: {e}"
