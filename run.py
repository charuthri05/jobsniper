#!/usr/bin/env python3
"""
Job Application Pipeline — single CLI entry point.

Usage:
    python run.py setup      # interactive profile builder
    python run.py scrape     # run all scrapers
    python run.py score      # score all 'new' jobs
    python run.py generate   # generate docs for 'queued' jobs
    python run.py review     # interactive review queue
    python run.py all        # scrape + score + generate
    python run.py stats      # print application stats
    python run.py export     # export jobs.db to CSV
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from utils.db import init_db
from utils.profile import (
    PROFILE_PATH, PREFERENCES_PATH,
    save_profile, load_profile, validate_profile,
    load_preferences, save_preferences,
)


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------

def cmd_setup(args):
    """Interactive profile builder. Fully generic — no pre-filled personal data."""
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    console.print(Panel("[bold cyan]Job Application Pipeline — Profile Setup[/bold cyan]"))

    # ------------------------------------------------------------------
    # Step 1: Guided .env creation (before anything else)
    # ------------------------------------------------------------------
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        console.print(Panel("[bold cyan]Step 1: API Configuration[/bold cyan]"))
        console.print(
            "This pipeline uses AI to score jobs and generate cover letters.\n"
            "Choose your AI provider:\n"
        )
        console.print("  [bold][1][/bold] OpenAI  (recommended — cheapest with GPT-4o-mini, ~$0.02 per 100 jobs)")
        console.print("  [bold][2][/bold] Anthropic (Claude — higher quality, ~$1 per 100 jobs)\n")

        provider_choice = ""
        while provider_choice not in ("1", "2"):
            provider_choice = input("> ").strip()
            if provider_choice not in ("1", "2"):
                console.print("[red]Please enter 1 or 2.[/red]")

        env_lines = []

        if provider_choice == "1":
            # OpenAI
            env_lines.append("AI_PROVIDER=openai")
            console.print("\n[bold green]OpenAI selected.[/bold green]")
            console.print("Get your API key at: [link=https://platform.openai.com/api-keys]https://platform.openai.com/api-keys[/link]")
            console.print("Sign up is free. You get $5 in free credits.\n")
            api_key = ""
            while not api_key:
                api_key = input("Enter your OpenAI API key (starts with sk-): ").strip()
                if not api_key:
                    console.print("[red]API key is required.[/red]")
            env_lines.append(f"OPENAI_API_KEY={api_key}")
            env_lines.append("AI_MODEL=gpt-4o-mini")
        else:
            # Anthropic
            env_lines.append("AI_PROVIDER=anthropic")
            console.print("\n[bold green]Anthropic selected.[/bold green]")
            console.print("Get your API key at: [link=https://console.anthropic.com/settings/keys]https://console.anthropic.com/settings/keys[/link]")
            console.print("Sign up is free. You get $5 in free credits.\n")
            api_key = ""
            while not api_key:
                api_key = input("Enter your Anthropic API key (starts with sk-ant-): ").strip()
                if not api_key:
                    console.print("[red]API key is required.[/red]")
            env_lines.append(f"ANTHROPIC_API_KEY={api_key}")
            env_lines.append("AI_MODEL=claude-sonnet-4-5")

        # LinkedIn session cookie (optional)
        console.print("\n[bold green]LinkedIn Session Cookie[/bold green] (optional — adds LinkedIn as a job source)\n")
        console.print("To get your LinkedIn cookie:")
        console.print("  1. Log into linkedin.com in Chrome")
        console.print("  2. Press F12 -> Application tab -> Cookies -> www.linkedin.com")
        console.print("  3. Find 'li_at' and copy its value")
        console.print()
        linkedin_cookie = input("Enter LinkedIn cookie (or press Enter to skip): ").strip()
        if linkedin_cookie:
            env_lines.append(f"LINKEDIN_SESSION_COOKIE={linkedin_cookie}")

        env_lines.append("SCORE_THRESHOLD=72")
        env_lines.append("EDITOR=code")

        env_path.write_text("\n".join(env_lines) + "\n")
        load_dotenv(env_path, override=True)
        console.print(f"\n[green].env file created at {env_path}[/green]\n")
    else:
        console.print("[green].env found[/green]\n")

    if PROFILE_PATH.exists():
        console.print(f"[yellow]Existing profile found at {PROFILE_PATH}[/yellow]")
        resp = input("Overwrite? [y/N] ").strip().lower()
        if resp != "y":
            console.print("Setup cancelled.")
            return

    console.print("\n[bold]Let's build your candidate profile.[/bold]")
    console.print("[dim]Fields marked with * are required.[/dim]\n")

    def ask(prompt, default="", required=False):
        """Prompt user with an optional default value."""
        marker = "*" if required else ""
        while True:
            if default:
                val = input(f"  {marker}{prompt} [{default}]: ").strip()
                return val if val else default
            val = input(f"  {marker}{prompt}: ").strip()
            if val or not required:
                return val
            console.print("    [red]This field is required.[/red]")

    def ask_list(prompt, defaults=None):
        """Prompt for a comma-separated list with optional defaults."""
        default_str = ", ".join(defaults) if defaults else ""
        if default_str:
            raw = input(f"  {prompt} [{default_str}]: ").strip()
        else:
            raw = input(f"  {prompt}: ").strip()
        if not raw and defaults:
            return defaults
        return [s.strip() for s in raw.split(",") if s.strip()]

    def ask_int(prompt, default=0):
        """Prompt for an integer with a default."""
        val = input(f"  {prompt} [{default}]: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            console.print(f"    [yellow]Invalid number, using {default}[/yellow]")
            return default

    # --- Basic info ---
    console.print("[bold green]Basic Information[/bold green]")
    name = ask("Full name", required=True)
    email = ask("Email", required=True)
    phone = ask("Phone", required=True)
    location = ask("Current location (city, state)", required=True)
    linkedin = ask("LinkedIn URL")
    github = ask("GitHub URL")

    # --- Professional ---
    console.print("\n[bold green]Professional Summary[/bold green]")
    console.print("  [dim]Write a 2-3 sentence summary of your background.[/dim]")
    summary = ask("Summary", required=True)

    yoe = ask_int("Years of experience", 0)
    current_title = ask("Current/most recent title", "Software Engineer")

    target_titles = ask_list(
        "Target job titles (comma-separated)",
        ["Software Engineer", "Full Stack Engineer", "Backend Engineer",
         "Frontend Engineer", "SWE II", "Senior Software Engineer"],
    )

    # --- Skills ---
    console.print("\n[bold green]Skills[/bold green]")
    console.print("  [dim]Enter comma-separated lists. Press Enter to accept defaults.[/dim]")
    languages = ask_list("Programming languages")
    frameworks = ask_list("Frameworks / libraries")
    infrastructure = ask_list("Infrastructure / Cloud")
    databases = ask_list("Databases")
    other_skills = ask_list("Other skills (e.g. system design, REST APIs)")

    # --- Experience ---
    console.print("\n[bold green]Experience[/bold green]")
    console.print("  [dim]Add your work experience. Type 'done' when finished.[/dim]\n")

    experience = []
    exp_index = 1
    while True:
        console.print(f"  [bold]Experience #{exp_index}[/bold]")
        title = ask("  Job title", required=(exp_index == 1))
        if not title:
            break
        company = ask("  Company", required=True)
        start = ask("  Start date (YYYY-MM)", required=True)
        end = ask("  End date (YYYY-MM or 'present')", "present")

        console.print("  [dim]  Enter bullet points one per line. Empty line to finish this entry.[/dim]")
        bullets = []
        while True:
            bullet = input("    - ").strip()
            if not bullet:
                break
            bullets.append(bullet)

        if not bullets:
            console.print("    [yellow]At least one bullet is recommended.[/yellow]")
            bullet = ask("    One-line description of what you did", required=True)
            if bullet:
                bullets.append(bullet)

        experience.append({
            "title": title,
            "company": company,
            "start": start,
            "end": end,
            "bullets": bullets,
        })

        exp_index += 1
        more = input("\n  Add another experience? [y/N] ").strip().lower()
        if more != "y":
            break

    if not experience:
        console.print("  [red]At least one experience entry is required.[/red]")
        return

    # --- Education ---
    console.print("\n[bold green]Education[/bold green]")
    education = []
    edu_index = 1
    while True:
        console.print(f"  [bold]Education #{edu_index}[/bold]")
        degree = ask("  Degree (e.g. B.S. Computer Science)", required=(edu_index == 1))
        if not degree:
            break
        school = ask("  School", required=True)
        year = ask_int("  Graduation year", 2024)
        education.append({"degree": degree, "school": school, "year": year})

        edu_index += 1
        more = input("\n  Add another? [y/N] ").strip().lower()
        if more != "y":
            break

    if not education:
        console.print("  [red]At least one education entry is required.[/red]")
        return

    # --- Raw resume text ---
    console.print("\n[bold green]Resume Text[/bold green]")

    # Option 1: parse from PDF
    console.print("  [dim]You can import your resume from a PDF file, paste it as text, or auto-generate from the info above.[/dim]")
    pdf_path = input("  Do you have a resume PDF? Enter path or press Enter to skip: ").strip()

    raw_resume_text = None
    if pdf_path:
        from utils.resume_parser import parse_resume_pdf
        try:
            raw_resume_text = parse_resume_pdf(pdf_path)
            console.print(f"  [green]Successfully extracted text from PDF ({len(raw_resume_text)} chars).[/green]")
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"  [red]PDF parsing failed: {exc}[/red]")
            console.print("  [yellow]Falling back to manual entry.[/yellow]")

    # Option 2: manual paste (only if PDF was not used)
    if raw_resume_text is None:
        console.print("  [dim]Paste your full resume as plain text, or just press Enter to auto-generate from the info above.[/dim]")
        console.print("  [dim]To paste multi-line text: paste and then press Enter twice.[/dim]")

        raw_lines = []
        first_line = input("  Resume text (or Enter to skip): ").strip()
        if first_line:
            raw_lines.append(first_line)
            while True:
                line = input("  ").strip()
                if not line:
                    break
                raw_lines.append(line)

        if raw_lines:
            raw_resume_text = "\n".join(raw_lines)

    # Option 3: auto-generate from structured data (fallback)
    if raw_resume_text is None:
        # Auto-generate from structured data
        raw_resume_text = f"{name} | {email} | {phone}\n"
        if linkedin:
            raw_resume_text += f"{linkedin}\n"
        if github:
            raw_resume_text += f"{github}\n"
        raw_resume_text += f"\nSummary: {summary}\n\nExperience:\n"
        for exp in experience:
            raw_resume_text += f"\n{exp['title']} at {exp['company']} ({exp['start']} – {exp['end']})\n"
            for b in exp["bullets"]:
                raw_resume_text += f"  - {b}\n"
        raw_resume_text += "\nEducation:\n"
        for ed in education:
            raw_resume_text += f"  {ed['degree']} — {ed['school']} ({ed['year']})\n"
        if languages or frameworks or databases or infrastructure:
            raw_resume_text += "\nSkills:\n"
            if languages:
                raw_resume_text += f"  Languages: {', '.join(languages)}\n"
            if frameworks:
                raw_resume_text += f"  Frameworks: {', '.join(frameworks)}\n"
            if databases:
                raw_resume_text += f"  Databases: {', '.join(databases)}\n"
            if infrastructure:
                raw_resume_text += f"  Infrastructure: {', '.join(infrastructure)}\n"
            if other_skills:
                raw_resume_text += f"  Other: {', '.join(other_skills)}\n"
        console.print("  [green]Resume text auto-generated from your entries.[/green]")

    # --- Assemble profile ---
    profile = {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
        "linkedin": linkedin,
        "github": github,
        "summary": summary,
        "years_of_experience": yoe,
        "current_title": current_title,
        "target_titles": target_titles,
        "skills": {
            "languages": languages,
            "frameworks": frameworks,
            "infrastructure": infrastructure,
            "databases": databases,
            "other": other_skills,
        },
        "experience": experience,
        "education": education,
        "raw_resume_text": raw_resume_text,
    }

    try:
        validate_profile(profile)
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        console.print("Please re-run setup and fill in all required fields.")
        return

    save_profile(profile)
    console.print(f"\n[green]Profile saved to {PROFILE_PATH}[/green]")

    # --- Preferences ---
    console.print(Panel("[bold cyan]Job Search Preferences[/bold cyan]"))

    prefs = load_preferences()

    # Pre-filled target roles
    console.print("  Target roles: " + ", ".join(prefs["target_roles"]))
    resp = input("  Update target roles? [y/N] ").strip().lower()
    if resp == "y":
        prefs["target_roles"] = ask_list("Target roles (comma-separated)", prefs["target_roles"])

    # Locations
    console.print("  [dim]Leave empty for all US locations, or enter specific cities.[/dim]")
    locations = ask_list("Target locations (comma-separated, or Enter for all US)", prefs.get("locations", []))
    prefs["locations"] = locations

    # Remote
    remote_resp = input("  Remote only? [y/N] ").strip().lower()
    prefs["remote_only"] = (remote_resp == "y")

    # Salary
    prefs["min_salary"] = ask_int("Minimum salary ($)", prefs.get("min_salary", 0))

    # Seniority
    console.print("  [dim]Seniority levels: intern, entry-level, mid, senior, staff, principal[/dim]")
    prefs["seniority_levels"] = ask_list(
        "Target seniority levels",
        prefs.get("seniority_levels", ["entry-level", "mid", "senior"]),
    )

    # Visa
    visa_resp = input("  Do you need visa sponsorship (H1B)? [y/N] ").strip().lower()
    prefs["visa_sponsorship_required"] = (visa_resp == "y")

    # Blacklist
    blacklist = ask_list("Companies to blacklist (comma-separated)", prefs.get("blacklist_companies", []))
    prefs["blacklist_companies"] = blacklist

    # Greenhouse/Lever boards are pre-filled — just show count
    console.print(f"\n  [dim]Pre-configured: {len(prefs.get('greenhouse_boards', []))} Greenhouse boards + {len(prefs.get('lever_boards', []))} Lever boards[/dim]")
    console.print(f"  [dim]Edit data/preferences.json to add/remove specific company boards.[/dim]")

    save_preferences(prefs)
    console.print(f"[green]Preferences saved to {PREFERENCES_PATH}[/green]")

    # --- Init DB ---
    init_db()
    console.print(f"[green]Database initialized.[/green]")
    console.print("\n[bold green]Setup complete! Run 'python run.py scrape' to start finding jobs.[/bold green]")


# ---------------------------------------------------------------------------
# scrape command
# ---------------------------------------------------------------------------

def cmd_scrape(args):
    """Run all scrapers and normalize results into jobs.db."""
    from rich.console import Console
    console = Console()

    init_db()
    prefs = load_preferences()

    console.print("[bold cyan]Running all scrapers...[/bold cyan]")

    from pipeline.normalizer import run_all_scrapers
    stats = run_all_scrapers(prefs)

    console.print(f"\n[bold green]Scrape complete. {stats['new']} new jobs added.[/bold green]")


# ---------------------------------------------------------------------------
# score command
# ---------------------------------------------------------------------------

def cmd_score(args):
    """Score all 'new' jobs using hard filters + Claude API."""
    from rich.console import Console
    console = Console()

    init_db()
    profile = load_profile()
    prefs = load_preferences()

    console.print("[bold cyan]Scoring new jobs...[/bold cyan]")

    from pipeline.scorer import score_all_new_jobs
    stats = score_all_new_jobs(profile, prefs)


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

def cmd_generate(args):
    """Generate cover letters and resume bullets for queued jobs."""
    from rich.console import Console
    console = Console()

    init_db()
    profile = load_profile()

    console.print("[bold cyan]Generating cover letters and resume bullets...[/bold cyan]")

    from pipeline.generator import generate_for_queued_jobs
    stats = generate_for_queued_jobs(profile)


# ---------------------------------------------------------------------------
# review command
# ---------------------------------------------------------------------------

def cmd_review(args):
    """Launch the interactive review queue."""
    init_db()

    from review.cli import review_queue
    review_queue()


# ---------------------------------------------------------------------------
# all command
# ---------------------------------------------------------------------------

def cmd_all(args):
    """Run the full pipeline: scrape + score + generate."""
    from rich.console import Console
    console = Console()

    console.print("[bold cyan]Running full pipeline...[/bold cyan]\n")

    init_db()
    prefs = load_preferences()
    profile = load_profile()

    # Step 1: Scrape
    console.print("[bold]Step 1/3: Scraping[/bold]")
    from pipeline.normalizer import run_all_scrapers
    scrape_stats = run_all_scrapers(prefs)

    # Step 2: Score
    console.print("\n[bold]Step 2/3: Scoring[/bold]")
    from pipeline.scorer import score_all_new_jobs
    score_stats = score_all_new_jobs(profile, prefs)

    # Step 3: Generate
    console.print("\n[bold]Step 3/3: Generating[/bold]")
    from pipeline.generator import generate_for_queued_jobs
    gen_stats = generate_for_queued_jobs(profile)

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]Pipeline complete![/bold green]")
    console.print(f"  Scraped: {scrape_stats.get('new', 0)} new jobs")
    console.print(f"  Scored:  {score_stats.get('queued', 0)} queued / {score_stats.get('total', 0)} total")
    console.print(f"  Generated: {gen_stats.get('generated', 0)} cover letters")
    console.print(f"\nRun [bold]python run.py review[/bold] to review and submit.")


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

def cmd_stats(args):
    """Print application statistics."""
    from rich.console import Console
    from utils.db import count_by_status, count_today, count_this_week

    console = Console()
    init_db()

    status_counts = count_by_status()
    today_scraped = count_today()
    today_submitted = count_today("submitted")
    today_queued = count_today("queued")

    week_submitted = count_this_week("submitted")
    week_total = count_this_week()

    all_submitted = status_counts.get("submitted", 0)
    all_approved = status_counts.get("approved", 0)
    queued = status_counts.get("queued", 0)

    total_applied = all_submitted + all_approved
    week_applied = week_submitted

    console.print("\n[bold cyan]Job Application Pipeline — Stats[/bold cyan]\n")
    console.print(f"Today:      {today_scraped} new jobs scraped  |  {today_queued} passed filter  |  {today_submitted} submitted")
    console.print(f"This week:  {week_applied} applied  ·  {week_total} total scraped")
    console.print(f"All time:   {total_applied} applied")
    console.print(f"Queue:      {queued} jobs awaiting review")

    if status_counts:
        console.print(f"\n[dim]Status breakdown: {dict(status_counts)}[/dim]")


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------

def cmd_export(args):
    """Export jobs.db to CSV."""
    from rich.console import Console
    from utils.db import export_to_csv

    console = Console()
    init_db()

    output_path = PROJECT_ROOT / "data" / "jobs_export.csv"
    count = export_to_csv(str(output_path))

    if count:
        console.print(f"[green]Exported {count} jobs to {output_path}[/green]")
    else:
        console.print("[yellow]No jobs to export.[/yellow]")


# ---------------------------------------------------------------------------
# dashboard command
# ---------------------------------------------------------------------------

def cmd_dashboard(args):
    """Launch the web-based job dashboard."""
    init_db()
    from web.app import run_dashboard
    run_dashboard()


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def main():
    """Parse arguments and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(
        description="Job Application Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("setup", help="Interactive profile builder")
    subparsers.add_parser("scrape", help="Run all scrapers")
    subparsers.add_parser("score", help="Score all new jobs")
    subparsers.add_parser("generate", help="Generate cover letters and resume bullets")
    subparsers.add_parser("review", help="Interactive review queue")
    subparsers.add_parser("all", help="Run scrape + score + generate")
    subparsers.add_parser("stats", help="Print application statistics")
    subparsers.add_parser("export", help="Export jobs.db to CSV")
    subparsers.add_parser("dashboard", help="Web-based job dashboard")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "setup": cmd_setup,
        "scrape": cmd_scrape,
        "score": cmd_score,
        "generate": cmd_generate,
        "review": cmd_review,
        "all": cmd_all,
        "stats": cmd_stats,
        "export": cmd_export,
        "dashboard": cmd_dashboard,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
