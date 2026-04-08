"""
Greenhouse and Lever ATS scrapers.

These are public JSON APIs — no authentication needed.
Uses async httpx for maximum parallelism — all boards fetched simultaneously.
"""

import asyncio
import hashlib
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
    job_id = raw.get("id", "")
    url = f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"

    location = ""
    if raw.get("location"):
        location = raw["location"].get("name", "")

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


async def _fetch_greenhouse_async(client: httpx.AsyncClient, board_token: str) -> tuple[str, list[dict]]:
    """Fetch all jobs from a single Greenhouse board asynchronously."""
    url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        return board_token, [normalize_greenhouse_job(j, board_token) for j in jobs]
    except httpx.HTTPStatusError as e:
        return board_token, []
    except Exception:
        return board_token, []


# Keep sync version for standalone use
def fetch_greenhouse_jobs(board_token: str) -> list[dict]:
    """Fetch all jobs from a Greenhouse board (sync wrapper)."""
    url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        return [normalize_greenhouse_job(j, board_token) for j in jobs]
    except Exception:
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

    salary_min = None
    salary_max = None

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


async def _fetch_lever_async(client: httpx.AsyncClient, company_slug: str) -> tuple[str, list[dict]]:
    """Fetch all jobs from a single Lever board asynchronously."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        postings = resp.json()
        if not isinstance(postings, list):
            return company_slug, []
        return company_slug, [normalize_lever_job(j, company_slug) for j in postings]
    except Exception:
        return company_slug, []


def fetch_lever_jobs(company_slug: str) -> list[dict]:
    """Fetch all jobs from a Lever company page (sync wrapper)."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        postings = resp.json()
        if not isinstance(postings, list):
            return []
        return [normalize_lever_job(j, company_slug) for j in postings]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Async batch fetch — all boards fire at once
# ---------------------------------------------------------------------------

async def _fetch_all_async(preferences: dict) -> list[dict]:
    """Fire all Greenhouse + Lever requests simultaneously."""
    greenhouse_boards = preferences.get("greenhouse_boards", [])
    lever_boards = preferences.get("lever_boards", [])
    total_boards = len(greenhouse_boards) + len(lever_boards)

    print(f"  Fetching from {total_boards} boards simultaneously...")

    all_jobs = []

    async with httpx.AsyncClient(timeout=20, limits=httpx.Limits(max_connections=50)) as client:
        # Fire ALL requests at once
        tasks = []
        for board in greenhouse_boards:
            tasks.append(_fetch_greenhouse_async(client, board))
        for slug in lever_boards:
            tasks.append(_fetch_lever_async(client, slug))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            name, jobs = result
            all_jobs.extend(jobs)
            if jobs:
                print(f"    {name}: {len(jobs)} jobs")

    print(f"  Total ATS jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_all_ats_jobs(preferences: dict, **kwargs) -> list[dict]:
    """
    Fetch jobs from all configured Greenhouse and Lever boards.
    Uses async I/O — all 70 boards fetched simultaneously.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context (e.g. Flask with async), use thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, _fetch_all_async(preferences))
            return future.result()
    else:
        return asyncio.run(_fetch_all_async(preferences))
