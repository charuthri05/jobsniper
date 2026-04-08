"""
Cover letter and resume bullet generation using the configured AI provider.

Only called for jobs with status='queued'.
Generates a tailored cover letter and 3 resume bullets per job.
"""

import json
import re

from utils.ai_client import chat_completion
from utils.db import get_jobs_by_status, update_job
from utils.profile import load_profile, get_all_bullets
from pipeline.resume_generator import generate_tailored_resume


COVER_LETTER_SYSTEM = """You are a professional cover letter writer for software engineers targeting big tech.
Write in first person. Be specific, not generic. Never use filler phrases like
"I am excited to apply" or "I am a passionate engineer."
Reference specific details from the job description. Keep it to 3 paragraphs, under 300 words.
Naturally weave in the provided ATS keywords where they fit truthfully — do not force or list them."""

RESUME_BULLET_SYSTEM = """You are a resume writer. Rewrite the candidate's existing bullet points to better match
a specific job description. Keep the facts 100% accurate — only adjust emphasis and language.
Naturally incorporate the provided ATS keywords where they fit truthfully.
Return a JSON array of exactly 3 bullet strings."""


def generate_cover_letter(job: dict, profile: dict) -> str:
    """
    Generate a tailored cover letter for a specific job.
    Returns the cover letter text.
    """
    # Parse strengths and keywords from notes if available
    strengths = []
    keywords = []
    try:
        notes = json.loads(job.get("notes") or "{}")
        strengths = notes.get("strengths", [])
        keywords = notes.get("keywords", [])
    except (json.JSONDecodeError, TypeError):
        pass

    user_message = f"""Write a cover letter for this application.

CANDIDATE:
{json.dumps({
    "name": profile["name"],
    "summary": profile["summary"],
    "years_of_experience": profile["years_of_experience"],
    "current_title": profile["current_title"],
    "skills": profile["skills"],
    "experience": [
        {"title": e["title"], "company": e["company"], "bullets": e["bullets"][:4]}
        for e in profile.get("experience", [])
    ],
}, indent=2)}

JOB:
Title: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
Why this role scored well: {job.get('score_reason', 'Strong match')}
Strengths matched: {', '.join(strengths) if strengths else 'General fit'}
Top ATS keywords to naturally incorporate: {', '.join(keywords) if keywords else 'N/A'}
Description: {(job.get('description') or '')[:3000]}

Output the cover letter text only. No subject line. No "Dear Hiring Manager" header."""

    return chat_completion(system=COVER_LETTER_SYSTEM, user_message=user_message, max_tokens=600)


def generate_resume_bullets(job: dict, profile: dict) -> list[str]:
    """
    Generate 3 tailored resume bullets for a specific job.
    Returns a list of 3 bullet strings.
    """
    all_bullets = get_all_bullets(profile)

    # Parse keywords from notes if available
    keywords = []
    try:
        notes = json.loads(job.get("notes") or "{}")
        keywords = notes.get("keywords", [])
    except (json.JSONDecodeError, TypeError):
        pass

    user_message = f"""Rewrite the top 3 most relevant bullets from this resume to match this job description.
Use the job's language and keywords where truthful. Each bullet must start with a strong
action verb and include a measurable impact where one exists.

CANDIDATE BULLETS:
{json.dumps(all_bullets, indent=2)}

Top ATS keywords to naturally incorporate: {', '.join(keywords) if keywords else 'N/A'}

JOB DESCRIPTION KEYWORDS AND REQUIREMENTS:
{(job.get('description') or '')[:3000]}

Return JSON array only: ["bullet 1", "bullet 2", "bullet 3"]"""

    raw_text = chat_completion(system=RESUME_BULLET_SYSTEM, user_message=user_message, max_tokens=400)

    # Extract JSON array even if wrapped in code fences
    json_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"Could not parse JSON array from response: {raw_text[:200]}")

    bullets = json.loads(json_match.group())

    if not isinstance(bullets, list) or len(bullets) < 1:
        raise ValueError(f"Expected a list of bullets, got: {bullets}")

    # Ensure exactly 3 bullets
    return bullets[:3]


def generate_for_queued_jobs(profile: dict | None = None) -> dict:
    """
    Generate cover letters and resume bullets for all 'queued' jobs.
    Returns stats: {total, generated, errors}
    """
    from rich.console import Console
    from rich.progress import Progress

    console = Console()

    if profile is None:
        profile = load_profile()

    jobs = get_jobs_by_status("queued")

    # Filter to only those without a cover letter yet
    jobs_needing_gen = [j for j in jobs if not j.get("cover_letter")]

    if not jobs_needing_gen:
        console.print("[yellow]No queued jobs need generation.[/yellow]")
        return {"total": 0, "generated": 0, "errors": 0}

    console.print(f"\n[bold]Generating docs for {len(jobs_needing_gen)} queued jobs[/bold]\n")

    stats = {"total": len(jobs_needing_gen), "generated": 0, "errors": 0}

    with Progress() as progress:
        task = progress.add_task("Generating...", total=len(jobs_needing_gen))

        for job in jobs_needing_gen:
            try:
                # Generate cover letter
                cover_letter = generate_cover_letter(job, profile)

                # Generate resume bullets
                bullets = generate_resume_bullets(job, profile)

                # Generate tailored resume PDF
                resume_path = None
                try:
                    resume_path = generate_tailored_resume(job, profile)
                    console.print(
                        f"  [green]Resume PDF[/green] saved: {resume_path}"
                    )
                except Exception as resume_err:
                    console.print(
                        f"  [yellow]Resume PDF failed[/yellow] for {job['title']}: {resume_err}"
                    )

                # Merge resume_path into existing notes
                existing_notes = {}
                try:
                    existing_notes = json.loads(job.get("notes") or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
                if resume_path:
                    existing_notes["resume_path"] = resume_path
                notes_json = json.dumps(existing_notes)

                # Save to database
                update_job(
                    job["id"],
                    cover_letter=cover_letter,
                    resume_bullets=json.dumps(bullets),
                    notes=notes_json,
                )

                stats["generated"] += 1
                console.print(
                    f"  [green]Generated[/green] {job['title']} at {job['company']}"
                )

            except Exception as e:
                stats["errors"] += 1
                console.print(
                    f"  [red]ERROR[/red] {job['title']} at {job['company']}: {e}"
                )

            progress.advance(task)

    console.print(f"\n[bold]Generation complete:[/bold]")
    console.print(f"  {stats['generated']} generated  |  {stats['errors']} errors")

    return stats
