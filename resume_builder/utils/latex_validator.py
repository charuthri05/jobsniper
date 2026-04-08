"""LaTeX validation utilities."""

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of LaTeX validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def validate_latex(content: str) -> ValidationResult:
    """
    Validate LaTeX content for common issues.

    Args:
        content: LaTeX document content

    Returns:
        ValidationResult with errors and warnings
    """
    errors = []
    warnings = []

    # Check for document structure
    if "\\documentclass" not in content:
        errors.append("Missing \\documentclass declaration")

    if "\\begin{document}" not in content:
        errors.append("Missing \\begin{document}")

    if "\\end{document}" not in content:
        errors.append("Missing \\end{document}")

    # Check brace balance
    brace_errors = check_brace_balance(content)
    errors.extend(brace_errors)

    # Check environment balance
    env_errors = check_environment_balance(content)
    errors.extend(env_errors)

    # Check for required resume sections
    section_warnings = check_resume_sections(content)
    warnings.extend(section_warnings)

    # Check for common LaTeX errors
    common_errors = check_common_errors(content)
    warnings.extend(common_errors)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def check_brace_balance(content: str) -> list[str]:
    """
    Check for severely unbalanced braces {} in LaTeX content.

    Note: This is a simplified check that only catches severe imbalances.
    Complex LaTeX with nested commands may have false positives, so we
    only report very large imbalances.
    """
    errors = []

    # Simple count-based check
    open_count = content.count("{")
    close_count = content.count("}")

    # Account for escaped braces
    escaped_open = len(re.findall(r"\\{", content))
    escaped_close = len(re.findall(r"\\}", content))

    actual_open = open_count - escaped_open
    actual_close = close_count - escaped_close

    diff = abs(actual_open - actual_close)

    # Only report if severely imbalanced (threshold of 10 to avoid false positives)
    if diff > 10:
        if actual_open > actual_close:
            errors.append(f"Possibly {diff} unclosed braces")
        else:
            errors.append(f"Possibly {diff} extra closing braces")

    return errors


def check_environment_balance(content: str) -> list[str]:
    """Check for balanced \\begin{} and \\end{} pairs."""
    errors = []

    # Find all begin/end pairs
    begins = re.findall(r"\\begin\{(\w+)\}", content)
    ends = re.findall(r"\\end\{(\w+)\}", content)

    begin_counts = {}
    for env in begins:
        begin_counts[env] = begin_counts.get(env, 0) + 1

    end_counts = {}
    for env in ends:
        end_counts[env] = end_counts.get(env, 0) + 1

    all_envs = set(begin_counts.keys()) | set(end_counts.keys())

    for env in all_envs:
        begin_count = begin_counts.get(env, 0)
        end_count = end_counts.get(env, 0)

        if begin_count > end_count:
            errors.append(f"Unclosed environment: {env} ({begin_count} begins, {end_count} ends)")
        elif end_count > begin_count:
            errors.append(f"Extra \\end{{{env}}}: ({begin_count} begins, {end_count} ends)")

    return errors


def check_resume_sections(content: str) -> list[str]:
    """Check for expected resume sections."""
    warnings = []

    expected_sections = [
        (r"\\section\{.*Education.*\}", "Education section"),
        (r"\\section\{.*Experience.*\}", "Experience section"),
        (r"\\section\{.*Skills.*\}", "Skills section"),
    ]

    for pattern, name in expected_sections:
        if not re.search(pattern, content, re.IGNORECASE):
            warnings.append(f"Missing expected section: {name}")

    return warnings


def check_common_errors(content: str) -> list[str]:
    """Check for common LaTeX errors."""
    warnings = []

    # Check for unescaped special characters (excluding in URLs)
    # Note: This is a simplified check
    if re.search(r"(?<!\\)[&%](?![a-zA-Z])", content):
        warnings.append("Possible unescaped special character (& or %)")

    # Check for common typos
    if "\\textb{" in content:
        warnings.append("Possible typo: \\textb{ should be \\textbf{")

    if "\\texti{" in content:
        warnings.append("Possible typo: \\texti{ should be \\textit{")

    # Check for empty items
    if re.search(r"\\item\s*\\item", content):
        warnings.append("Possible empty \\item")

    return warnings


def validate_protected_content(
    generated: str,
    template: str,
    protected_values: dict[str, str],
) -> list[str]:
    """
    Validate that protected content hasn't been modified.

    Args:
        generated: Generated LaTeX content
        template: Original template content
        protected_values: Dict of name -> value for protected content

    Returns:
        List of warnings for modified protected content
    """
    warnings = []

    for name, value in protected_values.items():
        # Escape regex special characters in value
        escaped_value = re.escape(value)

        if re.search(escaped_value, template) and not re.search(escaped_value, generated):
            warnings.append(f"Protected content may be modified: {name} ('{value}')")

    return warnings
