"""Job Description parser for extracting metadata."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class JDMetadata:
    """Extracted metadata from a job description."""

    company: str
    role: str
    location: Optional[str] = None
    raw_content: str = ""
    required_skills: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)

    @property
    def folder_name(self) -> str:
        """Generate folder name from company and role."""
        company_clean = re.sub(r"[^a-zA-Z0-9]", "", self.company)
        role_clean = re.sub(r"[^a-zA-Z0-9]", "", self.role.replace(" ", ""))
        return f"{company_clean}_{role_clean}"


def parse_jd(jd_path: Path) -> JDMetadata:
    """
    Parse a job description markdown file.

    Expects YAML frontmatter with company, role, location.

    Args:
        jd_path: Path to the job description file

    Returns:
        JDMetadata with extracted information
    """
    content = jd_path.read_text()

    # Extract YAML frontmatter
    frontmatter = _extract_frontmatter(content)

    company = frontmatter.get("company", _infer_company(content))
    role = frontmatter.get("role", _infer_role(content))
    location = frontmatter.get("location")

    # Extract skills and tech stack
    required_skills = _extract_required_skills(content)
    nice_to_have = _extract_nice_to_have(content)
    tech_stack = _extract_tech_stack(content)

    return JDMetadata(
        company=company,
        role=role,
        location=location,
        raw_content=content,
        required_skills=required_skills,
        nice_to_have=nice_to_have,
        tech_stack=tech_stack,
    )


def _extract_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content."""
    pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(pattern, content, re.DOTALL)

    if match:
        try:
            return yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _infer_company(content: str) -> str:
    """Attempt to infer company name from content."""
    # Look for "About {Company}" pattern
    match = re.search(r"(?:About|Join)\s+([A-Z][a-zA-Z\s]+?)(?:\n|,|\.)", content)
    if match:
        return match.group(1).strip()

    # Look for company name in title
    match = re.search(r"^#\s*(.+?)\s*[-–—]", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return "Unknown Company"


def _infer_role(content: str) -> str:
    """Attempt to infer role from content."""
    # Look for role in title
    match = re.search(r"^#\s*(?:.+?[-–—])?\s*(.+?)$", content, re.MULTILINE)
    if match:
        role = match.group(1).strip()
        if len(role) < 100:
            return role

    # Look for "Role:" or similar
    match = re.search(r"(?:Role|Position|Title):\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return "Software Engineer"


def _extract_required_skills(content: str) -> list[str]:
    """Extract required skills from JD."""
    skills = []

    # Find "Required" section
    required_section = re.search(
        r"(?:###?\s*)?Required.*?\n(.*?)(?=###|\n\n[A-Z]|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )

    if required_section:
        # Extract bullet points
        bullets = re.findall(r"[-*]\s*(.+?)(?:\n|$)", required_section.group(1))
        skills.extend([b.strip() for b in bullets if b.strip()])

    return skills


def _extract_nice_to_have(content: str) -> list[str]:
    """Extract nice-to-have skills from JD."""
    skills = []

    # Find "Nice to Have" section
    nice_section = re.search(
        r"(?:###?\s*)?(?:Nice to Have|Preferred|Bonus).*?\n(.*?)(?=###|\n\n[A-Z]|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )

    if nice_section:
        bullets = re.findall(r"[-*]\s*(.+?)(?:\n|$)", nice_section.group(1))
        skills.extend([b.strip() for b in bullets if b.strip()])

    return skills


def _extract_tech_stack(content: str) -> list[str]:
    """Extract mentioned technologies from JD."""
    # Common tech patterns to look for
    tech_patterns = [
        r"\*\*([A-Za-z][A-Za-z0-9.]+(?:\s+[A-Za-z0-9.]+)?)\*\*",  # Bold text
        r"`([A-Za-z][A-Za-z0-9.]+)`",  # Code blocks
    ]

    techs = set()
    for pattern in tech_patterns:
        matches = re.findall(pattern, content)
        techs.update(m.strip() for m in matches if len(m.strip()) > 1)

    # Filter known tech terms
    known_tech = {
        "Node.js", "TypeScript", "JavaScript", "Python", "Go", "Rust", "Java",
        "NestJS", "Express", "React", "Vue", "Angular", "Next.js",
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "DynamoDB",
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "ECS", "Lambda",
        "Terraform", "CDK", "GitHub Actions", "Jenkins", "GitLab",
        "gRPC", "REST", "GraphQL", "Kafka", "RabbitMQ", "NATS",
        "New Relic", "Datadog", "Sentry", "PagerDuty", "Prometheus", "Grafana",
    }

    # Return techs that match known terms (case-insensitive)
    known_lower = {t.lower(): t for t in known_tech}
    result = []
    for tech in techs:
        if tech.lower() in known_lower:
            result.append(known_lower[tech.lower()])
        elif tech in known_tech:
            result.append(tech)

    return sorted(set(result))
