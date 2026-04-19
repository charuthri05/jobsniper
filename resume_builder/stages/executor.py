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

TAILORING STRATEGY (apply to every JD — READ CAREFULLY):

1. JD-DRIVEN ADDITIONS ARE MANDATORY (NOT OPTIONAL).
   The purpose of per-JD tailoring is to make the resume densely match the JD's top requirements. A generated resume that is nearly identical to the master is a tailoring FAILURE. For every JD you MUST:
     a. Identify the JD's top 5-8 technical priorities (technologies, skills, domains, system types).
     b. Check which priorities the candidate's source experience materials actually demonstrate.
     c. For each JD priority the master template does NOT already surface, ADD a new bullet to the appropriate experience sub-section (current role for current-role work, or a previous-role sub-section for that role's work).
   The candidate's source experience materials (in the user prompt) are the canonical source of truth for what they have done; the master is a subset and often omits JD-relevant work. Leaving a clear JD requirement unmentioned when the source describes that work is a bug, not a safe default.

2. KEEP ALL EXISTING MASTER BULLETS BY DEFAULT.
   Every bullet in the master template stays. Do NOT drop a master bullet just because it has low JD relevance. Drop master bullets ONLY when the resume exceeds two pages after all additions (see rule 7 compression order), and even then only the LOWEST-JD-RELEVANCE master bullets go first. Never drop a JD-relevant master bullet.

3. LIGHT REWORDING OF EXISTING MASTER BULLETS — OPTIONAL, WITH STRICT INVARIANTS.
   You may lightly reword an existing master bullet to surface a JD keyword the bullet's real facts support. Invariants:
     a. Underlying fact, technology, and what the metric measured do not change. "Reduced unauthorized access attempts by 92%" stays about unauthorized access. Do not reframe "case management usability" as "design workflow efficiency".
     b. Metric number preserved exactly. If source has no number, output has no number. NEVER drop a metric that is in the source.
     c. No filler or soft-skill additions ("scalable", "production-ready", "enterprise-grade", "mentoring junior engineers", "leading teams", "driving cross-functional discussions") unless already in source.
     d. If you cannot reword without violating (a)-(c), leave the bullet verbatim.

   CONCRETE BAD EXAMPLE (do not do this):
     Source bullet: "Implemented ML-powered search algorithms to improve legal document retrieval, increasing search relevance by 30%."
     BAD rewording (for a detection-engineering JD): "Built ML-powered anomaly detection for legal document classification using text embeddings and semantic similarity algorithms, identifying suspicious document patterns related to fraud detection and improving case outcome predictions."
     Why bad:
       - Changed the system's purpose from "search retrieval" to "anomaly detection / fraud detection" (changes what was built).
       - Dropped the 30% metric entirely.
       - Introduced "fraud detection" which is not in source materials (fabricated scope).
     ACCEPTABLE alternative: either leave verbatim, or "Implemented ML-powered semantic search algorithms for legal document retrieval using text embeddings, increasing search relevance by 30%." (keeps fact, keeps metric, just adds the specific ML technique which source confirms). If even that is a stretch, leave verbatim.

4. PROJECTS — BULLETS VERBATIM, DROP WHOLE PROJECTS FOR SPACE.
   Never reword project bullets. If space requires compression, drop a whole project sub-section (lowest JD-signal first). Never trim individual bullets inside a kept project.

5. SKILLS — REORDER ALLOWED, LINE-DROPS FOR SPACE.
   Reorder skill category lines so JD-priority categories appear first. Drop an entire skill line only if space is tight. Do not add skills the candidate does not have, and do not rewrite line content.

6. EDUCATION — VERBATIM, ALWAYS. Never modify.

7. TARGET IS TWO FULL PAGES, AFTER JD-DRIVEN ADDITIONS.
   JD-relevant additions take priority over page count. Do NOT skip a required addition because the master is already at two pages — add the bullet first, then compress other content to make room.

   CRITICAL HEURISTIC — YOU CANNOT SEE THE COMPILED PAGE COUNT, SO USE THIS RULE:
   The master template fills approximately two pages by itself. Each additional experience bullet adds roughly 1-2 lines. Therefore:
     - If you add 1-2 new experience bullets total (across all experience sections), the output will likely still fit in two pages. No project drops required.
     - If you add 3-4 new experience bullets total, you MUST drop ONE project entirely to make room.
     - If you add 5-6 new experience bullets total, you MUST drop TWO projects entirely.
     - If you add 7+ new experience bullets total, drop all projects except the single highest-JD-relevance one, and consider dropping 1-2 skill lines.
   Count your additions before finalizing the output. Drop projects proactively per this rule. Going to three pages is a FAILURE and must not happen.

   Compression order when overflow is expected (stop at the first step that fits):
     a. Drop one project entirely (lowest JD-signal first — for non-systems roles drop Taco-DB first; for non-cloud/monitoring roles drop URL Shortener first; drop Real-Time Chat last).
     b. Drop a second project entirely.
     c. Drop the lowest-JD-relevance master bullets from experience sub-sections (bullets whose technology and domain have no connection to JD priorities). Never drop a JD-relevant master bullet. Never reduce a sub-section to zero bullets.
     d. Drop skill category lines (least JD-relevant first).
     e. Drop the lowest-alignment ADDED experience bullets.
     f. As a last resort, lightly adjust LaTeX spacing (\vspace, itemsep) so content fits.

   NEVER drop a whole experience sub-section.
   NEVER drop a JD-relevant bullet (master or added).
   NEVER merge or split a master bullet.
   NEVER let the output exceed two pages.

8. NO FABRICATION (ABSOLUTE, APPLIES EVERYWHERE).
   Never invent metrics, technologies, responsibilities, or soft claims. If source has no number, output has no number. Never add "99.9% uptime", "mentoring junior engineers", "leading teams", "enterprise-grade", "production-ready", "driving cross-functional collaboration" unless verbatim in source.

9. SUMMARY TUNING. Rewrite the summary to match JD keywords for ATS. Draw the candidate's skill set from SOURCE EXPERIENCE MATERIALS, not just the master summary — the master often omits JD-relevant skills the candidate actually has. For example, if the master summary says "full-stack and distributed systems" but source describes GenAI agent development and observability engineering, and the JD is for detection engineering, the tuned summary must surface those real skills.
   - Keep the original summary's sentence rhythm and length.
   - Swap in JD-aligned skill clusters and technology lists so JD-priority terms appear first (ATS weight).
   - Pull skills from source materials. Only include skills the candidate actually has.
   - Never add fabricated soft-skill claims or metrics.

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
