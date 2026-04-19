"""Stage 1: Planner - Analyzes JD and creates rewrite plan."""

from pathlib import Path
from typing import Any

from resume_builder.config import Config
from resume_builder.stages.base import BaseStage
from resume_builder.utils.jd_parser import JDMetadata


PLANNER_SYSTEM_PROMPT = """You are an expert resume optimization consultant specializing in tailoring technical resumes for specific job descriptions.

Your task is to analyze a job description and create a detailed plan for rewriting resume bullet points to maximize alignment with the JD requirements.

IMPORTANT RULES:
1. NEVER fabricate experience, tools, or metrics the candidate doesn't have. Only reframe existing experience.
2. Focus on reframing existing experience to highlight JD-relevant aspects.
3. Prioritize quantifiable achievements (metrics, percentages, scale).
4. Match the technical terminology used in the JD, but only when the candidate actually has that experience.

STYLE RULES for proposed rewrites (these carry downstream to the final resume):
- No em-dashes (no "---", "--", " — ") in bullet text. Use commas, semicolons, or natural prepositions.
- Each bullet follows: [action verb] + [what + specific tech] + [context] + [measurable impact]. Roughly 1.5 lines.
- State WHAT was built and WHAT impact it had. Do not narrate internal architecture (auth middleware layers, consumer groups, session IDs, filter chains) — those details belong in interviews.
- Match the sentence rhythm of the candidate's existing bullets in the provided LaTeX template — don't introduce a new voice.
- Avoid filler ("leveraging", "utilizing", "hands-on experience", "proactively", "materially", "significantly improved", "cutting-edge", "robust", "seamless").

OUTPUT FORMAT:
You MUST respond with exactly these sections in this order:

CURRENT_ROLE_REWRITE_PLAN:
| Current Bullet Summary | Rewrite Strategy | JD Keywords to Emphasize |
|------------------------|------------------|-------------------------|
| ... | ... | ... |

PREVIOUS_ROLE_REWRITE_PLAN:
| Current Bullet Summary | Rewrite Strategy | JD Keywords to Emphasize |
|------------------------|------------------|-------------------------|
| ... | ... | ... |

PROJECT_SELECTION:
| Project | Include (Yes/No) | Reason | JD Alignment |
|---------|------------------|--------|--------------|
| ... | ... | ... | ... |

SKILLS_REORDER:
Current Order: [list current skills order]
Proposed Order: [list proposed skills order prioritizing JD requirements]
Rationale: [brief explanation]

ADDITIONAL_RECOMMENDATIONS:
- [Any other suggestions for improving JD alignment]
"""


class PlannerStage(BaseStage):
    """Stage 1: Planner - Creates resume rewrite plan based on JD analysis."""

    stage_name = "Stage 1: Planner"
    stage_number = 1

    def __init__(
        self,
        config: Config,
        output_dir: Path,
        jd_metadata: JDMetadata,
    ):
        super().__init__(config, output_dir)
        self.jd_metadata = jd_metadata

    def build_system_prompt(self) -> str:
        return PLANNER_SYSTEM_PROMPT

    def build_user_prompt(self, **kwargs: Any) -> str:
        """
        Build user prompt with all context.

        Expected kwargs:
            linq_experience: str - Content of Linq experience file
            applogic_experience: str - Content of AppLogic experience file
            projects: str - Content of projects file
            latex_template: str - Content of LaTeX template
        """
        linq_experience = kwargs.get("linq_experience", "")
        applogic_experience = kwargs.get("applogic_experience", "")
        projects = kwargs.get("projects", "")
        latex_template = kwargs.get("latex_template", "")

        # Build tech stack summary
        tech_stack_str = ", ".join(self.jd_metadata.tech_stack) if self.jd_metadata.tech_stack else "Not specified"

        prompt = f"""## Target Job Description

**Company:** {self.jd_metadata.company}
**Role:** {self.jd_metadata.role}
**Location:** {self.jd_metadata.location or "Not specified"}
**Key Technologies:** {tech_stack_str}

### Full JD Content:
{self.jd_metadata.raw_content}

---

## Candidate's Current Role Experience:
{linq_experience}

---

## Candidate's Previous Role Experience:
{applogic_experience}

---

## Candidate's Projects:
{projects}

---

## Current Resume LaTeX Template (authoritative for dates, company names, bullet voice, and formatting):
```latex
{latex_template}
```

---

## Your Task

Analyze the job description and create a comprehensive plan for rewriting the resume to maximize alignment with this specific role at {self.jd_metadata.company}.

Focus on:
1. Which current-role bullets to emphasize or reword for {self.jd_metadata.role}
2. Which previous-role bullets to emphasize or reword
3. Which projects to include and why
4. How to reorder skills to match JD priorities

All proposed rewrites must match the sentence style of the candidate's existing bullets in the template (no em-dashes, no architecture narration, action-verb + tech + impact format).

Provide your response in the exact format specified in the system prompt."""

        return prompt

    def get_output_filename(self) -> str:
        return self.config.stages.planner.output_file

    def execute(self, **kwargs: Any):
        """Execute planner with all required context."""
        # Load files if paths provided instead of content
        base_dir = kwargs.get("base_dir", Path.cwd())

        if "linq_experience" not in kwargs:
            linq_path = base_dir / self.config.inputs.experience.current
            kwargs["linq_experience"] = self.load_file(linq_path)

        if "applogic_experience" not in kwargs:
            applogic_path = base_dir / self.config.inputs.experience.previous
            kwargs["applogic_experience"] = self.load_file(applogic_path)

        if "projects" not in kwargs:
            projects_path = base_dir / self.config.inputs.projects
            kwargs["projects"] = self.load_file(projects_path)

        if "latex_template" not in kwargs:
            template_path = base_dir / self.config.inputs.resume_template
            kwargs["latex_template"] = self.load_file(template_path)

        return super().execute(**kwargs)
