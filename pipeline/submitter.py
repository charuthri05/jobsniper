"""
Playwright-based auto-fill for ATS application forms.

Supports Greenhouse, Lever, and generic forms. Detects the ATS type from the URL,
navigates to the application page, and pre-fills all recognized fields.

Runs with headless=False so the candidate can review and submit manually.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "submissions.log"),
    level=logging.INFO,
    format="%(asctime)s — %(message)s",
)
logger = logging.getLogger("submitter")


def _load_profile() -> dict:
    """Load candidate profile for form filling."""
    from utils.profile import load_profile
    return load_profile()


def _detect_ats(url: str) -> str:
    """Detect the ATS type from a job URL."""
    if "greenhouse.io" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "myworkdayjobs.com" in url or "workday.com" in url:
        return "workday"
    if "icims.com" in url:
        return "icims"
    if "ashbyhq.com" in url:
        return "ashby"
    return "generic"


# ---------------------------------------------------------------------------
# Field filling helpers
# ---------------------------------------------------------------------------

async def _try_fill(page, selector: str, value: str) -> bool:
    """Try to fill a field. Returns True if found and filled."""
    if not value:
        return False
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            await el.scroll_into_view_if_needed(timeout=2000)
            await el.fill(value)
            return True
    except Exception:
        pass
    return False


async def _try_fill_by_label(page, label_text: str, value: str) -> bool:
    """Try to find an input by its label text and fill it."""
    if not value:
        return False
    try:
        # Find label containing text, then find associated input
        label = page.locator(f'label:has-text("{label_text}")').first
        if await label.count() > 0:
            for_attr = await label.get_attribute("for")
            if for_attr:
                field = page.locator(f"#{for_attr}")
                if await field.count() > 0:
                    await field.fill(value)
                    return True
            # Try sibling/child input
            field = label.locator(".. input, .. textarea").first
            if await field.count() > 0:
                await field.fill(value)
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# ATS-specific fillers
# ---------------------------------------------------------------------------

async def _fill_greenhouse(page, profile: dict, cover_letter: str) -> dict:
    """Fill a Greenhouse application form."""
    name_parts = profile["name"].split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    filled = {}

    # Greenhouse uses id-based fields on their hosted forms
    field_map = [
        ('input[name*="first_name"], input[id*="first_name"], #first_name', first_name, "First Name"),
        ('input[name*="last_name"], input[id*="last_name"], #last_name', last_name, "Last Name"),
        ('input[name*="email"], input[type="email"], #email', profile.get("email", ""), "Email"),
        ('input[name*="phone"], input[type="tel"], #phone', profile.get("phone", ""), "Phone"),
        ('input[name*="linkedin"], input[id*="linkedin"]', profile.get("linkedin", ""), "LinkedIn"),
        ('input[name*="github"], input[name*="website"], input[name*="portfolio"], input[id*="github"]', profile.get("github", ""), "GitHub/Website"),
        ('input[name*="location"], input[id*="location"]', profile.get("location", ""), "Location"),
    ]

    for selector, value, name in field_map:
        if await _try_fill(page, selector, value):
            filled[name] = value

    # Cover letter — textarea
    if cover_letter:
        cl_selectors = 'textarea[name*="cover_letter"], textarea[id*="cover_letter"], textarea[name*="cover"], textarea[aria-label*="cover letter"]'
        if await _try_fill(page, cl_selectors, cover_letter):
            filled["Cover Letter"] = f"({len(cover_letter)} chars)"

    # Try label-based fallbacks for any missing fields
    label_fallbacks = [
        ("First Name", first_name, "First Name"),
        ("Last Name", last_name, "Last Name"),
        ("Email", profile.get("email", ""), "Email"),
        ("Phone", profile.get("phone", ""), "Phone"),
        ("LinkedIn", profile.get("linkedin", ""), "LinkedIn"),
        ("GitHub", profile.get("github", ""), "GitHub/Website"),
        ("Website", profile.get("github", ""), "GitHub/Website"),
        ("Location", profile.get("location", ""), "Location"),
        ("City", profile.get("location", ""), "Location"),
    ]

    for label, value, name in label_fallbacks:
        if name not in filled:
            if await _try_fill_by_label(page, label, value):
                filled[name] = value

    return filled


async def _fill_lever(page, profile: dict, cover_letter: str) -> dict:
    """Fill a Lever application form."""
    filled = {}

    # Lever uses specific card-based form structure
    field_map = [
        ('input[name="name"]', profile["name"], "Full Name"),
        ('input[name="email"]', profile.get("email", ""), "Email"),
        ('input[name="phone"]', profile.get("phone", ""), "Phone"),
        ('input[name="org"]', "", "Current Company"),
        ('input[name="urls[LinkedIn]"], input[name*="linkedin"]', profile.get("linkedin", ""), "LinkedIn"),
        ('input[name="urls[GitHub]"], input[name*="github"]', profile.get("github", ""), "GitHub"),
        ('input[name="urls[Portfolio]"], input[name*="portfolio"], input[name*="website"]', profile.get("github", ""), "Portfolio"),
    ]

    for selector, value, name in field_map:
        if await _try_fill(page, selector, value):
            filled[name] = value

    # Cover letter / additional info — Lever uses a textarea at the bottom
    if cover_letter:
        cl_selectors = 'textarea[name="comments"], textarea[name="additional"], textarea[name*="cover"]'
        if await _try_fill(page, cl_selectors, cover_letter):
            filled["Additional Info / Cover Letter"] = f"({len(cover_letter)} chars)"

    # Label-based fallbacks
    label_fallbacks = [
        ("Full name", profile["name"], "Full Name"),
        ("Email", profile.get("email", ""), "Email"),
        ("Phone", profile.get("phone", ""), "Phone"),
        ("LinkedIn", profile.get("linkedin", ""), "LinkedIn"),
        ("GitHub", profile.get("github", ""), "GitHub"),
    ]

    for label, value, name in label_fallbacks:
        if name not in filled:
            if await _try_fill_by_label(page, label, value):
                filled[name] = value

    return filled


async def _fill_generic(page, profile: dict, cover_letter: str) -> dict:
    """Fill a generic application form by matching common field patterns."""
    name_parts = profile["name"].split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    filled = {}

    # Try by name/id attributes first
    generic_fields = [
        ('input[name*="first" i][name*="name" i], input[id*="first" i][id*="name" i], input[autocomplete="given-name"]', first_name, "First Name"),
        ('input[name*="last" i][name*="name" i], input[id*="last" i][id*="name" i], input[autocomplete="family-name"]', last_name, "Last Name"),
        ('input[name*="full" i][name*="name" i], input[name="name"], input[autocomplete="name"]', profile["name"], "Full Name"),
        ('input[type="email"], input[name*="email" i], input[autocomplete="email"]', profile.get("email", ""), "Email"),
        ('input[type="tel"], input[name*="phone" i], input[autocomplete="tel"]', profile.get("phone", ""), "Phone"),
        ('input[name*="linkedin" i], input[id*="linkedin" i]', profile.get("linkedin", ""), "LinkedIn"),
        ('input[name*="github" i], input[name*="portfolio" i], input[name*="website" i]', profile.get("github", ""), "GitHub/Website"),
        ('input[name*="location" i], input[name*="city" i], input[autocomplete="address-level2"]', profile.get("location", ""), "Location"),
    ]

    for selector, value, name in generic_fields:
        if await _try_fill(page, selector, value):
            filled[name] = value

    # Cover letter — any large textarea
    if cover_letter:
        cl_selectors = 'textarea[name*="cover" i], textarea[name*="letter" i], textarea[name*="additional" i], textarea[name*="comment" i]'
        if await _try_fill(page, cl_selectors, cover_letter):
            filled["Cover Letter"] = f"({len(cover_letter)} chars)"

    # Label-based fallbacks
    label_attempts = [
        ("First Name", first_name), ("First name", first_name),
        ("Last Name", last_name), ("Last name", last_name),
        ("Full Name", profile["name"]), ("Full name", profile["name"]), ("Name", profile["name"]),
        ("Email", profile.get("email", "")), ("E-mail", profile.get("email", "")),
        ("Phone", profile.get("phone", "")), ("Phone Number", profile.get("phone", "")),
        ("LinkedIn", profile.get("linkedin", "")), ("LinkedIn URL", profile.get("linkedin", "")),
        ("GitHub", profile.get("github", "")), ("Website", profile.get("github", "")), ("Portfolio", profile.get("github", "")),
        ("Location", profile.get("location", "")), ("City", profile.get("location", "")),
    ]

    for label, value in label_attempts:
        if await _try_fill_by_label(page, label, value):
            # Determine field name from label
            name = label.split()[0] if " " not in label else label
            if name not in filled:
                filled[name] = value

    return filled


# ---------------------------------------------------------------------------
# Main auto-fill function
# ---------------------------------------------------------------------------

async def _autofill_job(page, job: dict, profile: dict) -> dict:
    """Navigate to a job's application page and auto-fill the form.

    Returns dict with: ats_type, filled_fields, status, screenshot.
    Does NOT submit — leaves the form filled for user to review and submit.
    """
    url = job["url"]
    ats_type = _detect_ats(url)
    cover_letter = job.get("cover_letter", "") or ""
    result = {"ats_type": ats_type, "filled": {}, "status": "pending", "screenshot": ""}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # For Greenhouse, click "Apply" button if we're on the job listing page
        if ats_type == "greenhouse":
            apply_btn = page.locator('a:has-text("Apply"), button:has-text("Apply for this job"), a[href*="#app"]').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await page.wait_for_timeout(1500)

        # For Lever, navigate to the /apply page
        if ats_type == "lever" and "/apply" not in url:
            apply_url = url.rstrip("/") + "/apply"
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

        # Fill based on ATS type
        if ats_type == "greenhouse":
            result["filled"] = await _fill_greenhouse(page, profile, cover_letter)
        elif ats_type == "lever":
            result["filled"] = await _fill_lever(page, profile, cover_letter)
        else:
            result["filled"] = await _fill_generic(page, profile, cover_letter)

        # Take screenshot
        screenshot_path = str(LOG_DIR / f"fill_{job['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        await page.screenshot(path=screenshot_path, full_page=False)
        result["screenshot"] = screenshot_path
        result["status"] = "filled"

        logger.info(
            f"FILLED: {job.get('title', '')} at {job.get('company', '')} | "
            f"ATS: {ats_type} | Fields: {list(result['filled'].keys())} | URL: {url}"
        )

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(
            f"FILL ERROR: {job.get('title', '')} at {job.get('company', '')} | "
            f"ATS: {ats_type} | Error: {e} | URL: {url}"
        )

    return result


async def autofill_batch(job_ids: list[str], progress_callback=None):
    """Open a browser and auto-fill application forms for multiple jobs.

    Opens each job in a new tab, fills the form, and leaves all tabs open
    for the user to review and submit manually.

    Args:
        job_ids: List of job IDs to auto-fill.
        progress_callback: Optional function(current, total, job, result) for progress updates.

    Returns list of results.
    """
    from playwright.async_api import async_playwright

    profile = _load_profile()
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        for i, job_id in enumerate(job_ids):
            from utils.db import get_job_by_id
            job = get_job_by_id(job_id)
            if not job:
                results.append({"job_id": job_id, "status": "not_found"})
                if progress_callback:
                    progress_callback(i + 1, len(job_ids), None, {"status": "not_found"})
                continue

            # Open a new tab for each job
            page = await context.new_page()

            result = await _autofill_job(page, job, profile)
            result["job_id"] = job_id
            result["title"] = job.get("title", "")
            result["company"] = job.get("company", "")
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, len(job_ids), job, result)

        # Keep browser open for user to review — wait until user closes it
        if results:
            logger.info(f"BATCH FILL: {len(results)} jobs filled. Browser left open for review.")
            # Wait for browser to be closed by the user
            try:
                await browser.wait_for_event("disconnected", timeout=0)
            except Exception:
                pass

    return results


def autofill_jobs_sync(job_ids: list[str], progress_callback=None) -> list[dict]:
    """Synchronous wrapper for autofill_batch."""
    return asyncio.run(autofill_batch(job_ids, progress_callback))


# ---------------------------------------------------------------------------
# Legacy single-job submit (kept for CLI review command)
# ---------------------------------------------------------------------------

def submit_application(job: dict) -> dict:
    """Submit a single job application via Playwright (CLI use)."""
    profile = _load_profile()
    cover_letter = job.get("cover_letter", "")

    result = asyncio.run(_autofill_single_and_wait(job, profile, cover_letter))
    return result


async def _autofill_single_and_wait(job: dict, profile: dict, cover_letter: str) -> dict:
    """Open a single job, auto-fill, and wait for user to close browser."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        result = await _autofill_job(page, job, profile)

        print(f"\n  Auto-filled {len(result.get('filled', {}))} fields ({result['ats_type']})")
        for field, value in result.get("filled", {}).items():
            print(f"    {field}: {value}")
        print("\n  Review the form and submit manually. Close the browser when done.")

        try:
            await browser.wait_for_event("disconnected", timeout=0)
        except Exception:
            pass

    result["confirmation"] = "Form auto-filled. User reviewed and submitted manually."
    return result
