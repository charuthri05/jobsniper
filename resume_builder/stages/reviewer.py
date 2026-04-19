"""Stage 2: Reviewer - Validates the plan and provides feedback."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from resume_builder.config import Config
from resume_builder.stages.base import BaseStage
from resume_builder.utils.jd_parser import JDMetadata


REVIEWER_SYSTEM_PROMPT = """You are an expert resume reviewer specializing in technical resumes for software engineering roles.

Your task is to review a resume rewrite plan and provide detailed feedback to ensure the final resume will be optimally tailored to the target job description.

REVIEW CRITERIA:
1. JD ALIGNMENT: Does the plan address the key requirements in the JD?
2. AUTHENTICITY: Are the proposed rewrites based on actual experience (no fabrication)?
3. IMPACT: Do the bullet points emphasize quantifiable achievements?
4. KEYWORDS: Are relevant technical keywords from the JD incorporated?
5. COMPLETENESS: Does the plan cover all resume sections appropriately?
6. STYLE: Call out any proposed rewrites that (a) use em-dashes ("---", "--", " — ") inside bullet text, (b) narrate internal architecture instead of claiming impact, (c) use filler words ("leveraging", "utilizing", "hands-on", "proactively", "materially", "significantly improved", "cutting-edge", "robust", "seamless"), (d) exceed ~1.5 lines per bullet, or (e) break from the sentence rhythm of the candidate's existing bullets in the template.

OUTPUT FORMAT:
You MUST respond with exactly these sections in this order:

ASSESSMENT: [Good/Needs Improvement/Major Issues]

ALIGNMENT_SCORE: [1-10]

GAPS_IDENTIFIED:
- [Gap 1: Description of what's missing or could be improved]
- [Gap 2: Description]
(If no gaps: "No significant gaps identified")

REQUIRED_ADJUSTMENTS:
### Current Role Section
- [Specific adjustment needed]
- [Another adjustment]

### Previous Role Section
- [Specific adjustment needed]

### Projects
- [Specific adjustment needed]

### Skills
- [Specific adjustment needed]

### Style
- [Flag any em-dashes, architecture narration, filler words, or voice mismatches found in the plan]

(If a section needs no changes, write "No adjustments needed")

ADDITIONAL_RECOMMENDATIONS:
- [Recommendation 1: Actionable suggestion]
- [Recommendation 2: Actionable suggestion]

Be specific and actionable in your feedback. Reference specific JD requirements and plan items."""


@dataclass
class ReviewFeedback:
    """Parsed review feedback."""

    assessment: str
    alignment_score: int
    gaps: list[str]
    linq_adjustments: list[str]
    applogic_adjustments: list[str]
    project_adjustments: list[str]
    skills_adjustments: list[str]
    recommendations: list[str]
    raw_content: str

    @property
    def needs_revision(self) -> bool:
        """Check if the plan needs significant revision."""
        return self.assessment in ("Needs Improvement", "Major Issues")

    @property
    def has_gaps(self) -> bool:
        """Check if gaps were identified."""
        if not self.gaps:
            return False
        return not any("no significant gaps" in g.lower() for g in self.gaps)


class ReviewerStage(BaseStage):
    """Stage 2: Reviewer - Validates plan and provides feedback."""

    stage_name = "Stage 2: Reviewer"
    stage_number = 2

    def __init__(
        self,
        config: Config,
        output_dir: Path,
        jd_metadata: JDMetadata,
    ):
        super().__init__(config, output_dir)
        self.jd_metadata = jd_metadata

    def build_system_prompt(self) -> str:
        return REVIEWER_SYSTEM_PROMPT

    def build_user_prompt(self, **kwargs: Any) -> str:
        """
        Build user prompt with plan and context.

        Expected kwargs:
            plan_content: str - Content of resume_plan.md from Stage 1
            linq_experience: str - Content of Linq experience file
            applogic_experience: str - Content of AppLogic experience file
            projects: str - Content of projects file
        """
        plan_content = kwargs.get("plan_content", "")
        linq_experience = kwargs.get("linq_experience", "")
        applogic_experience = kwargs.get("applogic_experience", "")
        projects = kwargs.get("projects", "")

        tech_stack_str = ", ".join(self.jd_metadata.tech_stack) if self.jd_metadata.tech_stack else "Not specified"

        prompt = f"""## Target Job Description

**Company:** {self.jd_metadata.company}
**Role:** {self.jd_metadata.role}
**Key Technologies:** {tech_stack_str}

### Full JD Content:
{self.jd_metadata.raw_content}

---

## Resume Rewrite Plan (from Stage 1):
{plan_content}

---

## Source Materials (for verification):

### Current Role Experience:
{linq_experience}

### Previous Role Experience:
{applogic_experience}

### Projects:
{projects}

---

## Your Task

Review the resume rewrite plan above and provide detailed feedback:

1. Assess overall alignment with the {self.jd_metadata.company} {self.jd_metadata.role} position
2. Identify any gaps where JD requirements are not addressed
3. Suggest specific adjustments to improve alignment
4. Verify all proposed rewrites are based on actual experience
5. Provide additional recommendations for optimization

Be specific and reference exact items from the plan and JD."""

        return prompt

    def get_output_filename(self) -> str:
        return self.config.stages.reviewer.output_file

    def execute(self, **kwargs: Any):
        """Execute reviewer with plan and context."""
        base_dir = kwargs.get("base_dir", Path.cwd())

        # Load plan from Stage 1
        if "plan_content" not in kwargs:
            plan_file = self.output_dir / self.config.stages.planner.output_file
            if not plan_file.exists():
                raise FileNotFoundError(
                    f"Plan file not found: {plan_file}. Run Stage 1 (Planner) first."
                )
            kwargs["plan_content"] = self.load_file(plan_file)

        # Load experience files
        if "linq_experience" not in kwargs:
            linq_path = base_dir / self.config.inputs.experience.current
            kwargs["linq_experience"] = self.load_file(linq_path)

        if "applogic_experience" not in kwargs:
            applogic_path = base_dir / self.config.inputs.experience.previous
            kwargs["applogic_experience"] = self.load_file(applogic_path)

        if "projects" not in kwargs:
            projects_path = base_dir / self.config.inputs.projects
            kwargs["projects"] = self.load_file(projects_path)

        return super().execute(**kwargs)

    def parse_feedback(self, content: str) -> ReviewFeedback:
        """Parse structured feedback from reviewer response."""
        # Extract assessment
        assessment_match = re.search(r"ASSESSMENT:\s*(.+?)(?:\n|$)", content)
        assessment = assessment_match.group(1).strip() if assessment_match else "Unknown"

        # Extract alignment score
        score_match = re.search(r"ALIGNMENT_SCORE:\s*(\d+)", content)
        alignment_score = int(score_match.group(1)) if score_match else 0

        # Extract gaps
        gaps = self._extract_list_section(content, "GAPS_IDENTIFIED")

        # Extract adjustments by section
        adjustments_section = self._extract_section(content, "REQUIRED_ADJUSTMENTS")
        linq_adjustments = self._extract_subsection_list(adjustments_section, "Linq Section")
        applogic_adjustments = self._extract_subsection_list(adjustments_section, "AppLogic Section")
        project_adjustments = self._extract_subsection_list(adjustments_section, "Projects")
        skills_adjustments = self._extract_subsection_list(adjustments_section, "Skills")

        # Extract recommendations
        recommendations = self._extract_list_section(content, "ADDITIONAL_RECOMMENDATIONS")

        return ReviewFeedback(
            assessment=assessment,
            alignment_score=alignment_score,
            gaps=gaps,
            linq_adjustments=linq_adjustments,
            applogic_adjustments=applogic_adjustments,
            project_adjustments=project_adjustments,
            skills_adjustments=skills_adjustments,
            recommendations=recommendations,
            raw_content=content,
        )

    def _extract_section(self, content: str, section_name: str) -> str:
        """Extract a named section from content."""
        pattern = rf"{section_name}:\s*\n(.*?)(?=\n[A-Z_]+:|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_list_section(self, content: str, section_name: str) -> list[str]:
        """Extract bullet points from a section."""
        section = self._extract_section(content, section_name)
        if not section:
            return []
        bullets = re.findall(r"^[-*]\s*(.+?)$", section, re.MULTILINE)
        return [b.strip() for b in bullets if b.strip()]

    def _extract_subsection_list(self, content: str, subsection_name: str) -> list[str]:
        """Extract bullet points from a subsection (### Header)."""
        pattern = rf"###\s*{subsection_name}\s*\n(.*?)(?=###|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
        bullets = re.findall(r"^[-*]\s*(.+?)$", match.group(1), re.MULTILINE)
        return [b.strip() for b in bullets if b.strip()]
