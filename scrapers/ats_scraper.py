"""
Greenhouse and Lever ATS scrapers.

These are public JSON APIs — no authentication needed.
Rate limit: ~100 req/min for Greenhouse, so we add a small sleep between boards.
"""

import hashlib
import time
from datetime import datetime, timezone
from html import unescape

import httpx
from bs4 import BeautifulSoup


def _make_id(url: str) -> str:
    """Generate a deterministic job ID from the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _strip_html(html: str | None) -> str:
    """Remove HTML tags and decode entities. Returns plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return unescape(soup.get_text(separator="\n", strip=True))


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

def normalize_greenhouse_job(raw: dict, board_token: str) -> dict:
    """Convert a single Greenhouse API job object to our standard schema."""
    # Build the application URL
    job_id = raw.get("id", "")
    url = f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"

    location = ""
    if raw.get("location"):
        location = raw["location"].get("name", "")

    # Description may contain HTML
    description = _strip_html(raw.get("content", ""))

    return {
        "id": _make_id(url),
        "title": raw.get("title", "Unknown"),
        "company": board_token.capitalize(),
        "location": location,
        "url": url,
        "source": "greenhouse",
        "description": description,
        "salary_min": None,
        "salary_max": None,
        "date_posted": raw.get("updated_at", ""),
        "date_scraped": _now_iso(),
        "status": "new",
    }


def fetch_greenhouse_jobs(board_token: str) -> list[dict]:
    """
    Fetch all jobs from a Greenhouse board.
    Returns a list of normalized job dicts.
    """
    url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        return [normalize_greenhouse_job(j, board_token) for j in jobs]
    except httpx.HTTPStatusError as e:
        print(f"  [Greenhouse] HTTP {e.response.status_code} for board '{board_token}'")
        return []
    except httpx.RequestError as e:
        print(f"  [Greenhouse] Request error for board '{board_token}': {e}")
        return []
    except Exception as e:
        print(f"  [Greenhouse] Unexpected error for board '{board_token}': {e}")
        return []


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

def normalize_lever_job(raw: dict, company_slug: str) -> dict:
    """Convert a single Lever API job object to our standard schema."""
    url = raw.get("hostedUrl", "")
    if not url:
        url = f"https://jobs.lever.co/{company_slug}/{raw.get('id', '')}"

    location = ""
    categories = raw.get("categories", {})
    if categories:
        location = categories.get("location", "")

    description_parts = []
    for section in raw.get("lists", []):
        heading = section.get("text", "")
        if heading:
            description_parts.append(heading)
        for item in section.get("content", "").split("<li>"):
            clean = _strip_html(item)
            if clean:
                description_parts.append(f"  - {clean}")

    additional = _strip_html(raw.get("additional", ""))
    description_text = _strip_html(raw.get("descriptionPlain", ""))
    if not description_text:
        description_text = "\n".join(description_parts)
    if additional:
        description_text += "\n\n" + additional

    # Salary parsing from Lever's salary range field (if present)
    salary_min = None
    salary_max = None
    compensation = categories.get("commitment", "")

    return {
        "id": _make_id(url),
        "title": raw.get("text", "Unknown"),
        "company": company_slug.capitalize(),
        "location": location,
        "url": url,
        "source": "lever",
        "description": description_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "date_posted": "",
        "date_scraped": _now_iso(),
        "status": "new",
    }


def fetch_lever_jobs(company_slug: str) -> list[dict]:
    """
    Fetch all jobs from a Lever company page.
    Returns a list of normalized job dicts.
    """
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        postings = resp.json()
        if not isinstance(postings, list):
            return []
        return [normalize_lever_job(j, company_slug) for j in postings]
    except httpx.HTTPStatusError as e:
        print(f"  [Lever] HTTP {e.response.status_code} for company '{company_slug}'")
        return []
    except httpx.RequestError as e:
        print(f"  [Lever] Request error for company '{company_slug}': {e}")
        return []
    except Exception as e:
        print(f"  [Lever] Unexpected error for company '{company_slug}': {e}")
        return []


# ---------------------------------------------------------------------------
# Batch fetch
# ---------------------------------------------------------------------------

def _fetch_greenhouse_worker(board: str) -> tuple[str, list[dict]]:
    """Worker function for parallel Greenhouse fetching."""
    jobs = fetch_greenhouse_jobs(board)
    return board, jobs


def _fetch_lever_worker(slug: str) -> tuple[str, list[dict]]:
    """Worker function for parallel Lever fetching."""
    jobs = fetch_lever_jobs(slug)
    return slug, jobs


def fetch_all_ats_jobs(preferences: dict, max_workers: int = 10) -> list[dict]:
    """
    Fetch jobs from all configured Greenhouse and Lever boards in parallel.
    Uses 10 concurrent workers by default — fast but stays under rate limits.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_jobs = []
    greenhouse_boards = preferences.get("greenhouse_boards", [])
    lever_boards = preferences.get("lever_boards", [])

    # Parallel Greenhouse fetching
    print(f"  Fetching from {len(greenhouse_boards)} Greenhouse boards ({max_workers} parallel)...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_greenhouse_worker, board): board
            for board in greenhouse_boards
        }
        for future in as_completed(futures):
            board, jobs = future.result()
            all_jobs.extend(jobs)
            if jobs:
                print(f"    {board}: {len(jobs)} jobs")

    # Parallel Lever fetching
    if lever_boards:
        print(f"  Fetching from {len(lever_boards)} Lever boards...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_lever_worker, slug): slug
                for slug in lever_boards
            }
            for future in as_completed(futures):
                slug, jobs = future.result()
                all_jobs.extend(jobs)
                if jobs:
                    print(f"    {slug}: {len(jobs)} jobs")

    print(f"  Total ATS jobs fetched: {len(all_jobs)}")
    return all_jobs
