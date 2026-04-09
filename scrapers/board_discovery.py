"""
Auto-discover Greenhouse and Lever job boards from company names.

Takes a list of company names, tries common slug patterns against
the Greenhouse and Lever APIs, and returns which ones have active boards.
"""

import asyncio
import re
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Large list of tech companies to check — YC top companies, unicorns,
# well-known startups, FAANG, etc.
TECH_COMPANIES = [
    # FAANG / Big Tech
    "google", "meta", "apple", "amazon", "microsoft", "netflix",
    # Cloud / Infrastructure
    "snowflake", "databricks", "cloudflare", "datadog", "elastic",
    "hashicorp", "confluent", "mongodb", "cockroachlabs", "timescale",
    "planetscale", "neon", "supabase", "vercel", "netlify", "railway",
    "render", "fly", "digitalocean",
    # AI / ML
    "openai", "anthropic", "cohere", "mistral", "huggingface",
    "stability", "midjourney", "jasper", "writer", "adept",
    "inflection", "characterai", "perplexity", "runway",
    "scale", "labelbox", "weights-and-biases", "wandb", "modal",
    "anyscale", "ray", "deepmind", "nvidia",
    # Fintech
    "stripe", "plaid", "brex", "ramp", "mercury", "wise",
    "coinbase", "robinhood", "affirm", "chime", "sofi", "marqeta",
    "nerdwallet", "cashapp", "block", "adyen", "checkout",
    "carta", "capchase", "moderntreasury", "column", "unit",
    # E-commerce / Marketplace
    "shopify", "instacart", "doordash", "uber", "lyft",
    "airbnb", "vrbo", "etsy", "poshmark", "mercari",
    "faire", "goat", "stockx", "whatnot",
    # Social / Consumer
    "reddit", "discord", "snap", "pinterest", "spotify",
    "duolingo", "calm", "headspace", "strava", "peloton",
    "bumble", "hinge", "match",
    # Developer Tools
    "github", "gitlab", "atlassian", "jetbrains",
    "postman", "insomnia", "figma", "canva", "miro",
    "notion", "coda", "airtable", "asana", "linear",
    "retool", "superblocks", "appsmith", "budibase",
    "snyk", "sonarqube", "codecov", "launchdarkly",
    "sentry", "logdna", "mezmo", "chronosphere",
    # Cybersecurity
    "crowdstrike", "paloaltonetworks", "zscaler", "okta",
    "1password", "bitwarden", "tailscale", "cloudflare",
    "wiz", "orca-security", "lacework", "snyk",
    "sentinelone", "tanium", "rapid7",
    # SaaS / Enterprise
    "salesforce", "hubspot", "twilio", "sendgrid",
    "pagerduty", "opsgenie", "victorops",
    "gusto", "rippling", "deel", "remote", "oyster",
    "lattice", "cultureamp", "15five",
    "gong", "chorus", "outreach", "salesloft",
    "intercom", "drift", "zendesk", "freshworks",
    "contentful", "sanity", "strapi", "prismic",
    "amplitude", "mixpanel", "segment", "heap",
    "dbt-labs", "fivetran", "airbyte", "prefect",
    # Health Tech
    "veracyte", "tempus", "flatiron", "color",
    "ro", "hims", "cerebral", "springhealth",
    "benchling", "recursion", "insitro",
    # Autonomous / Robotics / Hardware
    "cruise", "aurora", "waymo", "zoox", "nuro",
    "anduril", "shield-ai", "skydio", "zipline",
    "relativity", "astranis", "spire",
    # Real Estate / PropTech
    "opendoor", "zillow", "redfin", "compass",
    "loft", "divvy", "bungalow",
    # Education
    "coursera", "udemy", "masterclass",
    "brilliant", "kahoot", "quizlet",
    # Gaming
    "roblox", "epicgames", "unity", "riot",
    # Other notable tech
    "palantir", "bloomberg", "squarespace", "webflow",
    "toast", "samsara", "procore", "servicetitan",
    "grammarly", "calendly", "loom", "mux",
    "drata", "vanta", "secureframe",
    "navan", "tripactions", "hopper",
    "flexport", "convoyinc", "project44",
    "plaid", "mx", "galileo-ft",
    "watershed", "watershedclimate", "pachama",
    "applied-intuition", "aurora-innovation",
    # Additional YC companies
    "algolia", "zapier", "gitlab", "razorpay",
    "meesho", "cleartax", "cred", "zerodha",
    "gojek", "grab", "sea",
]

# Common slug transformations to try
def _generate_slugs(company: str) -> list[str]:
    """Generate possible API slugs from a company name."""
    name = company.lower().strip()
    slugs = [name]

    # Remove common suffixes
    for suffix in [" inc", " inc.", " llc", " ltd", " corp", " co", " io", " ai", " hq"]:
        if name.endswith(suffix):
            slugs.append(name[:-len(suffix)].strip())

    # Replace spaces/special chars
    slugs.append(name.replace(" ", ""))
    slugs.append(name.replace(" ", "-"))
    slugs.append(name.replace(" ", "_"))

    # Remove "the" prefix
    if name.startswith("the "):
        slugs.append(name[4:])

    return list(dict.fromkeys(slugs))  # deduplicate, preserve order


async def _check_greenhouse(client: httpx.AsyncClient, slug: str) -> dict | None:
    """Check if a Greenhouse board exists and has jobs."""
    url = f"https://api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            job_count = len(data.get("jobs", []))
            if job_count > 0:
                return {"slug": slug, "ats": "greenhouse", "jobs": job_count}
    except Exception:
        pass
    return None


async def _check_lever(client: httpx.AsyncClient, slug: str) -> dict | None:
    """Check if a Lever board exists and has jobs."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return {"slug": slug, "ats": "lever", "jobs": len(data)}
    except Exception:
        pass
    return None


async def discover_boards(
    companies: list[str] | None = None,
    existing_greenhouse: list[str] | None = None,
    existing_lever: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """
    Discover Greenhouse and Lever boards from a list of company names.

    Args:
        companies: List of company names to check. Defaults to TECH_COMPANIES.
        existing_greenhouse: Already known Greenhouse slugs (to skip).
        existing_lever: Already known Lever slugs (to skip).
        progress_callback: Optional function(message) for progress updates.

    Returns:
        dict with: new_greenhouse, new_lever, total_checked, total_found
    """
    companies = companies or TECH_COMPANIES
    existing_greenhouse = set(s.lower() for s in (existing_greenhouse or []))
    existing_lever = set(s.lower() for s in (existing_lever or []))

    def update(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # Generate all slugs to check
    all_slugs = set()
    for company in companies:
        for slug in _generate_slugs(company):
            all_slugs.add(slug)

    # Remove already known
    all_slugs -= existing_greenhouse
    all_slugs -= existing_lever

    update(f"Checking {len(all_slugs)} potential slugs from {len(companies)} companies...")

    new_greenhouse = []
    new_lever = []
    checked = 0

    async with httpx.AsyncClient(
        timeout=10,
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    ) as client:
        # Check in batches to avoid overwhelming the APIs
        slug_list = list(all_slugs)
        batch_size = 50

        for i in range(0, len(slug_list), batch_size):
            batch = slug_list[i:i + batch_size]

            # Check both Greenhouse and Lever for each slug
            tasks = []
            for slug in batch:
                if slug not in existing_greenhouse:
                    tasks.append(_check_greenhouse(client, slug))
                if slug not in existing_lever:
                    tasks.append(_check_lever(client, slug))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception) or result is None:
                    continue
                if result["ats"] == "greenhouse":
                    new_greenhouse.append(result)
                    existing_greenhouse.add(result["slug"])
                    update(f"  Found Greenhouse: {result['slug']} ({result['jobs']} jobs)")
                else:
                    new_lever.append(result)
                    existing_lever.add(result["slug"])
                    update(f"  Found Lever: {result['slug']} ({result['jobs']} jobs)")

            checked += len(batch)
            update(f"Progress: {checked}/{len(slug_list)} slugs checked...")

            # Small delay between batches
            await asyncio.sleep(0.5)

    update(f"Discovery complete: {len(new_greenhouse)} new Greenhouse, {len(new_lever)} new Lever boards")

    return {
        "new_greenhouse": sorted(new_greenhouse, key=lambda x: x["jobs"], reverse=True),
        "new_lever": sorted(new_lever, key=lambda x: x["jobs"], reverse=True),
        "total_checked": checked,
        "total_found": len(new_greenhouse) + len(new_lever),
    }


def discover_boards_sync(
    companies: list[str] | None = None,
    existing_greenhouse: list[str] | None = None,
    existing_lever: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """Synchronous wrapper for discover_boards."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                discover_boards(companies, existing_greenhouse, existing_lever, progress_callback),
            )
            return future.result()
    else:
        return asyncio.run(
            discover_boards(companies, existing_greenhouse, existing_lever, progress_callback)
        )
