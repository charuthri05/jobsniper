"""
Merge and deduplicate all scraped job sources into jobs.db.

All scrapers return different schemas. This module normalizes everything
and inserts into the database, skipping duplicates by URL.
"""

import hashlib
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from html import unescape

from utils.db import init_db, insert_jobs, get_existing_urls


def _make_id(url: str) -> str:
    """Generate a deterministic 16-char hex ID from the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _strip_html(text: str | None) -> str:
    """Remove HTML tags and decode entities from text."""
    if not text:
        return ""
    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        return unescape(soup.get_text(separator="\n", strip=True))
    return text.strip()


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# Title keywords that indicate a software engineering role — applied before DB insert
# to avoid storing thousands of irrelevant jobs (PM, marketing, design, HR, etc.)
_TITLE_KEYWORDS = {
    "software", "engineer", "developer", "swe", "backend", "frontend",
    "full stack", "fullstack", "full-stack", "web developer",
    "application developer", "platform engineer", "devops", "sre",
    "site reliability", "systems engineer", "infrastructure engineer",
    "data engineer", "ml engineer", "machine learning engineer",
}


def _title_is_relevant(title: str) -> bool:
    """Check if a job title matches any engineering role keyword."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in _TITLE_KEYWORDS)


def normalize_and_insert(raw_jobs: list[dict]) -> dict:
    """
    Normalize a list of raw job dicts and insert into jobs.db.

    Steps:
    1. Ensure each job has the required fields
    2. Title pre-filter — drop non-engineering roles before touching DB
    3. Batch URL dedup — one query instead of N
    4. Generate ID from URL if missing
    5. Strip HTML from descriptions
    6. Insert new jobs

    Returns stats dict: {total, new, duplicates, invalid, title_filtered}
    """
    init_db()

    stats = {"total": len(raw_jobs), "new": 0, "duplicates": 0, "invalid": 0, "title_filtered": 0}

    # Load all existing URLs in one query for O(1) dedup lookups
    existing_urls = get_existing_urls()
    to_insert = []

    for raw in raw_jobs:
        url = raw.get("url")
        if not url:
            stats["invalid"] += 1
            continue

        title = raw.get("title")
        company = raw.get("company")
        if not title or not company:
            stats["invalid"] += 1
            continue

        # Title pre-filter: drop non-engineering roles early
        if not _title_is_relevant(title):
            stats["title_filtered"] += 1
            continue

        # Batch dedup: check against in-memory set instead of per-job DB query
        if url in existing_urls:
            stats["duplicates"] += 1
            continue

        # Track URL to dedup within this batch too
        existing_urls.add(url)

        # Normalize fields
        job = {
            "id": raw.get("id") or _make_id(url),
            "title": title.strip(),
            "company": company.strip(),
            "location": (raw.get("location") or "").strip() or None,
            "url": url,
            "source": raw.get("source", "unknown"),
            "description": _strip_html(raw.get("description")),
            "salary_min": raw.get("salary_min"),
            "salary_max": raw.get("salary_max"),
            "date_posted": raw.get("date_posted"),
            "date_scraped": raw.get("date_scraped") or _now_iso(),
            "status": "new",
        }

        to_insert.append(job)

    # Bulk insert
    if to_insert:
        inserted = insert_jobs(to_insert)
        stats["new"] = inserted
        # Some may have been caught by DB-level dedup
        stats["duplicates"] += len(to_insert) - inserted

    return stats


def run_all_scrapers(preferences: dict) -> dict:
    """
    Run all configured scrapers and normalize results into jobs.db.
    Returns combined stats.
    """
    from rich.console import Console
    console = Console()

    all_jobs = []

    # ATS scrapers (Greenhouse + Lever)
    console.print("\n[bold]Fetching from ATS boards...[/bold]")
    try:
        from scrapers.ats_scraper import fetch_all_ats_jobs
        ats_jobs = fetch_all_ats_jobs(preferences)
        all_jobs.extend(ats_jobs)
        console.print(f"  [green]ATS: {len(ats_jobs)} jobs fetched[/green]")
    except Exception as e:
        console.print(f"  [red]ATS scraper error: {e}[/red]")

    # Hiring Cafe scraper
    console.print("\n[bold]Fetching from Hiring Cafe...[/bold]")
    try:
        from scrapers.hiringcafe_scraper import fetch_hiringcafe_jobs
        hc_jobs = fetch_hiringcafe_jobs(preferences)
        all_jobs.extend(hc_jobs)
        console.print(f"  [green]Hiring Cafe: {len(hc_jobs)} jobs fetched[/green]")
    except Exception as e:
        console.print(f"  [red]Hiring Cafe scraper error: {e}[/red]")

    # JobSpy scrapers
    console.print("\n[bold]Fetching from job boards (JobSpy)...[/bold]")
    try:
        from scrapers.jobspy_scraper import scrape_major_boards
        jobspy_jobs = scrape_major_boards(preferences)
        all_jobs.extend(jobspy_jobs)
        console.print(f"  [green]JobSpy: {len(jobspy_jobs)} jobs fetched[/green]")
    except Exception as e:
        console.print(f"  [red]JobSpy scraper error: {e}[/red]")

    # Normalize and insert
    console.print(f"\n[bold]Normalizing {len(all_jobs)} total jobs...[/bold]")
    stats = normalize_and_insert(all_jobs)

    console.print(f"\n[bold]Scrape results:[/bold]")
    console.print(f"  Total fetched: {stats['total']}")
    console.print(f"  [dim]Non-engineering filtered: {stats.get('title_filtered', 0)}[/dim]")
    console.print(f"  Duplicates skipped: {stats['duplicates']}")
    console.print(f"  [green]New jobs added: {stats['new']}[/green]")
    if stats["invalid"] > 0:
        console.print(f"  [yellow]Invalid entries: {stats['invalid']}[/yellow]")

    return stats
