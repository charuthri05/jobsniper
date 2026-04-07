"""
Interactive terminal review queue.

The candidate's daily driver — presents queued jobs one at a time
with cover letter previews and keyboard actions.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from utils.db import get_jobs_by_status, update_job, insert_application


console = Console()


def _format_salary(job: dict) -> str:
    """Format salary range for display."""
    sal_min = job.get("salary_min")
    sal_max = job.get("salary_max")
    if sal_min and sal_max:
        return f"${sal_min:,} – ${sal_max:,}"
    elif sal_min:
        return f"${sal_min:,}+"
    elif sal_max:
        return f"Up to ${sal_max:,}"
    return ""


def _get_strengths_and_missing(job: dict) -> tuple[list, list]:
    """Extract strengths and missing from job notes."""
    try:
        notes = json.loads(job.get("notes") or "{}")
        return notes.get("strengths", []), notes.get("missing", [])
    except (json.JSONDecodeError, TypeError):
        return [], []


def _preview_cover_letter(cover_letter: str, lines: int = 4) -> str:
    """Return the first N lines of the cover letter."""
    if not cover_letter:
        return "(no cover letter generated)"
    return "\n".join(cover_letter.strip().split("\n")[:lines])


def _edit_cover_letter(cover_letter: str) -> str:
    """Open cover letter in $EDITOR, return edited text."""
    editor = os.getenv("EDITOR", "nano")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="cover_letter_", delete=False
    ) as f:
        f.write(cover_letter)
        tmppath = f.name

    try:
        subprocess.call([editor, tmppath])
        with open(tmppath, "r") as f:
            return f.read()
    finally:
        os.unlink(tmppath)


def _view_with_pager(text: str, title: str = "") -> None:
    """Display text using less or a simple pager."""
    if title:
        text = f"{'=' * 60}\n{title}\n{'=' * 60}\n\n{text}"

    try:
        proc = subprocess.Popen(
            ["less", "-R"],
            stdin=subprocess.PIPE,
            encoding="utf-8",
        )
        proc.communicate(input=text)
    except FileNotFoundError:
        # Fallback: just print it
        console.print(text)
        input("\nPress Enter to continue...")


def display_job(job: dict, index: int, total: int) -> None:
    """Display a single job in the review format."""
    strengths, missing = _get_strengths_and_missing(job)
    salary = _format_salary(job)

    # Header
    console.print("\n" + "─" * 60)

    title_line = f"[{index}/{total}]  [bold]{job['title']}[/bold] — {job['company']}"
    console.print(title_line)

    # Location and details
    details = []
    if job.get("location"):
        details.append(job["location"])
    if salary:
        details.append(salary)
    if details:
        console.print(f"       {' · '.join(details)}")

    # Score
    score = job.get("score", 0)
    score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    score_label = "strong fit" if score >= 80 else "decent fit" if score >= 60 else "weak fit"
    console.print(f"       Score: [{score_color}]{score}/100[/{score_color}]  |  {score_label}")

    # Reason
    if job.get("score_reason"):
        console.print(f"       Why: {job['score_reason']}")

    # Missing skills
    if missing:
        console.print(f"       Missing: {', '.join(missing)}")

    # Cover letter preview
    cover_letter = job.get("cover_letter", "")
    preview = _preview_cover_letter(cover_letter)

    console.print()
    console.print(Panel(
        preview,
        title="COVER LETTER PREVIEW",
        border_style="dim",
        width=60,
    ))

    # Resume bullets
    bullets_raw = job.get("resume_bullets")
    if bullets_raw:
        try:
            bullets = json.loads(bullets_raw)
            console.print("\n  [bold]TAILORED BULLETS:[/bold]")
            for b in bullets:
                console.print(f"  [dim]•[/dim] {b}")
        except (json.JSONDecodeError, TypeError):
            pass

    console.print()


def review_queue() -> dict:
    """
    Run the interactive review queue.
    Returns session stats: {submitted, skipped, remaining, edited}
    """
    jobs = get_jobs_by_status("queued")

    if not jobs:
        console.print("[yellow]No jobs in the review queue.[/yellow]")
        console.print("Run 'python run.py scrape && python run.py score && python run.py generate' first.")
        return {"submitted": 0, "skipped": 0, "remaining": 0, "edited": 0}

    # Only show jobs that have cover letters generated
    ready_jobs = [j for j in jobs if j.get("cover_letter")]
    if not ready_jobs:
        console.print("[yellow]Queued jobs exist but none have cover letters yet.[/yellow]")
        console.print("Run 'python run.py generate' first.")
        return {"submitted": 0, "skipped": 0, "remaining": len(jobs), "edited": 0}

    console.print(Panel(
        f"[bold cyan]Review Queue — {len(ready_jobs)} jobs to review[/bold cyan]"
    ))

    stats = {"submitted": 0, "skipped": 0, "remaining": len(ready_jobs), "edited": 0}

    try:
        for i, job in enumerate(ready_jobs, 1):
            display_job(job, i, len(ready_jobs))

            while True:
                console.print(
                    "  [bold][a][/bold] approve + submit   "
                    "[bold][e][/bold] edit   "
                    "[bold][r][/bold] read full JD   "
                    "[bold][v][/bold] view full letter   "
                    "[bold][s][/bold] skip"
                )
                try:
                    action = input("❯ ").strip().lower()
                except EOFError:
                    action = "s"

                if action == "a":
                    # Approve and submit
                    console.print(f"  [green]Approved![/green] Submitting {job['title']} at {job['company']}...")
                    try:
                        from pipeline.submitter import submit_application
                        result = submit_application(job)
                        update_job(
                            job["id"],
                            status="submitted",
                            date_submitted=datetime.now(timezone.utc).isoformat(),
                        )
                        insert_application(job["id"], confirmation_text=result.get("confirmation", ""))
                        console.print(f"  [bold green]Submitted successfully![/bold green]")
                        stats["submitted"] += 1
                    except Exception as e:
                        console.print(f"  [red]Submission failed: {e}[/red]")
                        console.print("  Marking as approved — you can submit manually.")
                        update_job(job["id"], status="approved")
                        stats["submitted"] += 1
                    stats["remaining"] -= 1
                    break

                elif action == "e":
                    # Edit cover letter
                    edited = _edit_cover_letter(job.get("cover_letter", ""))
                    update_job(job["id"], cover_letter=edited)
                    job["cover_letter"] = edited
                    stats["edited"] += 1
                    console.print("  [cyan]Cover letter updated.[/cyan]")

                    submit_now = input("  Submit now? [y/N] ").strip().lower()
                    if submit_now == "y":
                        try:
                            from pipeline.submitter import submit_application
                            result = submit_application(job)
                            update_job(
                                job["id"],
                                status="submitted",
                                date_submitted=datetime.now(timezone.utc).isoformat(),
                            )
                            insert_application(job["id"], confirmation_text=result.get("confirmation", ""))
                            console.print(f"  [bold green]Submitted![/bold green]")
                            stats["submitted"] += 1
                        except Exception as e:
                            console.print(f"  [red]Submission failed: {e}[/red]")
                            update_job(job["id"], status="approved")
                            stats["submitted"] += 1
                        stats["remaining"] -= 1
                        break
                    else:
                        # Show the job again with updated letter
                        display_job(job, i, len(ready_jobs))
                        continue

                elif action == "r":
                    # Read full job description
                    _view_with_pager(
                        job.get("description") or "No description available.",
                        f"{job['title']} at {job['company']}"
                    )
                    display_job(job, i, len(ready_jobs))
                    continue

                elif action == "v":
                    # View full cover letter
                    _view_with_pager(
                        job.get("cover_letter") or "No cover letter.",
                        f"Cover Letter — {job['title']} at {job['company']}"
                    )
                    continue

                elif action == "s":
                    # Skip
                    update_job(job["id"], status="skipped")
                    console.print(f"  [dim]Skipped.[/dim]")
                    stats["skipped"] += 1
                    stats["remaining"] -= 1
                    break

                else:
                    console.print("  [yellow]Invalid input. Use a/e/r/v/s[/yellow]")

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Review interrupted. Progress saved.[/yellow]")

    # Session summary
    console.print("\n" + "─" * 60)
    console.print("[bold]Session Summary:[/bold]")
    console.print(f"  [green]{stats['submitted']} submitted[/green]  ·  "
                  f"[dim]{stats['skipped']} skipped[/dim]  ·  "
                  f"{stats['remaining']} remaining  ·  "
                  f"{stats['edited']} edited")
    console.print("─" * 60)

    return stats
