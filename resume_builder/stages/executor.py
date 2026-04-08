"""Stage 3: Executor - Generates final LaTeX resume."""

import re
from pathlib import Path
from typing import Any

from resume_builder.config import Config
from resume_builder.stages.base import BaseStage, StageResult
from resume_builder.utils.jd_parser import JDMetadata


EXECUTOR_SYSTEM_PROMPT = """You are an expert LaTeX resume writer. Your task is to generate a complete, compilable LaTeX resume based on a rewrite plan and reviewer feedback.

CRITICAL RULES:
1. Output ONLY the complete LaTeX document - no explanations, no markdown
2. The output must be a valid, compilable LaTeX file
3. Preserve ALL protected content exactly as shown (name, contact info, dates)
4. Apply the rewrite plan adjustments incorporating reviewer feedback
5. Maintain the exact LaTeX structure and formatting commands from the template

PROTECTED CONTENT (DO NOT MODIFY):
- Name: Siddartha Kodaboina
- Phone: (669) 649-2373
- Email: stevesiddu49@gmail.com
- LinkedIn URL and GitHub URL
- Education dates: "Aug 2023 - May 2025" and "Jun 2017 -- May 2021"
- Employment dates: "Aug 2025 -- Present" and "Jul 2021 -- Jul 2023"

OUTPUT FORMAT:
Return ONLY the complete LaTeX document starting with \\documentclass and ending with \\end{document}.
Do NOT wrap in markdown code blocks. Do NOT include any text before or after the LaTeX.
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
