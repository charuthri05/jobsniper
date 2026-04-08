"""
Tailored resume PDF generation for queued jobs.

Uses AI to rewrite the candidate's resume content for ATS optimization,
then renders a clean single-column PDF using fpdf2.
"""

import json
import os
import re
from pathlib import Path

from utils.ai_client import chat_completion
from utils.profile import load_profile

RESUMES_DIR = Path(__file__).resolve().parent.parent / "data" / "resumes"

RESUME_SYSTEM_PROMPT = (
    "You are an expert resume writer for ATS optimization. "
    "Rewrite the candidate's resume content to maximize keyword match with the target job. "
    "Keep all facts 100% accurate — only adjust emphasis, wording, and bullet ordering. "
    "Return valid JSON only."
)


def _build_user_prompt(job: dict, profile: dict, keywords: list[str]) -> str:
    """Build the user prompt for the AI resume-tailoring call."""
    profile_payload = {
        "name": profile.get("name", ""),
        "summary": profile.get("summary", ""),
        "experience": [
            {
                "company": e.get("company", ""),
                "title": e.get("title", ""),
                "start": e.get("start", ""),
                "end": e.get("end", "present"),
                "bullets": e.get("bullets", []),
            }
            for e in profile.get("experience", [])
        ],
        "education": profile.get("education", []),
        "skills": profile.get("skills", {}),
    }

    description = (job.get("description") or "")[:3000]

    return f"""Tailor this resume for the job below. Reorder bullets so most relevant appear first. Use the job's terminology where truthful.

TARGET KEYWORDS: {', '.join(keywords) if keywords else 'N/A'}

CANDIDATE PROFILE:
{json.dumps(profile_payload, indent=2)}

JOB:
Title: {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}
Description: {description}

Return JSON:
{{
  "summary": "<2-sentence tailored professional summary>",
  "experience": [
    {{"company": "...", "title": "...", "start": "...", "end": "...", "bullets": ["...", "..."]}}
  ],
  "skills_highlight": ["skill1", "skill2", "... top 12 most relevant"]
}}"""


def _tailor_with_ai(job: dict, profile: dict, keywords: list[str]) -> dict:
    """Call the AI to produce tailored resume content. Returns parsed JSON dict."""
    user_prompt = _build_user_prompt(job, profile, keywords)
    raw_text = chat_completion(
        system=RESUME_SYSTEM_PROMPT,
        user_message=user_prompt,
        max_tokens=1200,
    )

    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"Could not parse JSON from resume AI response: {raw_text[:200]}")

    result = json.loads(json_match.group())
    result.setdefault("summary", "")
    result.setdefault("experience", [])
    result.setdefault("skills_highlight", [])
    return result


def _register_fonts(pdf):
    """
    Try to register Arial TTF fonts for Unicode support.
    Falls back to fpdf2's built-in Helvetica if TTF files are not found.
    Returns the font family name to use.
    """
    # Candidate paths for Arial TTF across platforms
    arial_paths = {
        "regular": [
            "/System/Library/Fonts/Supplemental/Arial.ttf",              # macOS
            "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",         # Linux (msttcorefonts)
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # Linux fallback
            "C:\\Windows\\Fonts\\arial.ttf",                             # Windows
        ],
        "bold": [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",         # macOS
            "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",    # Linux
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",    # Linux fallback
            "C:\\Windows\\Fonts\\arialbd.ttf",                           # Windows
        ],
    }

    def _find_font(candidates):
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    regular = _find_font(arial_paths["regular"])
    bold = _find_font(arial_paths["bold"])

    if regular and bold:
        pdf.add_font("arial", "", regular, uni=True)
        pdf.add_font("arial", "B", bold, uni=True)
        return "arial"

    # Fallback: use fpdf2 built-in Helvetica (no TTF registration needed)
    return "Helvetica"


def _generate_pdf(tailored: dict, profile: dict, job: dict, output_path: str):
    """Render the tailored resume content into a single-column ATS-safe PDF."""
    import io
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    font_family = _register_fonts(pdf)
    pdf.add_page()

    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    # ── 1. Name (bold 16pt, centered) ──
    pdf.set_font(font_family, "B", 16)
    pdf.cell(0, 10, profile.get("name", ""), new_x="LMARGIN", new_y="NEXT", align="C")

    # ── 2. Contact line (9pt, centered) ──
    pdf.set_font(font_family, "", 9)
    pdf.set_text_color(80, 80, 80)
    contact_parts = [
        profile.get("email", ""),
        profile.get("phone", ""),
        profile.get("location", ""),
    ]
    contact_line = "  |  ".join(p for p in contact_parts if p)
    if contact_line:
        pdf.cell(0, 5, contact_line, new_x="LMARGIN", new_y="NEXT", align="C")

    # ── 3. LinkedIn | GitHub (9pt, centered) ──
    links = [profile.get("linkedin", ""), profile.get("github", "")]
    links_str = "  |  ".join(l for l in links if l)
    if links_str:
        pdf.cell(0, 5, links_str, new_x="LMARGIN", new_y="NEXT", align="C")

    # ── 4. Horizontal line ──
    pdf.ln(4)
    pdf.set_draw_color(180, 180, 180)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(4)

    # Helper: section heading
    def section_heading(title):
        pdf.set_font(font_family, "B", 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, title.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        y_line = pdf.get_y()
        pdf.line(pdf.l_margin, y_line, pdf.w - pdf.r_margin, y_line)
        pdf.ln(3)

    # ── 5. SUMMARY ──
    section_heading("Summary")
    pdf.set_font(font_family, "", 10)
    pdf.set_text_color(30, 30, 30)
    summary_text = tailored.get("summary", profile.get("summary", ""))
    if summary_text:
        pdf.multi_cell(0, 5, summary_text)
        pdf.ln(4)

    # ── 6. EXPERIENCE ──
    section_heading("Experience")
    for exp in tailored.get("experience", []):
        title_str = f"{exp.get('title', '')}  |  {exp.get('company', '')}"
        dates_str = f"{exp.get('start', '')} - {exp.get('end', 'present')}"

        # Title (bold) left, dates right on same line
        pdf.set_font(font_family, "B", 10)
        pdf.set_text_color(0, 0, 0)
        title_w = pdf.get_string_width(title_str)
        dates_w = pdf.get_string_width(dates_str)

        # Print title on the left
        pdf.cell(effective_width - dates_w - 2, 6, title_str)
        # Print dates right-aligned
        pdf.set_font(font_family, "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(dates_w + 2, 6, dates_str, new_x="LMARGIN", new_y="NEXT", align="R")

        # Bullets
        pdf.set_font(font_family, "", 10)
        pdf.set_text_color(30, 30, 30)
        for bullet in exp.get("bullets", []):
            bullet_text = f"\u2022  {bullet}"
            x_before = pdf.get_x()
            pdf.set_x(x_before + 4)
            pdf.multi_cell(effective_width - 4, 5, bullet_text)
            pdf.ln(1)
        pdf.ln(2)

    # ── 7. EDUCATION ──
    section_heading("Education")
    pdf.set_font(font_family, "", 10)
    pdf.set_text_color(30, 30, 30)
    for edu in profile.get("education", []):
        degree = edu.get("degree", "")
        school = edu.get("school", "")
        year = edu.get("year", "")
        edu_line = f"{degree} -- {school} ({year})" if year else f"{degree} -- {school}"
        pdf.cell(0, 6, edu_line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── 8. SKILLS ──
    section_heading("Skills")
    pdf.set_font(font_family, "", 10)
    pdf.set_text_color(30, 30, 30)
    skills_list = tailored.get("skills_highlight", [])
    if skills_list:
        skills_text = ", ".join(skills_list)
        pdf.multi_cell(0, 5, skills_text)

    # Save
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    pdf.output(output_path)


def generate_tailored_resume(job: dict, profile: dict) -> str:
    """
    Generate a tailored resume PDF for a job. Returns the file path.

    Steps:
    1. Extract keywords from job notes
    2. Call AI to tailor resume content
    3. Render PDF
    """
    # Extract keywords from notes
    keywords = []
    try:
        notes = json.loads(job.get("notes") or "{}")
        keywords = notes.get("keywords", [])
    except (json.JSONDecodeError, TypeError):
        pass

    # AI call to tailor the resume
    tailored = _tailor_with_ai(job, profile, keywords)

    # Generate PDF
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = str(RESUMES_DIR / f"{job['id']}.pdf")
    _generate_pdf(tailored, profile, job, output_path)

    return output_path
