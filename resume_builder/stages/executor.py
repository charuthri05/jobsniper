"""Stage 3: Executor - Generates final LaTeX resume."""

import re
from pathlib import Path
from typing import Any

from resume_builder.config import Config
from resume_builder.stages.base import BaseStage, StageResult
from resume_builder.utils.jd_parser import JDMetadata


EXECUTOR_SYSTEM_PROMPT = r"""You are a senior technical resume editor. Your task is to generate a complete, compilable LaTeX resume from a rewrite plan and reviewer feedback, using the provided LaTeX template as the structural and stylistic source of truth.

OUTPUT RULES:
1. Output ONLY the complete LaTeX document, starting with \documentclass and ending with \end{document}. No markdown code fences. No explanations before or after.
2. Preserve the exact LaTeX preamble, custom commands, section ordering, and formatting of the provided template.
3. Preserve ALL protected content exactly as it appears in the provided template: candidate's name, phone, email, LinkedIn URL, GitHub URL (if present), education institutions, education dates, employment company names, and employment dates. Do not infer or replace these from memory.

STYLE RULES (CRITICAL — these separate a human-written resume from an AI-generated one):

1. NO em-dashes anywhere in bullet text. Do not use "---", "--", " — ", en-dashes, or any long dash as a sentence connector inside bullets. Use commas, periods, semicolons, or natural prepositions: "with", "while", "to", "for", "that", "after", "during", "achieving", "enabling", "reducing", "preventing". (Dashes ARE allowed in date ranges like "Aug 2023 -- Dec 2024" — those are already in the template, preserve them verbatim.)

2. Bullet anatomy — every bullet follows this shape:
   [strong action verb in past/present tense] + [what was built or done, with specific technology in \textbf{}] + [context or purpose, optional] + [measurable impact with numbers in \textbf{}]

   GOOD: "Architected integration services connecting Linq with \textbf{Salesforce, HubSpot and GoHighLevel CRMs}, processing \textbf{150K+ requests/minute} while enabling seamless contact synchronization for 40K+ users."

   BAD: "Built an integration service, a NestJS backend that authenticates via OAuth2, handles webhook callbacks through a message queue, and transforms payloads through a middleware layer, which processes high volumes of requests."

   The bad version narrates internal architecture. The good version states impact.

3. Keep bullets to roughly 1.5 lines. One achievement per bullet. If a bullet describes three internals, split it or cut two.

4. State WHAT was built, WHICH technology, and WHAT measurable result. Do not explain how internals work (session UUIDs, filter chains, control-loop details, consumer group configs). Those belong in the interview, not the resume.

5. Avoid filler: "leveraging", "utilizing", "cutting-edge", "robust", "hands-on experience", "proactively", "materially", "significantly improved", "optimally", "best-in-class", "world-class", "comprehensive solution".

6. Prefer specific metrics over generic claims. "Reduced p95 latency by 40% (500ms to 300ms)" beats "significantly improved latency".

7. Bold key technologies and key numeric metrics with \textbf{}. Bold the noun phrases that matter, not verbs or whole sentences.

8. Match the sentence rhythm and diction of the existing bullets in the provided template. If the template uses "Optimized PostgreSQL query performance through composite indexes and materialized views, transforming 2.3-second queries to sub-50ms responses without schema changes", do not suddenly switch to a denser, jargon-heavy tone in new bullets.

9. Never fabricate experience, tools, or metrics that are not grounded in the rewrite plan or source experience materials.

TAILORING STRATEGY (apply to every JD, not just this one):

1. The candidate's master template is the baseline. For per-JD tailoring, ADD new JD-relevant bullets into the current-role experience section. Do NOT rewrite or reorder bullets in other sections (previous roles, projects, skills, education) unless rule 3 applies.

2. Preserve every work experience section as real employment history, including short internships. Never drop a role, regardless of duration, to save space.

3. When the resume exceeds the target page count, compress in this exact order:
   a. Drop one project entirely (lowest JD-signal project first)
   b. If still too long, drop a second project
   c. Only then consider trimming individual bullets within non-experience sections
   d. Never drop a work experience subsection

4. Tune the SUMMARY section per JD for ATS matching:
   - Keep the candidate's original sentence rhythm and structure
   - Reorder skill clusters and technology lists so JD-priority terms appear first (leading terms get ATS weight)
   - Only include skills the candidate actually has — no fabrication
   - Keep the summary dense with JD keywords while remaining natural prose

OUTPUT FORMAT:
Return ONLY the complete LaTeX document, beginning with \documentclass and ending with \end{document}. No code fences. No commentary. No reasoning steps.
"""


class ExecutorStage(BaseStage):
    """Stage 3: Executor - Generates final LaTeX from plan + feedback."""

    stage_name = "Stage 3: Executor"
    stage_number = 3

    def __init__(
        self,
        config: Config,
        output_dir: Path,
        jd_metadata: JDMetadata,
    ):
        super().__init__(config, output_dir)
        self.jd_metadata = jd_metadata

    def build_system_prompt(self) -> str:
        return EXECUTOR_SYSTEM_PROMPT

    def build_user_prompt(self, **kwargs: Any) -> str:
        """
        Build user prompt with plan, feedback, and template.

        Expected kwargs:
            plan_content: str - Content of resume_plan.md from Stage 1
            feedback_content: str - Content of review_feedback.md from Stage 2
            latex_template: str - Content of base LaTeX template
        """
        plan_content = kwargs.get("plan_content", "")
        feedback_content = kwargs.get("feedback_content", "")
        latex_template = kwargs.get("latex_template", "")

        prompt = f"""## Target Position
**Company:** {self.jd_metadata.company}
**Role:** {self.jd_metadata.role}

---

## Resume Rewrite Plan (Stage 1):
{plan_content}

---

## Reviewer Feedback (Stage 2):
{feedback_content}

---

## Base LaTeX Template:
{latex_template}

---

## Your Task

Generate the COMPLETE LaTeX resume by:
1. Starting with the base template structure
2. Applying ALL changes from the rewrite plan
3. Incorporating ALL adjustments from the reviewer feedback
4. Ensuring the resume is optimized for the {self.jd_metadata.company} {self.jd_metadata.role} position

REMEMBER:
- Output ONLY valid LaTeX code
- DO NOT modify protected content (name, contact info, dates)
- Preserve all LaTeX formatting commands and structure
- The output must compile without errors

Begin your response with \\documentclass and end with \\end{{document}}."""

        return prompt

    def get_output_filename(self) -> str:
        return self.config.stages.executor.output_file

    def execute(self, **kwargs: Any) -> StageResult:
        """Execute executor with plan, feedback, and template."""
        base_dir = kwargs.get("base_dir", Path.cwd())

        # Load plan from Stage 1
        if "plan_content" not in kwargs:
            plan_file = self.output_dir / self.config.stages.planner.output_file
            if not plan_file.exists():
                raise FileNotFoundError(
                    f"Plan file not found: {plan_file}. Run Stage 1 (Planner) first."
                )
            kwargs["plan_content"] = self.load_file(plan_file)

        # Load feedback from Stage 2
        if "feedback_content" not in kwargs:
            feedback_file = self.output_dir / self.config.stages.reviewer.output_file
            if not feedback_file.exists():
                raise FileNotFoundError(
                    f"Feedback file not found: {feedback_file}. Run Stage 2 (Reviewer) first."
                )
            kwargs["feedback_content"] = self.load_file(feedback_file)

        # Load LaTeX template
        if "latex_template" not in kwargs:
            template_path = base_dir / self.config.inputs.resume_template
            kwargs["latex_template"] = self.load_file(template_path)

        return super().execute(**kwargs)

    def save_output(self, content: str) -> Path:
        """Save LaTeX output, extracting from code blocks if needed."""
        latex_content = self.extract_latex(content)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / self.get_output_filename()
        output_file.write_text(latex_content)

        self.logger.info(f"Saved LaTeX to: {output_file}")
        return output_file

    def extract_latex(self, content: str) -> str:
        """Extract LaTeX content from response."""
        # Try to extract from markdown code block first
        latex_block = re.search(r"```(?:latex|tex)?\s*(.*?)```", content, re.DOTALL)
        if latex_block:
            return latex_block.group(1).strip()

        # Look for content between \documentclass and \end{document}
        doc_match = re.search(
            r"(\\documentclass.*?\\end\{document\})",
            content,
            re.DOTALL,
        )
        if doc_match:
            return doc_match.group(1).strip()

        # Return as-is if it looks like LaTeX
        if "\\documentclass" in content and "\\end{document}" in content:
            return content.strip()

        self.logger.warning("Could not extract LaTeX from response, returning raw content")
        return content.strip()

    def validate_protected_content(self, latex: str, template: str) -> list[str]:
        """Check if protected content was modified."""
        warnings = []

        protected_patterns = [
            (r"Siddartha Kodaboina", "Name"),
            (r"\(669\) 649-2373", "Phone"),
            (r"stevesiddu49@gmail\.com", "Email"),
            (r"Aug 2023 - May 2025", "Masters dates"),
            (r"Jun 2017 -- May 2021", "Bachelors dates"),
            (r"Aug 2025 -- Present", "Linq dates"),
            (r"Jul 2021 -- Jul 2023", "AppLogic dates"),
        ]

        for pattern, name in protected_patterns:
            if re.search(pattern, template) and not re.search(pattern, latex):
                warnings.append(f"Protected content may be modified: {name}")

        return warnings
