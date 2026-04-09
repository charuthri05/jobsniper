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
    # ══════════════════════════════════════════════════════════════
    # FAANG / Big Tech
    # ══════════════════════════════════════════════════════════════
    "google", "meta", "apple", "amazon", "microsoft", "netflix",
    "nvidia", "oracle", "ibm", "intel", "amd", "qualcomm",
    "adobe", "vmware", "dell", "hp", "cisco", "broadcom",

    # ══════════════════════════════════════════════════════════════
    # Cloud / Infrastructure / DevOps
    # ══════════════════════════════════════════════════════════════
    "snowflake", "databricks", "cloudflare", "datadog", "elastic",
    "hashicorp", "confluent", "mongodb", "cockroachlabs", "timescale",
    "planetscale", "neon", "supabase", "vercel", "netlify", "railway",
    "render", "fly", "digitalocean", "linode", "vultr",
    "pulumi", "env0", "spacelift", "terrateam",
    "grafana", "chronosphere", "lightstep", "honeycomb",

    # ══════════════════════════════════════════════════════════════
    # AI / ML / LLM Companies
    # ══════════════════════════════════════════════════════════════
    "openai", "anthropic", "cohere", "mistral", "huggingface",
    "stability", "midjourney", "jasper", "writer", "adept",
    "inflection", "characterai", "perplexity", "runway",
    "scale", "labelbox", "weights-and-biases", "wandb", "modal",
    "anyscale", "deepmind", "together", "togetherai",
    "replicate", "baseten", "banana-dev", "cerebras",
    "sambanova", "groq", "fireworks-ai", "fixie",
    "langchain", "llamaindex", "pinecone", "weaviate", "chroma",
    "unstructured", "humanloop", "promptlayer",
    "descript", "elevenlab", "synthesia", "tavus",
    "glean", "mem", "notion-ai", "codeium", "cursor",
    "magic", "poolside", "augment", "sourcegraph",
    "cognition", "devin", "factory", "codegen",
    "harvey", "casetext", "relativity",
    "hebbia", "vectara", "txtai",

    # ══════════════════════════════════════════════════════════════
    # YC Top Companies (W24, S24, W23, S23 batches)
    # ══════════════════════════════════════════════════════════════
    "posthog", "cal-com", "cal", "resend", "trigger-dev",
    "inngest", "convoy", "novu", "tinybird", "clickhouse",
    "turso", "drizzle", "encore", "zephyr", "stytch",
    "clerk", "workos", "propelauth", "passage",
    "infisical", "doppler", "bearer",
    "mintlify", "readme", "bump-sh", "speakeasy-api",
    "browserbase", "apify", "browserless", "playwright",
    "latitude", "helicone", "braintrust", "arize",
    "portkey", "orb", "metronome", "amberflo",
    "superblocks", "retool", "airplane", "windmill",
    "nango", "merge", "finch", "vessel",
    "snaplet", "neosync", "gretel", "tonic",
    "traceloop", "langtrace", "logfire",
    "highlight-io", "komodor", "groundcover",

    # ══════════════════════════════════════════════════════════════
    # YC Unicorns & Notable Alumni
    # ══════════════════════════════════════════════════════════════
    "stripe", "airbnb", "instacart", "doordash", "coinbase",
    "dropbox", "twitch", "reddit", "gitlab", "zapier",
    "algolia", "segment", "brex", "ramp", "faire",
    "deel", "rippling", "gusto", "lattice",
    "fivetran", "airbyte", "dbt-labs", "prefect",
    "mux", "loom", "sendbird", "stream",
    "checkr", "plaid", "moderntreasury", "column",
    "benchling", "recursion", "flatiron",
    "gong", "outreach", "salesloft", "clari",
    "webflow", "framer", "builder-io",
    "vercel", "railway", "render",
    "snyk", "vanta", "drata", "secureframe",
    "tailscale", "ngrok", "teleport",
    "pagerduty", "firehydrant", "rootly",
    "launchdarkly", "split", "flagsmith",
    "sentry", "logdna", "mezmo",
    "liveblocks", "partykit", "convex",

    # ══════════════════════════════════════════════════════════════
    # Fintech
    # ══════════════════════════════════════════════════════════════
    "stripe", "plaid", "brex", "ramp", "mercury", "wise",
    "coinbase", "robinhood", "affirm", "chime", "sofi", "marqeta",
    "nerdwallet", "cashapp", "block", "adyen", "checkout",
    "carta", "capchase", "moderntreasury", "column", "unit",
    "lithic", "highnote", "synctera", "treasury-prime",
    "alloy", "sardine", "unit21", "hummingbird",
    "moov", "dwolla", "abound", "method-fi",
    "teller", "akoya", "finicity",
    "pinwheel", "argyle", "truework",
    "melio", "routable", "rho", "navan",
    "razorpay", "paytm", "phonepe",

    # ══════════════════════════════════════════════════════════════
    # E-commerce / Marketplace / Logistics
    # ══════════════════════════════════════════════════════════════
    "shopify", "instacart", "doordash", "uber", "lyft",
    "airbnb", "etsy", "poshmark", "mercari",
    "faire", "goat", "stockx", "whatnot",
    "flexport", "project44", "shipbob", "shippo",
    "bolt", "fast", "paddle", "chargebee", "recurly",

    # ══════════════════════════════════════════════════════════════
    # Social / Consumer / Media
    # ══════════════════════════════════════════════════════════════
    "reddit", "discord", "snap", "pinterest", "spotify",
    "duolingo", "calm", "headspace", "strava", "peloton",
    "bumble", "hinge", "match",
    "substack", "beehiiv", "ghost", "medium",
    "clubhouse", "dispo", "poparazzi",

    # ══════════════════════════════════════════════════════════════
    # Developer Tools / Productivity
    # ══════════════════════════════════════════════════════════════
    "github", "gitlab", "atlassian",
    "postman", "figma", "canva", "miro",
    "notion", "coda", "airtable", "asana", "linear",
    "retool", "appsmith",
    "snyk", "codecov", "launchdarkly",
    "sentry", "logdna",
    "replit", "codespaces", "gitpod", "coder",
    "zed", "warp", "fig", "iterm",
    "raycast", "alfred", "arc",

    # ══════════════════════════════════════════════════════════════
    # Cybersecurity
    # ══════════════════════════════════════════════════════════════
    "crowdstrike", "paloaltonetworks", "zscaler", "okta",
    "1password", "bitwarden", "tailscale",
    "wiz", "orca-security", "lacework",
    "sentinelone", "tanium", "rapid7",
    "snyk", "semgrep", "endor-labs",
    "chainguard", "sigstore", "stackhawk",
    "material-security", "abnormal-security", "sublime-security",
    "vanta", "drata", "secureframe", "thoropass",

    # ══════════════════════════════════════════════════════════════
    # SaaS / Enterprise / HR / Sales
    # ══════════════════════════════════════════════════════════════
    "salesforce", "hubspot", "twilio",
    "pagerduty", "gusto", "rippling", "deel", "remote", "oyster",
    "lattice", "cultureamp", "15five", "leapsome",
    "gong", "chorus", "outreach", "salesloft",
    "intercom", "drift", "zendesk", "freshworks", "front",
    "contentful", "sanity", "strapi", "prismic",
    "amplitude", "mixpanel", "heap", "fullstory", "logrocket",
    "calendly", "chili-piper", "savvycal",
    "loom", "grain", "fireflies",
    "grammarly", "jasper", "writer",
    "airtable", "clickup", "monday", "basecamp",
    "figma", "pitch", "gamma",

    # ══════════════════════════════════════════════════════════════
    # Data / Analytics / Data Engineering
    # ══════════════════════════════════════════════════════════════
    "databricks", "snowflake", "dbt-labs", "fivetran",
    "airbyte", "prefect", "dagster", "mage",
    "hex", "mode", "sigma", "lightdash",
    "census", "hightouch", "rudderstack",
    "monte-carlo", "bigeye", "anomalo", "soda",
    "atlan", "alation", "collibra",
    "duckdb", "motherduck", "clickhouse", "tinybird",
    "rockset", "imply", "startree",

    # ══════════════════════════════════════════════════════════════
    # Health Tech / Biotech
    # ══════════════════════════════════════════════════════════════
    "veracyte", "tempus", "flatiron", "color",
    "ro", "hims", "cerebral", "springhealth", "talkiatry",
    "benchling", "recursion", "insitro",
    "devoted-health", "clover-health", "oscar",
    "athenahealth", "veeva", "doximity",
    "olive-ai", "viz-ai", "aidoc",

    # ══════════════════════════════════════════════════════════════
    # Autonomous / Robotics / Space / Hardware
    # ══════════════════════════════════════════════════════════════
    "cruise", "aurora", "waymo", "zoox", "nuro",
    "anduril", "shield-ai", "skydio", "zipline",
    "relativity", "astranis", "spire",
    "joby", "archer", "lilium",
    "samsara", "viam", "covariant",

    # ══════════════════════════════════════════════════════════════
    # Real Estate / Climate / Energy
    # ══════════════════════════════════════════════════════════════
    "opendoor", "zillow", "redfin", "compass",
    "watershed", "watershedclimate", "pachama",
    "palmetto", "arcadia", "gridx",

    # ══════════════════════════════════════════════════════════════
    # Education
    # ══════════════════════════════════════════════════════════════
    "coursera", "udemy", "masterclass",
    "brilliant", "kahoot", "quizlet",
    "guild", "springboard", "codecademy",

    # ══════════════════════════════════════════════════════════════
    # Gaming
    # ══════════════════════════════════════════════════════════════
    "roblox", "epicgames", "unity", "riot",
    "supercell", "scopely", "kabam",

    # ══════════════════════════════════════════════════════════════
    # Other Notable / Misc
    # ══════════════════════════════════════════════════════════════
    "palantir", "bloomberg", "squarespace", "webflow",
    "toast", "procore", "servicetitan",
    "calendly", "loom", "mux",
    "navan", "hopper",
    "flexport", "convoyinc", "project44",
    "applied-intuition",
    "ironclad", "icertis", "juro",
    "productboard", "pendo", "gainsight",
    "krisp", "otter-ai", "fathom",
    "axiom", "baselime", "betterstack",
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


async def _check_ashby(client: httpx.AsyncClient, slug: str) -> dict | None:
    """Check if an Ashby board exists and has jobs."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            job_count = len(data.get("jobs", []))
            if job_count > 0:
                return {"slug": slug, "ats": "ashby", "jobs": job_count}
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
    existing_ashby: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """
    Discover Greenhouse, Lever, and Ashby boards from a list of company names.

    Returns:
        dict with: new_greenhouse, new_lever, new_ashby, total_checked, total_found
    """
    companies = companies or TECH_COMPANIES
    existing_greenhouse = set(s.lower() for s in (existing_greenhouse or []))
    existing_lever = set(s.lower() for s in (existing_lever or []))
    existing_ashby = set(s.lower() for s in (existing_ashby or []))

    def update(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # Generate all slugs to check
    all_slugs = set()
    for company in companies:
        for slug in _generate_slugs(company):
            all_slugs.add(slug)

    # Remove already known across all ATS
    known = existing_greenhouse | existing_lever | existing_ashby
    slugs_to_check = all_slugs - known

    update(f"Checking {len(slugs_to_check)} potential slugs from {len(companies)} companies...")

    new_greenhouse = []
    new_lever = []
    new_ashby = []
    checked = 0

    async with httpx.AsyncClient(
        timeout=10,
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    ) as client:
        slug_list = list(slugs_to_check)
        batch_size = 50

        for i in range(0, len(slug_list), batch_size):
            batch = slug_list[i:i + batch_size]

            # Check Greenhouse, Lever, AND Ashby for each slug
            tasks = []
            for slug in batch:
                tasks.append(_check_greenhouse(client, slug))
                tasks.append(_check_lever(client, slug))
                tasks.append(_check_ashby(client, slug))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception) or result is None:
                    continue
                if result["ats"] == "greenhouse" and result["slug"] not in existing_greenhouse:
                    new_greenhouse.append(result)
                    existing_greenhouse.add(result["slug"])
                    update(f"  Found Greenhouse: {result['slug']} ({result['jobs']} jobs)")
                elif result["ats"] == "lever" and result["slug"] not in existing_lever:
                    new_lever.append(result)
                    existing_lever.add(result["slug"])
                    update(f"  Found Lever: {result['slug']} ({result['jobs']} jobs)")
                elif result["ats"] == "ashby" and result["slug"] not in existing_ashby:
                    new_ashby.append(result)
                    existing_ashby.add(result["slug"])
                    update(f"  Found Ashby: {result['slug']} ({result['jobs']} jobs)")

            checked += len(batch)
            update(f"Progress: {checked}/{len(slug_list)} slugs checked...")

            await asyncio.sleep(0.5)

    update(
        f"Discovery complete: {len(new_greenhouse)} Greenhouse, "
        f"{len(new_lever)} Lever, {len(new_ashby)} Ashby"
    )

    return {
        "new_greenhouse": sorted(new_greenhouse, key=lambda x: x["jobs"], reverse=True),
        "new_lever": sorted(new_lever, key=lambda x: x["jobs"], reverse=True),
        "new_ashby": sorted(new_ashby, key=lambda x: x["jobs"], reverse=True),
        "total_checked": checked,
        "total_found": len(new_greenhouse) + len(new_lever) + len(new_ashby),
    }


def discover_boards_sync(
    companies: list[str] | None = None,
    existing_greenhouse: list[str] | None = None,
    existing_lever: list[str] | None = None,
    existing_ashby: list[str] | None = None,
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
                discover_boards(companies, existing_greenhouse, existing_lever, existing_ashby, progress_callback),
            )
            return future.result()
    else:
        return asyncio.run(
            discover_boards(companies, existing_greenhouse, existing_lever, existing_ashby, progress_callback)
        )
