"""
SQLite database helpers for the job application pipeline.

All database interactions go through this module. The database file lives at
data/jobs.db and is auto-created on first access.
"""

import sqlite3
import os
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database, creating it if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create the jobs and applications tables if they don't already exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT UNIQUE NOT NULL,
                source TEXT,
                description TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                date_posted TEXT,
                date_scraped TEXT NOT NULL,
                score INTEGER,
                score_reason TEXT,
                status TEXT DEFAULT 'new',
                cover_letter TEXT,
                resume_bullets TEXT,
                date_submitted TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT REFERENCES jobs(id),
                submitted_at TEXT,
                confirmation_text TEXT,
                follow_up_date TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def insert_job(job: dict) -> bool:
    """
    Insert a single job into the database.
    Returns True if inserted, False if the URL already exists (dedup).
    """
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO jobs
               (id, title, company, location, url, source, description,
                salary_min, salary_max, date_posted, date_scraped, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job["id"],
                job["title"],
                job["company"],
                job.get("location"),
                job["url"],
                job.get("source"),
                job.get("description"),
                job.get("salary_min"),
                job.get("salary_max"),
                job.get("date_posted"),
                job.get("date_scraped", datetime.now(timezone.utc).isoformat()),
                job.get("status", "new"),
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def insert_jobs(jobs: list[dict]) -> int:
    """
    Bulk-insert jobs, skipping duplicates.
    Returns the count of newly inserted jobs.
    """
    inserted = 0
    conn = get_connection()
    try:
        for job in jobs:
            try:
                conn.execute(
                    """INSERT INTO jobs
                       (id, title, company, location, url, source, description,
                        salary_min, salary_max, date_posted, date_scraped, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job["id"],
                        job["title"],
                        job["company"],
                        job.get("location"),
                        job["url"],
                        job.get("source"),
                        job.get("description"),
                        job.get("salary_min"),
                        job.get("salary_max"),
                        job.get("date_posted"),
                        job.get("date_scraped", datetime.now(timezone.utc).isoformat()),
                        job.get("status", "new"),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                continue
        conn.commit()
    finally:
        conn.close()
    return inserted


def get_jobs_by_status(status: str) -> list[dict]:
    """Return all jobs with the given status as a list of dicts."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC NULLS LAST, date_scraped DESC",
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_job_by_id(job_id: str) -> dict | None:
    """Return a single job by its ID, or None."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job(job_id: str, **fields) -> None:
    """
    Update arbitrary fields on a job row.
    Usage: update_job("abc123", score=85, status="scored")
    """
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    values.append(job_id)
    conn = get_connection()
    try:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def url_exists(url: str) -> bool:
    """Check whether a job URL is already in the database."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_existing_urls() -> set[str]:
    """Return all job URLs currently in the database as a set for fast lookups."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT url FROM jobs").fetchall()
        return {row["url"] for row in rows}
    finally:
        conn.close()


def get_contract_jobs() -> list[dict]:
    """Return jobs likely involving contract/W2/C2C work, excluding skipped/submitted."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM jobs
               WHERE (LOWER(title) LIKE '%contract%' OR LOWER(description) LIKE '%contract%'
                      OR LOWER(description) LIKE '%w2%' OR LOWER(description) LIKE '%w-2%'
                      OR LOWER(title) LIKE '%c2c%' OR LOWER(description) LIKE '%corp to corp%')
                 AND status NOT IN ('skipped', 'submitted')
               ORDER BY score DESC NULLS LAST, date_scraped DESC"""
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_queued_without_cl() -> list[dict]:
    """Return queued jobs that do NOT have a cover letter."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' AND (cover_letter IS NULL OR cover_letter = '') "
            "ORDER BY score DESC, date_scraped DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_queued_with_cl() -> list[dict]:
    """Return queued jobs that HAVE a cover letter."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' AND cover_letter IS NOT NULL AND cover_letter != '' "
            "ORDER BY score DESC, date_scraped DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Application helpers
# ---------------------------------------------------------------------------

def insert_application(job_id: str, confirmation_text: str = "") -> int:
    """
    Record a submitted application. Returns the new application row ID.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO applications (job_id, submitted_at, confirmation_text)
               VALUES (?, ?, ?)""",
            (job_id, now, confirmation_text),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def count_by_status() -> dict[str, int]:
    """Return a dict mapping each status to its job count."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}
    finally:
        conn.close()


def count_today(status: str | None = None) -> int:
    """Count jobs scraped today, optionally filtered by status."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE date_scraped LIKE ? AND status = ?",
                (f"{today}%", status),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE date_scraped LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def count_this_week(status: str | None = None) -> int:
    """Count jobs from the last 7 days, optionally filtered by status."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conn = get_connection()
    try:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE date_scraped >= ? AND status = ?",
                (cutoff, status),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE date_scraped >= ?",
                (cutoff,),
            ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def export_to_csv(filepath: str) -> int:
    """Export all jobs to a CSV file. Returns row count."""
    import csv
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY date_scraped DESC").fetchall()
        if not rows:
            return 0
        keys = rows[0].keys()
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return len(rows)
    finally:
        conn.close()
