"""
LinkedIn Voyager API client using li_at session cookie.

Handles authentication, CSRF token, and provides methods for:
- Fetching all 1st-degree connections (bulk sync)
- Searching people at a specific company (on-demand)
- Finding recruiters at a company (on-demand)
"""

import logging
import os
import time
import random

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://www.linkedin.com/voyager/api"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class LinkedInClient:
    """Thin wrapper around LinkedIn's Voyager API."""

    def __init__(self, li_at_cookie: str | None = None):
        self.li_at = li_at_cookie or os.getenv("LINKEDIN_SESSION_COOKIE", "")
        if not self.li_at:
            raise ValueError("LINKEDIN_SESSION_COOKIE not set in .env")

        self._client = httpx.Client(timeout=20, follow_redirects=True)
        self._csrf = None
        self._headers = None
        self._authenticated = False

    def _ensure_auth(self):
        """Get CSRF token from LinkedIn using the li_at cookie."""
        if self._authenticated:
            return

        resp = self._client.get("https://www.linkedin.com", headers={
            "User-Agent": USER_AGENT,
            "Cookie": f"li_at={self.li_at}",
        })

        if resp.status_code != 200:
            raise ConnectionError(f"LinkedIn returned {resp.status_code} — cookie may be expired")

        jsessionid = dict(self._client.cookies).get("JSESSIONID", "")
        if not jsessionid:
            raise ConnectionError("Could not get JSESSIONID — cookie may be invalid")

        self._csrf = jsessionid.strip('"')
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "csrf-token": self._csrf,
            "Cookie": f'li_at={self.li_at}; JSESSIONID="{self._csrf}"',
            "x-li-lang": "en_US",
            "x-restli-protocol-version": "2.0.0",
        }
        self._authenticated = True
        logger.info("LinkedIn Voyager API authenticated")

    def _get(self, path: str) -> dict:
        """Make an authenticated GET request to the Voyager API."""
        self._ensure_auth()
        resp = self._client.get(f"{BASE_URL}{path}", headers=self._headers)
        if resp.status_code == 429:
            raise ConnectionError("LinkedIn rate limit hit — try again later")
        if resp.status_code == 401:
            self._authenticated = False
            raise ConnectionError("LinkedIn session expired — update LINKEDIN_SESSION_COOKIE in .env")
        resp.raise_for_status()
        return resp.json()

    def _sleep(self):
        """Random delay between requests to avoid detection."""
        time.sleep(random.uniform(1.5, 3.5))

    def get_my_profile(self) -> dict:
        """Get the authenticated user's profile."""
        data = self._get("/me")
        return data

    def fetch_connections(self, count: int = 100, start: int = 0) -> dict:
        """Fetch a page of 1st-degree connections.

        Returns dict with 'included' (profile data) and 'paging' info.
        """
        path = (
            "/relationships/dash/connections"
            "?decorationId=com.linkedin.voyager.dash.deco.web.mynetwork.ConnectionListWithProfile-16"
            f"&count={count}&q=search&start={start}"
            "&sortType=RECENTLY_ADDED"
        )
        return self._get(path)

    def fetch_all_connections(self, progress_callback=None) -> list[dict]:
        """Fetch ALL 1st-degree connections (paginated).

        Returns list of dicts with: name, headline, public_id, urn_id, company (parsed from headline).
        """
        all_connections = []
        start = 0
        page_size = 100
        total = None

        while True:
            if progress_callback:
                progress_callback(f"Fetching connections... {start} loaded")

            try:
                data = self.fetch_connections(count=page_size, start=start)
            except Exception as e:
                logger.error(f"Error fetching connections at offset {start}: {e}")
                break

            included = data.get("included", [])

            # Extract profile data from included items
            for item in included:
                if "firstName" not in item:
                    continue

                name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
                headline = item.get("occupation", "") or item.get("headline", "")
                public_id = item.get("publicIdentifier", "")
                urn = item.get("entityUrn", "")

                # Parse company from headline (common format: "Title at Company")
                company = _parse_company_from_headline(headline)

                all_connections.append({
                    "name": name,
                    "headline": headline,
                    "company": company,
                    "public_id": public_id,
                    "urn": urn,
                    "linkedin_url": f"https://www.linkedin.com/in/{public_id}" if public_id else "",
                })

            # Check if we've fetched all — stop only when a page returns 0 profiles
            fetched_profiles = len([i for i in included if "firstName" in i])
            if fetched_profiles == 0:
                break

            start += page_size
            self._sleep()

        if progress_callback:
            progress_callback(f"Loaded {len(all_connections)} connections")

        logger.info(f"Fetched {len(all_connections)} total connections")
        return all_connections

    def search_people_at_company(self, company_id: str, network_depth: str = "F,S", count: int = 10) -> list[dict]:
        """Search for people at a specific company in your network.

        Args:
            company_id: LinkedIn numeric company ID
            network_depth: 'F' (1st), 'S' (2nd), 'O' (3rd+), comma-separated
            count: max results

        Returns list of dicts with: name, headline, connection_degree, public_id
        """
        path = (
            "/search/dash/clusters"
            "?decorationId=com.linkedin.voyager.dash.deco.search.SearchClusterCollection-186"
            "&origin=FACETED_SEARCH"
            "&q=all"
            f"&query=(flagshipSearchIntent:SEARCH_SRP"
            f",queryParameters:(currentCompany:List({company_id})"
            f",network:List({network_depth})"
            f",resultType:List(PEOPLE)))"
            f"&start=0&count={count}"
        )

        data = self._get(path)
        results = []

        for item in data.get("included", []):
            if "firstName" not in item:
                continue

            name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
            headline = item.get("headline", "") or item.get("occupation", "")
            public_id = item.get("publicIdentifier", "")

            # Determine connection degree from networkDistance
            degree = 0
            network_info = item.get("networkDistance", {})
            if network_info:
                val = network_info.get("value", "")
                if "DISTANCE_1" in str(val):
                    degree = 1
                elif "DISTANCE_2" in str(val):
                    degree = 2
                elif "DISTANCE_3" in str(val):
                    degree = 3

            results.append({
                "name": name,
                "headline": headline,
                "public_id": public_id,
                "linkedin_url": f"https://www.linkedin.com/in/{public_id}" if public_id else "",
                "connection_degree": degree,
            })

        return results

    def search_recruiters_at_company(self, company_id: str, count: int = 5) -> list[dict]:
        """Find recruiters/talent acquisition people at a company."""
        path = (
            "/search/dash/clusters"
            "?decorationId=com.linkedin.voyager.dash.deco.search.SearchClusterCollection-186"
            "&origin=FACETED_SEARCH"
            "&q=all"
            f"&query=(flagshipSearchIntent:SEARCH_SRP"
            f",keywords:recruiter"
            f",queryParameters:(currentCompany:List({company_id})"
            f",resultType:List(PEOPLE)))"
            f"&start=0&count={count}"
        )

        data = self._get(path)
        results = []

        for item in data.get("included", []):
            if "firstName" not in item:
                continue

            name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
            headline = item.get("headline", "") or item.get("occupation", "")
            public_id = item.get("publicIdentifier", "")

            # Only include people with recruiting-related titles
            headline_lower = headline.lower()
            is_recruiter = any(kw in headline_lower for kw in [
                "recruiter", "recruiting", "talent", "sourcer",
                "people ops", "hiring", "acquisition",
            ])

            if is_recruiter:
                results.append({
                    "name": name,
                    "headline": headline,
                    "public_id": public_id,
                    "linkedin_url": f"https://www.linkedin.com/in/{public_id}" if public_id else "",
                    "contact_type": "recruiter",
                })

        return results

    def get_company_id(self, company_slug: str) -> str | None:
        """Look up a company's numeric ID from its slug/name."""
        path = f"/organization/companies?q=universalName&universalName={company_slug}"
        try:
            data = self._get(path)
            # Extract company ID from entityUrn
            for item in data.get("included", data.get("elements", [])):
                urn = item.get("entityUrn", "")
                if "fs_company:" in urn or "fs_normalized_company:" in urn:
                    return urn.split(":")[-1]
            # Try elements directly
            elements = data.get("elements", [])
            if elements:
                urn = elements[0].get("entityUrn", "")
                if urn:
                    return urn.split(":")[-1]
        except Exception as e:
            logger.debug(f"Could not find company ID for '{company_slug}': {e}")
        return None

    def close(self):
        """Close the HTTP client."""
        self._client.close()


def _parse_company_from_headline(headline: str) -> str:
    """Extract company name from a LinkedIn headline.

    Common patterns:
    - "Software Engineer at Stripe"
    - "SWE @ Google"
    - "Founder, Acme Corp"
    - "Engineering Manager | Netflix"
    """
    if not headline:
        return ""

    headline = headline.strip()

    # Pattern: "... at Company"
    if " at " in headline:
        return headline.split(" at ")[-1].strip().split("|")[0].strip().split("·")[0].strip()

    # Pattern: "... @ Company"
    if " @ " in headline:
        return headline.split(" @ ")[-1].strip().split("|")[0].strip().split("·")[0].strip()

    # Pattern: "Title | Company"
    if " | " in headline:
        parts = headline.split(" | ")
        if len(parts) >= 2:
            return parts[-1].strip()

    # Pattern: "Title, Company"
    if ", " in headline:
        parts = headline.split(", ")
        if len(parts) == 2:
            return parts[-1].strip()

    return ""
