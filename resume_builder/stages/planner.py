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
5. PRIMARY DIRECTIVE — JD-DRIVEN ADDITIONS ARE MANDATORY: For every JD, actively identify which of the candidate's real source experiences match JD priorities and propose adding those as bullets in the appropriate experience sub-section (current role for current-role work, or a previous-role sub-section for that role's work). A plan that proposes no new bullets is a tailoring failure unless the master already surfaces every JD priority (rare). Source experience materials are the canonical source of truth; the master is a subset and often omits JD-relevant work.
6. For JD priorities the candidate has in source but the master does not surface, propose a NEW BULLET. For JD priorities the master surfaces but with wording that misses a JD keyword, propose a LIGHT REWORDING preserving fact / technology / what-the-metric-measured / metric number. Default to adding over rewording when in doubt.
7. KEEP ALL MASTER BULLETS BY DEFAULT. Do NOT propose dropping a master bullet just because it has low JD relevance. Dropping a master bullet is ONLY acceptable when the resume exceeds two pages after all additions, and even then only the lowest-JD-relevance master bullets go. Never propose merging or splitting a master bullet. Never propose dropping a JD-relevant bullet.
8. NEVER propose fabricated metrics or soft claims. If source says "reduced incident response time" without a number, do not propose "reduced incident response time by 60%". Numbers come only from source. No soft-skill additions ("mentoring", "leading", "driving", "scalable", "production-ready", "enterprise-grade") unless already in source.
9. TARGET is a two-page resume that is FULL, AFTER JD-driven additions. Additions take priority over page count — do not skip a required addition because the master is at two pages. If additions push past two pages, propose compression in this order: drop projects first (lowest-signal first), then drop lowest-JD-relevance master bullets (never JD-relevant ones), then drop skill lines, then as a last resort trim the lowest-alignment ADDED bullet. Never drop a JD-relevant bullet, never drop a whole experience sub-section.

STYLE RULES for proposed rewrites (these carry downstream to the final resume):
- No em-dashes (no "---", "--", " — ") in bullet text. Use commas, semicolons, or natural prepositions.
- Each bullet follows: [action verb] + [what + specific tech] + [context] + [measurable impact]. Roughly 1.5 lines.
- State WHAT was built and WHAT impact it had. Do not narrate internal architecture (auth middleware layers, consumer groups, session IDs, filter chains) — those details belong in interviews.
- Match the sentence rhythm of the candidate's existing bullets in the provided LaTeX template — don't introduce a new voice.
- Avoid filler ("leveraging", "utilizing", "hands-on experience", "proactively", "materially", "significantly improved", "cutting-edge", "robust", "seamless", "enterprise-grade", "production-ready", "mentoring", "driving", "leading").

OUTPUT FORMAT:
You MUST respond with exactly these sections in this order. Do not skip the ADDITIONS sections — they are the primary output of this stage.

JD_PRIORITIES:
[Numbered list of the top 5-8 technical priorities from the JD — specific technologies, skills, domains, or system types the role explicitly calls for.]

CURRENT_ROLE_ADDITIONS:
[REQUIRED. For each JD priority the candidate has in source materials but the master template does NOT surface, propose a new bullet. Phrase it in the candidate's existing bullet voice.]
| Proposed New Bullet | Source Material Grounding | JD Priorities Addressed |
|---------------------|---------------------------|-------------------------|
| ... | ... | ... |

PREVIOUS_ROLE_ADDITIONS:
[REQUIRED. Same as above but for previous-role sub-sections. Only propose when the real work happened at that role.]
| Sub-section (EDIS/PCS/Intern) | Proposed New Bullet | Source Material Grounding | JD Priorities Addressed |
|-------------------------------|---------------------|---------------------------|-------------------------|
| ... | ... | ... | ... |

CURRENT_ROLE_REWRITE_PLAN:
[Optional. Light rewording proposals for existing master bullets only when it surfaces a JD keyword without violating invariants.]
| Current Bullet Summary | Proposed Light Rewording | JD Keywords Surfaced |
|------------------------|--------------------------|----------------------|
| ... | ... | ... |

PREVIOUS_ROLE_REWRITE_PLAN:
[Optional. Same as above for previous-role bullets.]
| Sub-section | Current Bullet Summary | Proposed Light Rewording | JD Keywords Surfaced |
|-------------|------------------------|--------------------------|----------------------|
| ... | ... | ... | ... |

PROJECT_SELECTION:
| Project | Include (Yes/No) | Reason | JD Alignment |
|---------|------------------|--------|--------------|
| ... | ... | ... | ... |

SKILLS_REORDER:
Current Order: [list current skills order]
Proposed Order: [list proposed skills order prioritizing JD requirements]
Rationale: [brief explanation]

SUMMARY_REWRITE:
[Propose the tailored summary. Pull skills from SOURCE MATERIALS, not just the master summary. Lead with JD-priority skill clusters. Same rhythm and length as master summary. No fabricated claims.]

PAGE_FIT_STRATEGY:
[If additions push the resume past two pages, specify what to drop in order: projects first (lowest-signal first), then lowest-JD-relevance master bullets, then skill lines, then as a last resort an added bullet. If additions leave the resume short of two pages, specify additional source-grounded bullets to add.]

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
