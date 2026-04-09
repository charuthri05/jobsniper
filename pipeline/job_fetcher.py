"""
Fetch a job posting from any URL and extract structured job data.

Strategy:
1. Try httpx (fast, no browser)
2. If empty/blocked, fall back to Playwright (handles JS-rendered pages)
3. Send extracted text to AI for structured extraction (title, company, location, description)
"""

import hashlib
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _make_id(url: str) -> str:
    """Generate a deterministic job ID from the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_with_httpx(url: str) -> str:
    """Try to fetch page content with httpx (fast, no browser)."""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug(f"httpx fetch failed for {url}: {e}")
        return ""


def _fetch_with_playwright(url: str) -> str:
    """Fallback: fetch page with Playwright (handles JS-rendered content)."""
    import asyncio

    async def _fetch():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)
                content = await page.content()
                return content
            except Exception as e:
                logger.debug(f"Playwright fetch failed for {url}: {e}")
                return ""
            finally:
                await browser.close()

    try:
        return asyncio.run(_fetch())
    except Exception as e:
        logger.debug(f"Playwright error: {e}")
        return ""


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, nav, footer elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def _extract_with_ai(text: str, url: str) -> dict:
    """Use AI to extract structured job data from page text."""
    from utils.ai_client import chat_completion
    import json

    # Truncate to avoid token limits
    text = text[:8000]

    system = """You are a job posting parser. Extract structured data from the text of a job posting page.
Return valid JSON only with exactly these fields. If a field cannot be determined, use empty string."""

    user_msg = f"""Extract the job posting details from this page content.

URL: {url}

PAGE CONTENT:
{text}

Return this exact JSON:
{{
  "title": "exact job title",
  "company": "company name",
  "location": "location (city, state, remote, etc.)",
  "description": "the full job description including requirements, responsibilities, qualifications — preserve as much detail as possible"
}}"""

    raw = chat_completion(system=system, user_message=user_msg, max_tokens=2000)

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        raise ValueError("AI could not extract job data from the page")

    parsed = json.loads(json_match.group())
    parsed.setdefault("title", "")
    parsed.setdefault("company", "")
    parsed.setdefault("location", "")
    parsed.setdefault("description", "")

    return parsed


def _try_greenhouse_api(url: str) -> dict | None:
    """If it's a Greenhouse URL, try the JSON API first (fast + clean)."""
    import httpx

    # Pattern: https://boards.greenhouse.io/{company}/jobs/{id}
    match = re.match(r"https?://boards\.greenhouse\.io/(\w+)/jobs/(\d+)", url)
    if not match:
        return None

    company, job_id = match.groups()
    api_url = f"https://api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"

    try:
        resp = httpx.get(api_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        description = ""
        if data.get("content"):
            soup = BeautifulSoup(data["content"], "html.parser")
            description = soup.get_text(separator="\n", strip=True)

        location = ""
        if data.get("location"):
            location = data["location"].get("name", "")

        return {
            "title": data.get("title", ""),
            "company": company.capitalize(),
            "location": location,
            "description": description,
        }
    except Exception:
        return None


def _try_lever_api(url: str) -> dict | None:
    """If it's a Lever URL, try the JSON API first."""
    import httpx

    # Pattern: https://jobs.lever.co/{company}/{id}
    match = re.match(r"https?://jobs\.lever\.co/(\w[\w-]*)/([a-f0-9-]+)", url)
    if not match:
        return None

    company, posting_id = match.groups()
    api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"

    try:
        resp = httpx.get(api_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        description = data.get("descriptionPlain", "")
        if not description:
            parts = []
            for section in data.get("lists", []):
                heading = section.get("text", "")
                if heading:
                    parts.append(heading)
                content = section.get("content", "")
                if content:
                    soup = BeautifulSoup(content, "html.parser")
                    parts.append(soup.get_text(separator="\n", strip=True))
            description = "\n\n".join(parts)

        additional = data.get("additional", "")
        if additional:
            soup = BeautifulSoup(additional, "html.parser")
            description += "\n\n" + soup.get_text(separator="\n", strip=True)

        location = ""
        categories = data.get("categories", {})
        if categories:
            location = categories.get("location", "")

        return {
            "title": data.get("text", ""),
            "company": company.capitalize(),
            "location": location,
            "description": description,
        }
    except Exception:
        return None


def fetch_job_from_url(url: str, progress_callback=None) -> dict:
    """
    Fetch a job posting from any URL and return a normalized job dict.

    Tries structured APIs first (Greenhouse, Lever), then falls back to
    HTML scraping + AI extraction for any other page.

    Returns dict with: success, job (normalized dict), error
    """
    def update(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    result = {"success": False, "job": None, "error": None}

    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Try structured APIs first (fast + clean)
    update("Checking for structured API...")
    job_data = _try_greenhouse_api(url)
    if job_data:
        update(f"Found via Greenhouse API: {job_data['title']}")
    else:
        job_data = _try_lever_api(url)
        if job_data:
            update(f"Found via Lever API: {job_data['title']}")

    # Fallback: fetch HTML and extract with AI
    if not job_data:
        update("Fetching page content...")
        html = _fetch_with_httpx(url)

        if not html or len(html) < 200:
            update("Direct fetch failed, trying with browser...")
            html = _fetch_with_playwright(url)

        if not html or len(html) < 200:
            result["error"] = "Could not fetch the page. Check the URL."
            return result

        text = _html_to_text(html)
        if len(text) < 100:
            result["error"] = "Could not extract text from the page."
            return result

        update("Extracting job details with AI...")
        try:
            job_data = _extract_with_ai(text, url)
        except Exception as e:
            result["error"] = f"AI extraction failed: {e}"
            return result

    if not job_data.get("title"):
        result["error"] = "Could not determine the job title from the page."
        return result

    # Build normalized job dict
    job = {
        "id": _make_id(url),
        "title": job_data["title"].strip(),
        "company": job_data.get("company", "Unknown").strip(),
        "location": job_data.get("location", "").strip(),
        "url": url,
        "source": "manual",
        "description": job_data.get("description", ""),
        "salary_min": None,
        "salary_max": None,
        "date_posted": "",
        "date_scraped": _now_iso(),
        "status": "queued",
    }

    update(f"Extracted: {job['title']} at {job['company']}")
    result["success"] = True
    result["job"] = job
    return result
