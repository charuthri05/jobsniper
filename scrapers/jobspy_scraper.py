"""
JobSpy wrapper for scraping LinkedIn, Indeed, Glassdoor, ZipRecruiter, and Google Jobs.

Uses the python-jobspy library which returns a pandas DataFrame.
"""

import hashlib
import math
from datetime import datetime, timezone

import pandas as pd


def _make_id(url: str) -> str:
    """Generate a deterministic job ID from the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _safe_str(val) -> str | None:
    """Safely convert a pandas value to string, handling NaN/None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return str(val).strip() if val else None


def _safe_int(val) -> int | None:
    """Safely convert a value to int, handling NaN/None."""
    if val is None:
        return None
    try:
        if isinstance(val, float) and math.isnan(val):
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


def normalize_jobspy_results(df: pd.DataFrame) -> list[dict]:
    """
    Convert a JobSpy DataFrame into a list of normalized job dicts
    matching the jobs.db schema.
    """
    jobs = []

    for _, row in df.iterrows():
        url = _safe_str(row.get("job_url") or row.get("link") or row.get("job_url_direct"))
        if not url:
            continue

        title = _safe_str(row.get("title")) or "Unknown"
        company = _safe_str(row.get("company_name") or row.get("company")) or "Unknown"
        location = _safe_str(row.get("location"))
        description = _safe_str(row.get("description"))
        date_posted = _safe_str(row.get("date_posted"))

        # Salary — JobSpy may return these as floats
        salary_min = _safe_int(row.get("min_amount") or row.get("salary_min"))
        salary_max = _safe_int(row.get("max_amount") or row.get("salary_max"))

        # Determine source
        site = _safe_str(row.get("site"))
        source = f"jobspy_{site}" if site else "jobspy"

        jobs.append({
            "id": _make_id(url),
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "source": source,
            "description": description,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "date_posted": date_posted,
            "date_scraped": _now_iso(),
            "status": "new",
        })

    return jobs


def scrape_major_boards(preferences: dict) -> list[dict]:
    """
    Scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google via JobSpy.
    Returns list of normalized job dicts.
    """
    from jobspy import scrape_jobs

    search_term = " OR ".join(preferences.get("target_roles", ["Software Engineer"]))

    # Build location string
    locations = preferences.get("locations", [])
    location_str = "United States"
    if locations:
        # Filter out 'Remote' for the location search param
        non_remote = [loc for loc in locations if loc.lower() != "remote"]
        if non_remote:
            location_str = non_remote[0]  # JobSpy works best with a single location

    # Map location to Indeed country code
    _indeed_country_map = {
        "united states": "USA", "usa": "USA", "us": "USA",
        "canada": "Canada", "united kingdom": "UK", "uk": "UK",
        "germany": "Germany", "india": "India", "australia": "Australia",
        "france": "France", "netherlands": "Netherlands", "singapore": "Singapore",
        "japan": "Japan", "brazil": "Brazil", "mexico": "Mexico",
        "ireland": "Ireland", "israel": "Israel", "sweden": "Sweden",
    }
    country_indeed = "USA"
    if locations:
        first_loc = locations[0].strip().lower()
        country_indeed = _indeed_country_map.get(first_loc, "USA")

    sites = ["indeed", "glassdoor", "zip_recruiter", "google"]
    # LinkedIn requires the li_at cookie which may not be set
    import os
    if os.getenv("LINKEDIN_SESSION_COOKIE"):
        sites.insert(0, "linkedin")

    print(f"  Searching: '{search_term}'")
    print(f"  Sites: {', '.join(sites)}")
    print(f"  Location: {location_str}")

    try:
        results = scrape_jobs(
            site_name=sites,
            search_term=search_term,
            location=location_str,
            results_wanted=50,
            hours_old=24,
            linkedin_fetch_description=True,
            country_indeed=country_indeed,
        )

        if results is None or results.empty:
            print("  No results returned from JobSpy.")
            return []

        print(f"  Raw results from JobSpy: {len(results)} rows")
        jobs = normalize_jobspy_results(results)
        print(f"  Normalized: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        print(f"  [JobSpy] Error during scrape: {e}")
        return []
