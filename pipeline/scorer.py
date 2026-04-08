"""
Two-stage job scoring: hard filters (free) then AI semantic scoring (API).

Stage 1 eliminates obvious mismatches before spending API credits.
Stage 2 uses the configured AI provider to produce a 0-100 fit score with reasoning.
Scoring runs concurrently (up to 20 parallel API calls) for speed.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.ai_client import chat_completion
from utils.db import get_jobs_by_status, update_job

SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "72"))
MAX_WORKERS = int(os.getenv("SCORE_WORKERS", "20"))
MAX_DESCRIPTION_CHARS = 3000

# Seniority keywords that signal a role is too senior or too junior
SENIOR_KEYWORDS = {"staff", "principal", "distinguished", "director", "vp", "head of", "chief"}
JUNIOR_KEYWORDS = {"intern", "internship", "co-op", "coop", "apprentice"}

# Known staffing, consultancy, and fraud companies to auto-reject
STAFFING_COMPANIES = {
    "infosys", "wipro", "tcs", "cognizant", "hcl", "tech mahindra",
    "capgemini", "accenture federal", "mindtree", "mphasis", "hexaware",
    "cyient", "persistent systems", "ltimindtree", "coforge",
    "robert half", "insight global", "teksystems", "randstad",
    "manpower", "adecco", "kelly services", "kforce", "apex systems",
    "modis", "hays", "collabera", "syntel", "niit technologies",
    "revature", "smoothstack", "fdm group", "cgi group", "cgi",
    "virtusa", "zensar", "birlasoft", "sonata software",
    "ntt data", "atos", "unisys", "dxc technology",
    "staffing", "consulting group", "global consulting",
}

# Patterns in company name or description that indicate staffing/consultancy
STAFFING_PATTERNS = [
    "staffing agency", "staffing company", "staffing firm",
    "consulting firm", "on behalf of our client", "our client is seeking",
    "contract-to-hire", "c2h position", "w2 only", "w2 contract",
    "corp-to-corp", "c2c", "looking for consultants",
    "bench sales", "h1b transfer", "sponsor transfer",
]


def hard_filter(job: dict, profile: dict, prefs: dict) -> tuple[bool, str]:
    """
    Returns (passes, reason). Eliminates obvious mismatches before API scoring.

    Checks:
    - Company blacklist
    - Staffing / consultancy / fraud company detection
    - Seniority mismatch (too senior / too junior)
    - Already processed (status != 'new')
    - Visa: only reject if job EXPLICITLY says no sponsorship
      (no mention of visa = still consider)
    """
    title_lower = job.get("title", "").lower()
    company = job.get("company", "")
    company_lower = company.lower()
    description_lower = (job.get("description") or "").lower()

    # Blacklist check (user-defined)
    blacklist = [c.lower() for c in prefs.get("blacklist_companies", [])]
    if company_lower in blacklist:
        return False, f"Company '{company}' is blacklisted"

    # Staffing / consultancy / fraud company check
    for staffing_name in STAFFING_COMPANIES:
        if staffing_name in company_lower:
            return False, f"'{company}' appears to be a staffing/consultancy company"

    # Staffing patterns in description
    for pattern in STAFFING_PATTERNS:
        if pattern in description_lower:
            return False, f"Job description contains staffing indicator: '{pattern}'"

    # Already processed
    if job.get("status") != "new":
        return False, f"Job already has status '{job.get('status')}'"

    # Too senior
    for kw in SENIOR_KEYWORDS:
        if kw in title_lower:
            allowed_seniority = prefs.get("seniority_levels", [])
            if "staff" not in allowed_seniority and "principal" not in allowed_seniority:
                return False, f"Title contains '{kw}' — too senior for target seniority"

    # Too junior
    for kw in JUNIOR_KEYWORDS:
        if kw in title_lower:
            allowed_seniority = prefs.get("seniority_levels", [])
            if "intern" not in allowed_seniority:
                return False, f"Title contains '{kw}' — too junior"

    # Title relevance — skip jobs that clearly aren't software engineering
    target_keywords = {"software", "engineer", "developer", "swe", "backend",
                        "frontend", "full stack", "fullstack", "full-stack",
                        "web developer", "application developer", "platform engineer",
                        "devops", "sre", "site reliability"}
    title_has_match = any(kw in title_lower for kw in target_keywords)
    if not title_has_match:
        return False, f"Title '{job.get('title')}' doesn't match any target role keywords"

    # Visa sponsorship — ONLY reject if job EXPLICITLY states no sponsorship.
    # Jobs that don't mention visa at all are kept.
    if prefs.get("visa_sponsorship_required", False):
        no_sponsor_patterns = [
            "not able to sponsor", "unable to sponsor", "no visa sponsorship",
            "will not sponsor", "cannot sponsor", "no sponsorship",
            "does not sponsor", "doesn't sponsor", "do not sponsor",
            "not eligible for sponsorship", "without sponsorship",
            "must be a u.s. citizen", "u.s. citizens only",
            "must be a us citizen", "us citizens only",
            "permanent resident required", "green card required",
            "no h1b", "not sponsor h-1b", "no h-1b",
            "must be legally authorized to work in the united states without sponsorship",
            "authorized to work in the u.s. without sponsorship",
            "work authorization required",
            "this position is not eligible for visa sponsorship",
        ]
        for pattern in no_sponsor_patterns:
            if pattern in description_lower:
                return False, f"Explicitly says no sponsorship: '{pattern}'"

    return True, "Passed hard filters"


def _truncate(text: str, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    """Truncate text to max_chars, keeping whole words."""
    if not text or len(text) <= max_chars:
        return text or ""
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated + "..."


# Build the profile summary once and reuse across all scoring calls
_profile_cache: dict = {}


def _get_profile_summary(profile: dict) -> str:
    """Cache the JSON-serialized profile summary to avoid rebuilding per job."""
    cache_key = profile.get("name", "")
    if cache_key not in _profile_cache:
        summary = {
            "name": profile["name"],
            "summary": profile["summary"],
            "years_of_experience": profile["years_of_experience"],
            "current_title": profile["current_title"],
            "target_titles": profile["target_titles"],
            "skills": profile["skills"],
            "experience": [
                {"title": e["title"], "company": e["company"], "bullets": e["bullets"][:3]}
                for e in profile.get("experience", [])
            ],
        }
        _profile_cache[cache_key] = json.dumps(summary, indent=2)
    return _profile_cache[cache_key]


def score_job_with_ai(job: dict, profile: dict) -> dict:
    """
    Call the configured AI provider to semantically score a job against the candidate profile.

    Returns dict with keys: score (int), reason (str), missing (list), strengths (list).
    Raises on API error so caller can handle gracefully.
    """
    profile_json = _get_profile_summary(profile)
    description = _truncate(job.get("description", "No description available"))

    system_prompt = "You are an expert technical recruiter. You evaluate job description fit for software engineers. Always respond with valid JSON only. No explanation outside the JSON."

    user_message = f"""Score how well this candidate matches this job. Return JSON with exactly these fields:
{{
  "score": <integer 0-100>,
  "reason": "<one sentence explaining the score>",
  "missing": ["<skill or experience gap 1>", "<gap 2>"],
  "strengths": ["<matching strength 1>", "<strength 2>"],
  "keywords": ["<top JD keyword 1>", "<top JD keyword 2>", "... up to 10 most important technical keywords/skills from the job description"]
}}

CANDIDATE PROFILE:
{profile_json}

JOB DESCRIPTION:
Title: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
Description: {description}"""

    raw_text = chat_completion(system=system_prompt, user_message=user_message, max_tokens=400)

    # Extract JSON even if wrapped in markdown code fences
    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not json_match:
        raise ValueError(f"Could not parse JSON from API response: {raw_text[:200]}")

    result = json.loads(json_match.group())

    # Validate expected fields
    if "score" not in result or not isinstance(result["score"], int):
        raise ValueError(f"Response missing valid 'score' field: {result}")

    result.setdefault("reason", "")
    result.setdefault("missing", [])
    result.setdefault("strengths", [])
    result.setdefault("keywords", [])

    return result


def _score_one(job: dict, profile: dict) -> tuple[dict, dict | None, Exception | None]:
    """Score a single job with AI. Retries on rate-limit (429) with exponential backoff."""
    max_retries = 4
    for attempt in range(max_retries):
        try:
            result = score_job_with_ai(job, profile)
            return (job, result, None)
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate" in err_str or "too many" in err_str
            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) + (attempt * 0.5)  # 1s, 2.5s, 4.5s
                time.sleep(wait)
                continue
            return (job, None, e)
    return (job, None, Exception("Max retries exceeded"))


def score_all_new_jobs(profile: dict, prefs: dict) -> dict:
    """
    Score all jobs with status='new'. Returns summary stats.

    Flow:
    1. Hard filter ALL jobs first (free, instant) — bulk skip
    2. Score survivors concurrently via ThreadPoolExecutor (up to 20 parallel)
    3. Jobs above threshold → status='queued', below → status='scored'
    """
    from rich.console import Console
    from rich.progress import Progress

    console = Console()
    jobs = get_jobs_by_status("new")

    if not jobs:
        console.print("[yellow]No new jobs to score.[/yellow]")
        return {"total": 0, "filtered_out": 0, "scored": 0, "queued": 0, "errors": 0}

    start_time = time.time()
    console.print(f"\n[bold]Scoring {len(jobs)} new jobs (threshold: {SCORE_THRESHOLD})[/bold]\n")

    stats = {"total": len(jobs), "filtered_out": 0, "scored": 0, "queued": 0, "errors": 0}

    # ── Stage 1: Run ALL hard filters first (free, instant) ──
    console.print("[bold]Stage 1:[/bold] Hard filters...")
    to_score = []
    for job in jobs:
        passes, reason = hard_filter(job, profile, prefs)
        if not passes:
            update_job(job["id"], status="skipped", score_reason=f"[FILTER] {reason}")
            stats["filtered_out"] += 1
        else:
            to_score.append(job)

    console.print(f"  {stats['filtered_out']} filtered out, [green]{len(to_score)} advancing to AI scoring[/green]\n")

    if not to_score:
        console.print("[yellow]No jobs passed hard filters.[/yellow]")
        return stats

    # ── Stage 2: Score concurrently ──
    console.print(f"[bold]Stage 2:[/bold] AI scoring ({len(to_score)} jobs, {MAX_WORKERS} parallel workers)...")

    with Progress() as progress:
        task = progress.add_task("Scoring with AI...", total=len(to_score))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_score_one, job, profile): job
                for job in to_score
            }

            for future in as_completed(futures):
                job, result, error = future.result()

                if error:
                    console.print(
                        f"  [red]ERROR[/red] {job['title']} at {job['company']}: {error}"
                    )
                    update_job(job["id"], score_reason=f"[ERROR] {str(error)}")
                    stats["errors"] += 1
                else:
                    score = result["score"]
                    reason = result["reason"]
                    new_status = "queued" if score >= SCORE_THRESHOLD else "scored"

                    update_job(
                        job["id"],
                        score=score,
                        score_reason=reason,
                        status=new_status,
                        notes=json.dumps({
                            "missing": result.get("missing", []),
                            "strengths": result.get("strengths", []),
                            "keywords": result.get("keywords", []),
                        }),
                    )

                    if new_status == "queued":
                        stats["queued"] += 1
                        console.print(
                            f"  [green]QUEUED[/green] {score}/100 — {job['title']} at {job['company']}"
                        )
                    else:
                        stats["scored"] += 1

                progress.advance(task)

    elapsed = time.time() - start_time
    console.print(f"\n[bold]Scoring complete in {elapsed:.1f}s:[/bold]")
    console.print(f"  {stats['filtered_out']} filtered out  |  {stats['queued']} queued  |  {stats['scored']} below threshold  |  {stats['errors']} errors")

    return stats
