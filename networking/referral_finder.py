"""
Referral finder — matches your LinkedIn connections to job companies.

Two-tier system:
1. INSTANT (offline): Match cached 1st-degree connections to company names
2. ON-DEMAND (API): Search 2nd-degree + recruiters at a specific company
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_referral_tables():
    """Create tables for connection cache and referral contacts."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS linkedin_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                headline TEXT,
                company TEXT,
                public_id TEXT,
                linkedin_url TEXT,
                synced_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_connections_company
                ON linkedin_connections(company COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS referral_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT REFERENCES jobs(id),
                company TEXT NOT NULL,
                contact_name TEXT,
                contact_title TEXT,
                contact_linkedin_url TEXT,
                connection_degree INTEGER DEFAULT 1,
                contact_type TEXT DEFAULT 'connection',
                outreach_status TEXT DEFAULT 'pending',
                found_at TEXT NOT NULL,
                notes TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_referrals_job
                ON referral_contacts(job_id);

            CREATE TABLE IF NOT EXISTS company_id_cache (
                company_name TEXT PRIMARY KEY,
                linkedin_id TEXT,
                cached_at TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Connection Sync (one-time bulk fetch)
# ──────────────────────────────────────────────────────────────

def sync_connections(progress_callback=None) -> dict:
    """Fetch all LinkedIn connections and cache them locally.

    Returns: {total, new, updated}
    """
    from networking.linkedin_client import LinkedInClient

    init_referral_tables()

    client = LinkedInClient()
    connections = client.fetch_all_connections(progress_callback=progress_callback)
    client.close()

    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    updated = 0

    try:
        # Clear old data and re-insert (simple full sync)
        conn.execute("DELETE FROM linkedin_connections")

        for c in connections:
            conn.execute(
                """INSERT INTO linkedin_connections
                   (name, headline, company, public_id, linkedin_url, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (c["name"], c["headline"], c["company"], c["public_id"], c["linkedin_url"], now),
            )
            new_count += 1

        conn.commit()
    finally:
        conn.close()

    return {"total": new_count, "new": new_count, "updated": updated}


def get_sync_status() -> dict:
    """Check when connections were last synced and how many are cached."""
    init_referral_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt, MAX(synced_at) as last_sync FROM linkedin_connections"
        ).fetchone()
        return {
            "count": row["cnt"],
            "last_sync": row["last_sync"],
            "synced": row["cnt"] > 0,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Instant Matching (offline, zero API calls)
# ──────────────────────────────────────────────────────────────

def find_connections_at_company(company_name: str) -> list[dict]:
    """Find 1st-degree connections at a company (from local cache).

    Uses fuzzy matching — checks if the company name appears in the
    connection's company or headline field.
    """
    if not company_name:
        return []

    init_referral_tables()
    conn = _get_conn()

    company_lower = company_name.lower().strip()

    # Also try common variations
    variations = {company_lower}
    # "Stripe Inc" → also try "Stripe"
    for suffix in [" inc", " inc.", " llc", " ltd", " corp", " co"]:
        if company_lower.endswith(suffix):
            variations.add(company_lower[:-len(suffix)].strip())
    # Add the base name
    variations.add(company_lower.split()[0] if company_lower else "")

    try:
        results = []
        seen_names = set()

        for variant in variations:
            if not variant or len(variant) < 2:
                continue

            rows = conn.execute(
                """SELECT name, headline, company, public_id, linkedin_url
                   FROM linkedin_connections
                   WHERE LOWER(company) LIKE ? OR LOWER(headline) LIKE ?
                   LIMIT 20""",
                (f"%{variant}%", f"%{variant}%"),
            ).fetchall()

            for row in rows:
                if row["name"] in seen_names:
                    continue
                seen_names.add(row["name"])

                # Determine contact type from headline
                headline_lower = (row["headline"] or "").lower()
                contact_type = "connection"
                if any(kw in headline_lower for kw in ["recruiter", "recruiting", "talent", "sourcer", "hiring"]):
                    contact_type = "recruiter"
                elif any(kw in headline_lower for kw in ["manager", "director", "lead", "head of"]):
                    contact_type = "hiring_manager"

                results.append({
                    "name": row["name"],
                    "headline": row["headline"],
                    "company": row["company"],
                    "linkedin_url": row["linkedin_url"],
                    "connection_degree": 1,
                    "contact_type": contact_type,
                })

        # Sort: recruiters first, then hiring managers, then connections
        type_order = {"recruiter": 0, "hiring_manager": 1, "connection": 2}
        results.sort(key=lambda x: type_order.get(x["contact_type"], 9))

        return results

    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# On-Demand Search (API call — use sparingly)
# ──────────────────────────────────────────────────────────────

def _get_cached_company_id(company_name: str) -> str | None:
    """Check if we have a cached LinkedIn company ID."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT linkedin_id FROM company_id_cache WHERE company_name = ?",
            (company_name.lower(),),
        ).fetchone()
        return row["linkedin_id"] if row else None
    finally:
        conn.close()


def _cache_company_id(company_name: str, linkedin_id: str):
    """Cache a company's LinkedIn ID."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO company_id_cache (company_name, linkedin_id, cached_at) VALUES (?, ?, ?)",
            (company_name.lower(), linkedin_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def search_deep_connections(company_name: str) -> dict:
    """On-demand deep search — find 2nd-degree connections and recruiters.

    Makes 2-3 LinkedIn API calls. Use sparingly (max 5-10 per day).

    Returns: {connections: [...], recruiters: [...], company_id: str}
    """
    from networking.linkedin_client import LinkedInClient

    result = {"connections": [], "recruiters": [], "company_id": None}

    client = LinkedInClient()

    try:
        # Get company ID (check cache first)
        company_slug = company_name.lower().replace(" ", "").replace(",", "").replace(".", "")
        company_id = _get_cached_company_id(company_name)

        if not company_id:
            # Try a few slug variations
            for slug in [company_slug, company_name.lower().replace(" ", "-"), company_name.lower().split()[0]]:
                company_id = client.get_company_id(slug)
                if company_id:
                    _cache_company_id(company_name, company_id)
                    break
                client._sleep()

        if not company_id:
            logger.warning(f"Could not find LinkedIn company ID for '{company_name}'")
            return result

        result["company_id"] = company_id

        # Search 1st + 2nd degree connections at company
        client._sleep()
        people = client.search_people_at_company(company_id, network_depth="F,S", count=10)
        result["connections"] = people

        # Search recruiters
        client._sleep()
        recruiters = client.search_recruiters_at_company(company_id, count=5)
        result["recruiters"] = recruiters

    except Exception as e:
        logger.error(f"Deep search failed for '{company_name}': {e}")
    finally:
        client.close()

    return result


def get_referrals_for_job(job: dict) -> dict:
    """Get all referral suggestions for a job.

    First checks local cache (instant), then returns what we have.
    Does NOT make API calls — use search_deep_connections() separately.

    Returns: {connections: [...], has_connections: bool, sync_status: {...}}
    """
    company = job.get("company", "")
    connections = find_connections_at_company(company)
    sync_status = get_sync_status()

    return {
        "connections": connections[:10],
        "has_connections": len(connections) > 0,
        "connection_count": len(connections),
        "sync_status": sync_status,
    }
