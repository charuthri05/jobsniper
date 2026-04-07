"""
Hiring Cafe (hiring.cafe) job scraper.

Uses Playwright to bypass Cloudflare protection, then calls the internal
search API via page.evaluate() to fetch matching jobs.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from html import unescape

from bs4 import BeautifulSoup


def _make_id(url: str) -> str:
    """Generate a deterministic job ID from the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _strip_html(html: str | None) -> str:
    """Remove HTML tags and decode entities."""
    if not html:
        return ""
    if "<" in html and ">" in html:
        soup = BeautifulSoup(html, "html.parser")
        return unescape(soup.get_text(separator="\n", strip=True))
    return html.strip()


# Known country → Hiring Cafe location object mapping
_COUNTRY_MAP = {
    "united states": {
        "formatted_address": "United States",
        "types": ["country"],
        "geometry": {"location": {"lat": "39.8283", "lon": "-98.5795"}},
        "id": "user_country",
        "address_components": [
            {"long_name": "United States", "short_name": "US", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "canada": {
        "formatted_address": "Canada",
        "types": ["country"],
        "geometry": {"location": {"lat": "56.1304", "lon": "-106.3468"}},
        "id": "user_country_ca",
        "address_components": [
            {"long_name": "Canada", "short_name": "CA", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "united kingdom": {
        "formatted_address": "United Kingdom",
        "types": ["country"],
        "geometry": {"location": {"lat": "55.3781", "lon": "-3.4360"}},
        "id": "user_country_gb",
        "address_components": [
            {"long_name": "United Kingdom", "short_name": "GB", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "germany": {
        "formatted_address": "Germany",
        "types": ["country"],
        "geometry": {"location": {"lat": "51.1657", "lon": "10.4515"}},
        "id": "user_country_de",
        "address_components": [
            {"long_name": "Germany", "short_name": "DE", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "india": {
        "formatted_address": "India",
        "types": ["country"],
        "geometry": {"location": {"lat": "20.5937", "lon": "78.9629"}},
        "id": "user_country_in",
        "address_components": [
            {"long_name": "India", "short_name": "IN", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "australia": {
        "formatted_address": "Australia",
        "types": ["country"],
        "geometry": {"location": {"lat": "-25.2744", "lon": "133.7751"}},
        "id": "user_country_au",
        "address_components": [
            {"long_name": "Australia", "short_name": "AU", "types": ["country"]}
        ],
        "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
    },
    "remote": {
        "formatted_address": "Remote",
        "types": ["anywhere"],
        "geometry": {"location": {"lat": "0", "lon": "0"}},
        "id": "remote_anywhere",
        "address_components": [],
        "options": {"flexible_regions": ["anywhere_in_world"]},
    },
}


def _build_location_entries(locations: list[str]) -> list[dict]:
    """Convert user location strings to Hiring Cafe location objects.

    Falls back to United States if no locations are specified or none match.
    """
    if not locations:
        return [_COUNTRY_MAP["united states"]]

    entries = []
    for loc in locations:
        key = loc.strip().lower()
        if key in _COUNTRY_MAP:
            entries.append(_COUNTRY_MAP[key])
        elif key == "uk":
            entries.append(_COUNTRY_MAP["united kingdom"])
        elif key == "us" or key == "usa":
            entries.append(_COUNTRY_MAP["united states"])
        else:
            # For city-level or unknown locations, build a generic entry
            entries.append({
                "formatted_address": loc.strip(),
                "types": ["locality"],
                "geometry": {"location": {"lat": "0", "lon": "0"}},
                "id": f"user_loc_{key.replace(' ', '_').replace(',', '')}",
                "address_components": [
                    {"long_name": loc.strip(), "short_name": loc.strip(), "types": ["locality"]}
                ],
                "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
            })

    return entries if entries else [_COUNTRY_MAP["united states"]]


def _build_search_states(preferences: dict) -> list[dict]:
    """Build multiple Hiring Cafe searchState objects — one per role keyword.

    The API returns fewer results with OR-combined queries, so we run
    separate searches for each target role and merge/deduplicate later.
    """
    seniority_map = {
        "entry-level": "Entry Level",
        "junior": "Entry Level",
        "mid": "Mid Level",
        "senior": "Senior Level",
        "staff": "Staff",
        "principal": "Principal",
        "lead": "Lead",
    }
    seniority_levels = []
    for level in preferences.get("seniority_levels", ["mid", "senior"]):
        mapped = seniority_map.get(level.lower())
        if mapped and mapped not in seniority_levels:
            seniority_levels.append(mapped)
    if not seniority_levels:
        seniority_levels = ["Mid Level", "Senior Level"]

    # Build location objects from preferences
    location_entries = _build_location_entries(preferences.get("locations", []))

    base = {
        "dateFetchedPastNDays": 7,
        "locations": location_entries,
        "workplaceTypes": ["Remote", "Hybrid", "Onsite"],
        "commitmentTypes": ["Full Time"],
        "seniorityLevel": seniority_levels,
        "sortBy": "default",
    }

    # Use up to 4 target roles as separate queries
    roles = preferences.get("target_roles", ["Software Engineer"])[:4]
    return [{**base, "searchQuery": role} for role in roles]


# JavaScript executed inside the browser to call the Hiring Cafe API.
# Uses base64-encoded searchState as a GET query parameter, matching the
# site's own request pattern. Returns raw results array.
_JS_FETCH_JOBS = """
async (searchState) => {
    const encoded = btoa(encodeURIComponent(JSON.stringify(searchState)));
    const url = "/api/search-jobs?s=" + encoded + "&sv=control";
    const resp = await fetch(url);
    if (!resp.ok) return {error: "HTTP " + resp.status, results: []};
    return await resp.json();
}
"""


def _normalize_job(raw: dict) -> dict | None:
    """Convert a single Hiring Cafe API job object to our standard schema."""
    job_info = raw.get("job_information", {})
    processed = raw.get("v5_processed_job_data", {})
    company_data = raw.get("v5_processed_company_data", {})

    title = job_info.get("title") or processed.get("core_job_title", "")
    if not title:
        return None

    company = (
        company_data.get("name")
        or processed.get("company_name")
        or raw.get("board_token", "Unknown")
    )

    apply_url = raw.get("apply_url", "")
    if not apply_url:
        return None

    location = processed.get("formatted_workplace_location", "")
    workplace_type = processed.get("workplace_type", "")
    if workplace_type and location:
        location = f"{location} ({workplace_type})"
    elif workplace_type:
        location = workplace_type

    description = _strip_html(job_info.get("description", ""))

    salary_min = processed.get("yearly_min_compensation")
    salary_max = processed.get("yearly_max_compensation")
    salary_min = int(salary_min) if isinstance(salary_min, (int, float)) and salary_min > 0 else None
    salary_max = int(salary_max) if isinstance(salary_max, (int, float)) and salary_max > 0 else None

    date_posted = processed.get("estimated_publish_date", "")

    return {
        "id": _make_id(apply_url),
        "title": title.strip(),
        "company": company.strip(),
        "location": location,
        "url": apply_url,
        "source": "hiringcafe",
        "description": description,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "date_posted": date_posted,
        "date_scraped": _now_iso(),
        "status": "new",
    }


async def _fetch_with_playwright(search_states: list[dict]) -> list[dict]:
    """Use Playwright to bypass Cloudflare and call the search API for each query."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        )
        page = await context.new_page()

        # Step 1: Navigate to hiring.cafe and wait for Cloudflare to pass
        print("    Navigating to hiring.cafe (Cloudflare challenge)...")
        await page.goto(
            "https://hiring.cafe",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        cloudflare_passed = False
        for _ in range(20):
            await page.wait_for_timeout(2000)
            try:
                title = await page.title()
            except Exception:
                await page.wait_for_timeout(3000)
                try:
                    title = await page.title()
                except Exception:
                    continue
            if "just a moment" not in title.lower():
                cloudflare_passed = True
                break

        if not cloudflare_passed:
            print("    Cloudflare challenge did not resolve in time.")
            await browser.close()
            return []

        await page.wait_for_timeout(2000)
        print("    Cloudflare passed.")

        # Step 2: Run each search query and collect results
        all_results = []
        seen_urls = set()

        for state in search_states:
            query = state.get("searchQuery", "?")
            print(f"    Fetching: '{query}'...")
            try:
                response = await page.evaluate(_JS_FETCH_JOBS, state)
            except Exception as e:
                print(f"    Error for '{query}': {e}")
                continue

            if isinstance(response, dict) and "error" in response:
                print(f"    API error for '{query}': {response['error']}")
                continue

            results = response.get("results", []) if isinstance(response, dict) else []
            new_count = 0
            for r in results:
                url = r.get("apply_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
                    new_count += 1
            print(f"      {len(results)} results, {new_count} new (deduped)")

        await browser.close()

    return all_results


def fetch_hiringcafe_jobs(preferences: dict) -> list[dict]:
    """
    Fetch jobs from Hiring Cafe's internal API.
    Runs multiple search queries (one per target role) and merges results.
    Returns a list of normalized job dicts.
    """
    search_states = _build_search_states(preferences)
    roles = [s["searchQuery"] for s in search_states]
    print(f"  [Hiring Cafe] Queries: {roles}")

    try:
        raw_jobs = asyncio.run(_fetch_with_playwright(search_states))
    except Exception as e:
        print(f"  [Hiring Cafe] Error: {e}")
        return []

    print(f"  [Hiring Cafe] Raw results (deduped): {len(raw_jobs)}")

    jobs = []
    for raw in raw_jobs:
        normalized = _normalize_job(raw)
        if normalized:
            jobs.append(normalized)

    print(f"  [Hiring Cafe] Normalized: {len(jobs)} jobs")
    return jobs
