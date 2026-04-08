"""Output folder management for resume builds."""

import re
from pathlib import Path


def sanitize_name(name: str) -> str:
    """Remove special characters and spaces from a name."""
    return re.sub(r"[^a-zA-Z0-9]", "", name)


def create_output_folder(
    company: str,
    role: str,
    base_dir: Path,
    folder_format: str = "{company}_{role}",
) -> Path:
    """
    Create output folder for a resume build.

    Args:
        company: Company name
        role: Role/position name
        base_dir: Base output directory (e.g., ./output)
        folder_format: Format string with {company} and {role} placeholders

    Returns:
        Path to the created output folder

    Handles duplicates by appending _2, _3, etc.
    """
    company_clean = sanitize_name(company)
    role_clean = sanitize_name(role)

    folder_name = folder_format.format(company=company_clean, role=role_clean)

    output_path = base_dir / folder_name

    if not output_path.exists():
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    # Handle duplicates
    counter = 2
    while True:
        numbered_path = base_dir / f"{folder_name}_{counter}"
        if not numbered_path.exists():
            numbered_path.mkdir(parents=True, exist_ok=True)
            return numbered_path
        counter += 1


def get_latest_output_folder(
    company: str,
    role: str,
    base_dir: Path,
    folder_format: str = "{company}_{role}",
) -> Path | None:
    """
    Find the most recent output folder for a company/role.

    Returns None if no folder exists.
    """
    company_clean = sanitize_name(company)
    role_clean = sanitize_name(role)
    base_name = folder_format.format(company=company_clean, role=role_clean)

    if not base_dir.exists():
        return None

    # Find all matching folders
    pattern = re.compile(rf"^{re.escape(base_name)}(?:_\d+)?$")
    matching = [d for d in base_dir.iterdir() if d.is_dir() and pattern.match(d.name)]

    if not matching:
        return None

    # Return most recently modified
    return max(matching, key=lambda p: p.stat().st_mtime)
