"""
Bridge between our job pipeline and the 3-stage resume builder.

This is a thin adapter — it takes a job from our DB, writes a JD file,
loads the config pointing to our data/ files, and calls the resume builder's
orchestrator. The resume builder's core code (stages, services, prompts)
is completely untouched.
"""

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "resume_builder_config.yaml"
RESUMES_DIR = PROJECT_ROOT / "data" / "resumes"


def _write_jd_file(job: dict) -> Path:
    """Write a job description as a markdown file with YAML frontmatter
    in the format the resume builder expects."""
    jd_path = PROJECT_ROOT / "data" / "job_description_temp.md"

    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    location = job.get("location", "")
    description = job.get("description", "")

    content = f"""---
company: {company}
role: {title}
location: {location}
---

# {title}

## Company: {company}
## Location: {location}

{description}
"""
    jd_path.write_text(content, encoding="utf-8")
    return jd_path


def _update_protected_content():
    """Update the config's protected_content from candidate_profile.json
    so the builder knows what NOT to modify in the LaTeX."""
    import yaml

    try:
        from utils.profile import load_profile
        profile = load_profile()
    except Exception:
        return

    if not CONFIG_PATH.exists():
        return

    config = yaml.safe_load(CONFIG_PATH.read_text())

    config["protected_content"]["name"] = profile.get("name", "")
    config["protected_content"]["email"] = profile.get("email", "")
    config["protected_content"]["phone"] = profile.get("phone", "")
    config["protected_content"]["linkedin"] = profile.get("linkedin", "")
    config["protected_content"]["github"] = profile.get("github", "")

    # Build employment dates from experience entries
    emp_dates = {}
    for exp in profile.get("experience", []):
        company_key = exp.get("company", "").lower().replace(" ", "_")
        start = exp.get("start", "")
        end = exp.get("end", "present")
        if company_key and start:
            emp_dates[company_key] = f"{start} -- {end}"
    config["protected_content"]["employment_dates"] = emp_dates

    # Build education dates
    edu_dates = {}
    for edu in profile.get("education", []):
        school_key = edu.get("school", "").lower().replace(" ", "_")[:20]
        year = edu.get("year", "")
        if school_key and year:
            edu_dates[school_key] = str(year)
    config["protected_content"]["education_dates"] = edu_dates

    CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")


def _find_output_pdf(company: str, role: str) -> Path | None:
    """Find the generated PDF in the builder's output directory."""
    output_base = PROJECT_ROOT / "data" / "resume_output"
    if not output_base.exists():
        return None

    # Try all subdirs, match on company name prefix
    company_lower = company.lower().replace(" ", "_").replace("/", "-").replace(",", "")

    for folder in sorted(output_base.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        if company_lower[:10] in folder.name.lower():
            pdfs = list(folder.glob("*.pdf"))
            if pdfs:
                return pdfs[0]

    # Fallback — most recently modified PDF
    all_pdfs = list(output_base.rglob("*.pdf"))
    if all_pdfs:
        return max(all_pdfs, key=lambda p: p.stat().st_mtime)

    return None


def check_builder_ready() -> dict:
    """Check if the resume builder has all required input files."""
    issues = []

    if not CONFIG_PATH.exists():
        issues.append("Config not found: data/resume_builder_config.yaml")

    exp_current = PROJECT_ROOT / "data" / "experience" / "current.md"
    if not exp_current.exists():
        issues.append("Missing: data/experience/current.md (current work experience)")

    template = PROJECT_ROOT / "data" / "resume_template" / "template.tex"
    if not template.exists() or len(template.read_text(encoding="utf-8").strip()) < 50:
        issues.append("Missing: Base resume (upload your resume in Settings → Resume Builder)")

    # Check Claude CLI
    if not shutil.which("claude"):
        issues.append("Claude CLI not found — install with: npm install -g @anthropic-ai/claude-code")

    # Check pdflatex
    from resume_builder.utils.latex_compiler import find_pdflatex
    if not find_pdflatex():
        issues.append("pdflatex not found — install TeX (macOS: brew install basictex, Windows: miktex.org, Linux: apt install texlive)")

    return {
        "ready": len(issues) == 0,
        "issues": issues,
    }


def generate_resume(job: dict, progress_callback=None) -> dict:
    """
    Generate a tailored resume for a job using the 3-stage pipeline.

    Calls the friend's resume builder orchestrator directly — no subprocess,
    just Python function calls. The core code is untouched.

    Args:
        job: Job dict from our database
        progress_callback: Optional function(message) for progress updates

    Returns:
        dict with: success, pdf_path, error, plan, feedback
    """
    from rich.console import Console

    def update(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    result = {
        "success": False,
        "pdf_path": None,
        "error": None,
        "plan": None,
        "feedback": None,
    }

    # Pre-flight checks
    status = check_builder_ready()
    if not status["ready"]:
        result["error"] = "Resume builder not ready: " + "; ".join(status["issues"])
        return result

    # Write JD file
    jd_path = _write_jd_file(job)
    update(f"JD written: {job.get('title')} at {job.get('company')}")

    # Update protected content from profile
    try:
        _update_protected_content()
    except Exception as e:
        logger.warning(f"Could not update protected content: {e}")

    # Run each stage individually so we can update progress between them.
    # The orchestrator's code is untouched — we call run() with stage=1, 2, 3.
    try:
        from resume_builder.config import load_config
        from resume_builder.orchestrator import Orchestrator

        cfg = load_config(config_path=CONFIG_PATH)
        console = Console(quiet=True)
        orchestrator = Orchestrator(config=cfg, console=console)

        output_dir = None

        # Stage 1: Planner
        update("Stage 1/3: Planning resume rewrites...")
        plan_result = orchestrator.run(
            jd_path=jd_path, output_dir=output_dir, stage=1, dry_run=False, verbose=False,
        )
        if not plan_result.success:
            result["error"] = "Planner failed: " + "; ".join(plan_result.errors or ["unknown"])
            return result
        output_dir = plan_result.output_dir
        update(f"Stage 1 done ({plan_result.stage_times.get('planner', 0):.0f}s)")

        if plan_result.plan_file and plan_result.plan_file.exists():
            result["plan"] = plan_result.plan_file.read_text(encoding="utf-8")

        # Stage 2: Reviewer
        update("Stage 2/3: Reviewing and validating plan...")
        review_result = orchestrator.run(
            jd_path=jd_path, output_dir=output_dir, stage=2, dry_run=False, verbose=False,
        )
        if not review_result.success:
            result["error"] = "Reviewer failed: " + "; ".join(review_result.errors or ["unknown"])
            return result
        update(f"Stage 2 done ({review_result.stage_times.get('reviewer', 0):.0f}s)")

        if review_result.feedback_file and review_result.feedback_file.exists():
            result["feedback"] = review_result.feedback_file.read_text(encoding="utf-8")

        # Stage 3: Executor
        update("Stage 3/3: Generating LaTeX resume...")
        exec_result = orchestrator.run(
            jd_path=jd_path, output_dir=output_dir, stage=3, dry_run=False, verbose=False,
        )
        if not exec_result.success:
            result["error"] = "Executor failed: " + "; ".join(exec_result.errors or ["unknown"])
            return result
        update(f"Stage 3 done ({exec_result.stage_times.get('executor', 0):.0f}s). Compiling PDF...")

        # Find the PDF
        pdf_source = exec_result.pdf_file
        if not pdf_source or not pdf_source.exists():
            pdf_source = _find_output_pdf(job.get("company", ""), job.get("title", ""))

        if not pdf_source or not pdf_source.exists():
            result["error"] = "Pipeline completed but no PDF generated. Is pdflatex installed?"
            return result

        # Copy to our resumes directory
        RESUMES_DIR.mkdir(parents=True, exist_ok=True)
        dest = RESUMES_DIR / f"{job['id']}.pdf"
        shutil.copy2(str(pdf_source), str(dest))

        update(f"Resume saved: {dest.name}")
        result["success"] = True
        result["pdf_path"] = str(dest)
        return result

    except Exception as e:
        result["error"] = f"Pipeline error: {e}"
        logger.exception("Resume builder pipeline failed")
        return result


def generate_resume_fast(job: dict, progress_callback=None) -> dict:
    """
    Fast resume generation: one AI API call → LaTeX → pdflatex → PDF.

    Skips the 3-stage pipeline entirely. Uses the configured AI provider
    (OpenAI/Anthropic API) for speed (~20-30s instead of ~7min).
    """
    import re

    def update(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    result = {"success": False, "pdf_path": None, "error": None}

    # Check inputs
    status = check_builder_ready()
    if not status["ready"]:
        result["error"] = "Resume builder not ready: " + "; ".join(status["issues"])
        return result

    # Load inputs
    template_path = PROJECT_ROOT / "data" / "resume_template" / "template.tex"
    template = template_path.read_text(encoding="utf-8")

    experience_parts = []
    exp_dir = PROJECT_ROOT / "data" / "experience"
    for f in sorted(exp_dir.glob("*.md")):
        if f.name != "previous.md":  # skip merged file, read individual ones
            experience_parts.append(f.read_text(encoding="utf-8"))
    if not experience_parts:
        # fallback to merged
        merged = exp_dir / "previous.md"
        if merged.exists():
            experience_parts.append(merged.read_text(encoding="utf-8"))
    experience = "\n\n---\n\n".join(experience_parts)

    projects_path = PROJECT_ROOT / "data" / "projects" / "projects.md"
    projects = projects_path.read_text(encoding="utf-8") if projects_path.exists() else ""

    description = (job.get("description") or "")[:5000]
    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")

    update(f"Generating resume for {title} at {company}...")

    # One-shot AI call
    try:
        from utils.ai_client import chat_completion

        system = r"""You are an expert LaTeX resume writer. Generate a complete, compilable LaTeX resume tailored to a specific job description.

CRITICAL RULES:
1. Output ONLY the complete LaTeX document — no explanations, no markdown code blocks
2. Start with \documentclass and end with \end{document}
3. Keep ALL facts 100% accurate — only adjust emphasis, wording, and bullet ordering
4. NEVER fabricate experience or skills the candidate doesn't have
5. Reframe existing experience to highlight JD-relevant aspects
6. Use action verbs and quantifiable achievements
7. Match the technical terminology used in the JD
8. Preserve the exact LaTeX structure and formatting commands from the base template"""

        user_msg = f"""Tailor this resume for the job below. Rewrite bullet points to maximize alignment with the JD requirements. Reorder sections and bullets so the most relevant appear first.

## Target Job
**Company:** {company}
**Role:** {title}
**Description:**
{description}

## Candidate's Experience
{experience}

## Candidate's Projects
{projects}

## Base LaTeX Resume Template (preserve this structure exactly)
{template}

Generate the COMPLETE tailored LaTeX resume. Start with \\documentclass and end with \\end{{document}}."""

        update("AI generating tailored LaTeX...")
        raw = chat_completion(system=system, user_message=user_msg, max_tokens=4000)

        # Extract LaTeX
        code_match = re.search(r"```(?:latex|tex)?\s*(.*?)```", raw, re.DOTALL)
        if code_match:
            latex = code_match.group(1).strip()
        else:
            doc_match = re.search(r"(\\documentclass.*?\\end\{document\})", raw, re.DOTALL)
            if doc_match:
                latex = doc_match.group(1).strip()
            elif "\\documentclass" in raw and "\\end{document}" in raw:
                latex = raw.strip()
            else:
                result["error"] = "AI did not return valid LaTeX"
                return result

    except Exception as e:
        result["error"] = f"AI call failed: {e}"
        return result

    # Write .tex and compile with pdflatex
    try:
        from resume_builder.utils.latex_compiler import compile_latex, find_pdflatex

        if not find_pdflatex():
            result["error"] = "pdflatex not installed"
            return result

        output_dir = PROJECT_ROOT / "data" / "resume_output" / "fast"
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / "resume.tex"
        tex_path.write_text(latex, encoding="utf-8")

        update("Compiling PDF...")
        compile_result = compile_latex(
            tex_file=tex_path,
            output_dir=output_dir,
            compile_twice=True,
            clean_aux=True,
        )

        if not compile_result.success or not compile_result.pdf_path:
            result["error"] = f"pdflatex failed: {'; '.join(compile_result.errors[:3])}"
            return result

        # Copy to resumes directory
        RESUMES_DIR.mkdir(parents=True, exist_ok=True)
        dest = RESUMES_DIR / f"{job['id']}.pdf"
        shutil.copy2(str(compile_result.pdf_path), str(dest))

        update(f"Resume saved: {dest.name}")
        result["success"] = True
        result["pdf_path"] = str(dest)
        return result

    except Exception as e:
        result["error"] = f"Compilation error: {e}"
        return result
