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


def _run_single_search(sites: list, search_term: str, location: str,
                        country_indeed: str, results_wanted: int = 100) -> pd.DataFrame | None:
    """Run a single JobSpy search. Returns DataFrame or None."""
    from jobspy import scrape_jobs
    try:
        return scrape_jobs(
            site_name=sites,
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=24,
            linkedin_fetch_description=True,
            country_indeed=country_indeed,
        )
    except Exception as e:
        print(f"    [JobSpy] Error for '{search_term}' in '{location}': {e}")
        return None


def scrape_major_boards(preferences: dict) -> list[dict]:
    """
    Scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google via JobSpy.
    Runs multiple searches in parallel for broader coverage.
    Returns list of normalized job dicts.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    target_roles = preferences.get("target_roles", ["Software Engineer"])

    sites = ["indeed", "glassdoor", "zip_recruiter", "google"]
    if os.getenv("LINKEDIN_SESSION_COOKIE"):
        sites.insert(0, "linkedin")

    # Build search queries — split roles into smaller groups for better results
    # LinkedIn/Indeed return more relevant results with specific queries
    search_queries = []
    for role in target_roles:
        search_queries.append(role)

    # Deduplicate
    search_queries = list(dict.fromkeys(search_queries))

    # Locations to search — if empty, use major US tech hubs for better coverage
    locations = preferences.get("locations", [])
    if not locations:
        search_locations = [
            "San Francisco, CA",
            "New York, NY",
            "Seattle, WA",
            "Austin, TX",
            "Remote",
        ]
    else:
        search_locations = locations

    country_indeed = "USA"

    print(f"  Sites: {', '.join(sites)}")
    print(f"  Roles: {len(search_queries)} queries")
    print(f"  Locations: {', '.join(search_locations)}")

    # Run searches in parallel — each role x location combo
    all_dfs = []
    tasks = []

    # Build task list: top 3 roles x all locations (cap total searches to avoid slowness)
    top_roles = search_queries[:3]  # Most important roles
    for role in top_roles:
        for loc in search_locations:
            tasks.append((role, loc))

    # Cap at 10 parallel searches
    tasks = tasks[:10]
    print(f"  Running {len(tasks)} parallel searches...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_run_single_search, sites, role, loc, country_indeed, 50): (role, loc)
            for role, loc in tasks
        }

        for future in as_completed(futures):
            role, loc = futures[future]
            df = future.result()
            if df is not None and not df.empty:
                all_dfs.append(df)
                print(f"    '{role}' in '{loc}': {len(df)} results")

    if not all_dfs:
        print("  No results returned from JobSpy.")
        return []

    # Combine all results and deduplicate by URL
    combined = pd.concat(all_dfs, ignore_index=True)

    # Deduplicate by job_url
    url_col = "job_url" if "job_url" in combined.columns else "link"
    if url_col in combined.columns:
        combined = combined.drop_duplicates(subset=[url_col], keep="first")

    print(f"  Raw results combined: {len(combined)} rows (deduplicated)")
    jobs = normalize_jobspy_results(combined)
    print(f"  Normalized: {len(jobs)} jobs")
    return jobs
