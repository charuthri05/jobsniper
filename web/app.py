"""
Flask web dashboard for the job application pipeline.

Provides a modern UI to browse jobs, select for cover letter generation,
review generated content, and bulk-submit applications.
"""

import json
import os
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response, send_file

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.db import (
    init_db, get_job_by_id, get_jobs_by_status,
    get_queued_without_cl, get_queued_with_cl,
    update_job, count_by_status, get_contract_jobs,
)
from utils.profile import (
    load_profile, save_profile, validate_profile,
    load_preferences, save_preferences,
    get_default_profile, get_default_preferences,
    PROFILE_PATH, PREFERENCES_PATH,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """Main dashboard page."""
    counts = count_by_status()
    return render_template("dashboard.html", counts=counts)


@app.route("/apply/<job_id>")
def apply_page(job_id):
    """Per-job application helper page with all fields ready to copy."""
    job = get_job_by_id(job_id)
    if not job:
        return "Job not found", 404

    profile = load_profile()
    name_parts = profile["name"].split(" ", 1)

    notes = {}
    if job.get("notes"):
        try:
            notes = json.loads(job["notes"])
        except (json.JSONDecodeError, TypeError):
            pass

    bullets = []
    if job.get("resume_bullets"):
        try:
            bullets = json.loads(job["resume_bullets"])
        except (json.JSONDecodeError, TypeError):
            pass

    return render_template("apply.html",
        job=job,
        profile=profile,
        first_name=name_parts[0],
        last_name=name_parts[1] if len(name_parts) > 1 else "",
        strengths=notes.get("strengths", []),
        missing=notes.get("missing", []),
        bullets=bullets,
    )


@app.route("/setup")
def setup_page():
    """Profile and preferences setup page."""
    return render_template("setup.html")


# ---------------------------------------------------------------------------
# API — Profile & Preferences
# ---------------------------------------------------------------------------

@app.route("/api/profile/full")
def api_profile_full():
    """Return the full candidate profile and preferences for the setup form.
    Falls back to baked-in defaults so a fresh clone is pre-filled."""
    profile = None
    try:
        profile = load_profile()
    except (FileNotFoundError, ValueError):
        pass

    try:
        preferences = load_preferences()
    except Exception:
        preferences = get_default_preferences()

    return jsonify({
        "exists": profile is not None,
        "profile": profile if profile else get_default_profile(),
        "preferences": preferences,
    })


@app.route("/api/profile/full", methods=["POST"])
def api_save_profile_full():
    """Save candidate profile and preferences from the setup form."""
    data = request.get_json()
    profile = data.get("profile")
    preferences = data.get("preferences")

    if not profile:
        return jsonify({"error": "Profile data is required"}), 400

    try:
        validate_profile(profile)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    save_profile(profile)
    if preferences:
        save_preferences(preferences)

    init_db()
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# API — Scrape
# ---------------------------------------------------------------------------

_scrape_progress = {
    "current": 0, "total": 4, "status": "idle", "message": "", "stats": None
}


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger job scraping in a background thread."""
    if _scrape_progress["status"] == "running":
        return jsonify({"error": "Scrape already in progress"}), 409

    _scrape_progress["current"] = 0
    _scrape_progress["total"] = 4
    _scrape_progress["status"] = "running"
    _scrape_progress["message"] = "Starting scrapers..."
    _scrape_progress["stats"] = None

    def run_scrape():
        from pipeline.normalizer import normalize_and_insert
        init_db()
        prefs = load_preferences()
        all_jobs = []

        # Step 1: ATS (Greenhouse + Lever)
        _scrape_progress["current"] = 1
        _scrape_progress["message"] = "Fetching from Greenhouse & Lever boards..."
        try:
            from scrapers.ats_scraper import fetch_all_ats_jobs
            ats_jobs = fetch_all_ats_jobs(prefs)
            all_jobs.extend(ats_jobs)
            _scrape_progress["message"] = f"ATS: {len(ats_jobs)} jobs fetched"
        except Exception as e:
            _scrape_progress["message"] = f"ATS error: {e}"

        # Step 2: Hiring Cafe
        _scrape_progress["current"] = 2
        _scrape_progress["message"] = "Fetching from Hiring Cafe..."
        try:
            from scrapers.hiringcafe_scraper import fetch_hiringcafe_jobs
            hc_jobs = fetch_hiringcafe_jobs(prefs)
            all_jobs.extend(hc_jobs)
            _scrape_progress["message"] = f"Hiring Cafe: {len(hc_jobs)} jobs fetched"
        except Exception as e:
            _scrape_progress["message"] = f"Hiring Cafe error: {e}"

        # Step 3: JobSpy
        _scrape_progress["current"] = 3
        _scrape_progress["message"] = "Fetching from job boards (LinkedIn, Indeed, etc.)..."
        try:
            from scrapers.jobspy_scraper import scrape_major_boards
            jobspy_jobs = scrape_major_boards(prefs)
            all_jobs.extend(jobspy_jobs)
            _scrape_progress["message"] = f"JobSpy: {len(jobspy_jobs)} jobs fetched"
        except Exception as e:
            _scrape_progress["message"] = f"JobSpy error: {e}"

        # Step 4: Normalize and insert
        _scrape_progress["current"] = 4
        _scrape_progress["message"] = "Normalizing and deduplicating..."
        try:
            stats = normalize_and_insert(all_jobs)
            _scrape_progress["stats"] = stats
            _scrape_progress["message"] = (
                f"Done: {stats['new']} new jobs added, "
                f"{stats['duplicates']} duplicates skipped"
            )
        except Exception as e:
            _scrape_progress["message"] = f"Normalize error: {e}"

        _scrape_progress["status"] = "done"

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/scrape/progress")
def api_scrape_progress():
    """SSE endpoint for scrape progress."""
    def stream():
        import time
        while True:
            data = json.dumps(_scrape_progress)
            yield f"data: {data}\n\n"
            if _scrape_progress["status"] in ("done", "idle"):
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# API — Score
# ---------------------------------------------------------------------------

_score_progress = {
    "current": 0, "total": 0, "status": "idle", "message": "", "stats": None
}


@app.route("/api/score", methods=["POST"])
def api_score():
    """Trigger job scoring in a background thread."""
    if _score_progress["status"] == "running":
        return jsonify({"error": "Scoring already in progress"}), 409

    _score_progress["current"] = 0
    _score_progress["total"] = 2
    _score_progress["status"] = "running"
    _score_progress["message"] = "Starting scorer..."
    _score_progress["stats"] = None

    def run_score():
        from pipeline.scorer import score_all_new_jobs
        init_db()
        profile = load_profile()
        prefs = load_preferences()

        # Step 1: Hard filters
        _score_progress["current"] = 1
        _score_progress["message"] = "Running hard filters and AI scoring..."

        try:
            stats = score_all_new_jobs(profile, prefs)
            _score_progress["current"] = 2
            _score_progress["stats"] = stats
            _score_progress["message"] = (
                f"Done: {stats.get('queued', 0)} queued, "
                f"{stats.get('scored', 0)} scored, "
                f"{stats.get('filtered_out', 0)} filtered out, "
                f"{stats.get('errors', 0)} errors"
            )
        except Exception as e:
            _score_progress["message"] = f"Scoring error: {e}"

        _score_progress["status"] = "done"

    thread = threading.Thread(target=run_score, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/score/progress")
def api_score_progress():
    """SSE endpoint for score progress."""
    def stream():
        import time
        while True:
            data = json.dumps(_score_progress)
            yield f"data: {data}\n\n"
            if _score_progress["status"] in ("done", "idle"):
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# API — Job listing
# ---------------------------------------------------------------------------

def _job_to_dict(job: dict) -> dict:
    """Convert a job row to a JSON-safe dict for the frontend."""
    notes = {}
    if job.get("notes"):
        try:
            notes = json.loads(job["notes"])
        except (json.JSONDecodeError, TypeError):
            pass

    bullets = []
    if job.get("resume_bullets"):
        try:
            bullets = json.loads(job["resume_bullets"])
        except (json.JSONDecodeError, TypeError):
            pass

    resume_pdf_path = str(PROJECT_ROOT / "data" / "resumes" / f"{job['id']}.pdf")

    return {
        "id": job["id"],
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "score": job.get("score"),
        "score_reason": job.get("score_reason", ""),
        "status": job.get("status", ""),
        "has_cover_letter": bool(job.get("cover_letter")),
        "cover_letter": job.get("cover_letter", ""),
        "resume_bullets": bullets,
        "strengths": notes.get("strengths", []),
        "missing": notes.get("missing", []),
        "keywords": notes.get("keywords", []),
        "description": job.get("description", ""),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "date_posted": job.get("date_posted", ""),
        "date_scraped": job.get("date_scraped", ""),
        "has_resume": os.path.exists(resume_pdf_path),
    }


@app.route("/api/jobs")
def api_jobs():
    """Fetch jobs by tab: queued, ready, submitted, skipped, new, scored, contract."""
    tab = request.args.get("tab", "queued")

    if tab == "queued":
        jobs = get_queued_without_cl()
    elif tab == "ready":
        jobs = get_queued_with_cl()
    elif tab == "submitted":
        jobs = get_jobs_by_status("submitted")
    elif tab == "skipped":
        jobs = get_jobs_by_status("skipped")
    elif tab == "new":
        jobs = get_jobs_by_status("new")
    elif tab == "scored":
        jobs = get_jobs_by_status("scored")
    elif tab == "contract":
        jobs = get_contract_jobs()
    else:
        jobs = get_jobs_by_status("queued")

    return jsonify([_job_to_dict(j) for j in jobs])


@app.route("/api/job/<job_id>")
def api_job_detail(job_id):
    """Get full details for a single job."""
    job = get_job_by_id(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(_job_to_dict(job))


@app.route("/api/stats")
def api_stats():
    """Get job counts by status."""
    counts = count_by_status()
    queued_no_cl = len(get_queued_without_cl())
    queued_with_cl = len(get_queued_with_cl())
    contract_count = len(get_contract_jobs())
    return jsonify({
        "queued": queued_no_cl,
        "ready": queued_with_cl,
        "submitted": counts.get("submitted", 0),
        "skipped": counts.get("skipped", 0),
        "scored": counts.get("scored", 0),
        "new": counts.get("new", 0),
        "contract": contract_count,
    })


# ---------------------------------------------------------------------------
# API — Actions
# ---------------------------------------------------------------------------

# Track generation progress for SSE
_generation_progress = {"current": 0, "total": 0, "status": "idle", "message": ""}


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Generate cover letters for selected job IDs. Runs in background thread."""
    data = request.get_json()
    job_ids = data.get("job_ids", [])

    if not job_ids:
        return jsonify({"error": "No jobs selected"}), 400

    # Don't start if already running
    if _generation_progress["status"] == "running":
        return jsonify({"error": "Generation already in progress"}), 409

    _generation_progress["current"] = 0
    _generation_progress["total"] = len(job_ids)
    _generation_progress["status"] = "running"
    _generation_progress["message"] = "Starting..."

    def run_generation():
        from pipeline.generator import generate_cover_letter, generate_resume_bullets
        from pipeline.resume_generator import generate_tailored_resume
        profile = load_profile()
        generated = 0
        errors = 0

        for i, job_id in enumerate(job_ids):
            job = get_job_by_id(job_id)
            if not job:
                _generation_progress["current"] = i + 1
                continue

            _generation_progress["message"] = f"{job['title']} at {job['company']}"

            try:
                cl = generate_cover_letter(job, profile)
                bullets = generate_resume_bullets(job, profile)

                # Generate tailored resume PDF
                resume_path = None
                try:
                    resume_path = generate_tailored_resume(job, profile)
                except Exception:
                    pass  # Non-fatal: cover letter + bullets still saved

                # Merge resume_path into existing notes
                existing_notes = {}
                try:
                    existing_notes = json.loads(job.get("notes") or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
                if resume_path:
                    existing_notes["resume_path"] = resume_path
                notes_json = json.dumps(existing_notes)

                update_job(job_id, cover_letter=cl, resume_bullets=json.dumps(bullets), notes=notes_json)
                generated += 1
            except Exception as e:
                errors += 1
                _generation_progress["message"] = f"Error: {e}"

            _generation_progress["current"] = i + 1

        _generation_progress["status"] = "done"
        _generation_progress["message"] = f"Done: {generated} generated, {errors} errors"

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    return jsonify({"status": "started", "total": len(job_ids)})


@app.route("/api/generate/progress")
def api_generate_progress():
    """SSE endpoint for generation progress."""
    def stream():
        import time
        while True:
            data = json.dumps(_generation_progress)
            yield f"data: {data}\n\n"
            if _generation_progress["status"] in ("done", "idle"):
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/cover-letters/download-all", methods=["POST"])
def api_download_all_cover_letters():
    """Download multiple cover letters as a single ZIP file."""
    import io
    import zipfile

    data = request.get_json()
    job_ids = data.get("job_ids", [])
    fmt = data.get("format", "pdf").lower()

    if not job_ids:
        return jsonify({"error": "No jobs selected"}), 400

    profile = load_profile()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for job_id in job_ids:
            job = get_job_by_id(job_id)
            if not job or not job.get("cover_letter"):
                continue

            cover_letter = job["cover_letter"]
            company = job.get("company", "Company").replace(" ", "_").replace("/", "-")
            title = job.get("title", "Role").replace(" ", "_").replace("/", "-")
            base_name = f"Cover_Letter_{company}_{title}"

            if fmt == "docx":
                resp = _generate_docx(cover_letter, job, profile, base_name)
                zf.writestr(f"{base_name}.docx", resp.get_data())
            elif fmt == "txt":
                zf.writestr(f"{base_name}.txt", cover_letter.encode("utf-8"))
            else:
                resp = _generate_pdf(cover_letter, job, profile, base_name)
                zf.writestr(f"{base_name}.pdf", resp.get_data())

    buf.seek(0)

    ext_label = {"pdf": "PDF", "docx": "Word", "txt": "Text"}.get(fmt, "PDF")
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="Cover_Letters_{ext_label}_{len(job_ids)}_jobs.zip"'
        },
    )


@app.route("/api/job/<job_id>/cover-letter/download")
def api_download_cover_letter(job_id):
    """Download a job's cover letter as PDF, DOCX, or TXT."""
    job = get_job_by_id(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    cover_letter = job.get("cover_letter") or ""
    if not cover_letter:
        return jsonify({"error": "No cover letter generated"}), 404

    fmt = request.args.get("format", "pdf").lower()
    company = job.get("company", "Company").replace(" ", "_")
    title = job.get("title", "Role").replace(" ", "_")
    base_name = f"Cover_Letter_{company}_{title}"

    profile = load_profile()

    if fmt == "docx":
        return _generate_docx(cover_letter, job, profile, base_name)
    elif fmt == "txt":
        return Response(
            cover_letter,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.txt"'},
        )
    else:
        return _generate_pdf(cover_letter, job, profile, base_name)


@app.route("/api/job/<job_id>/resume/download")
def api_download_resume(job_id):
    """Download a job's tailored resume PDF. Returns 404 if not generated yet."""
    job = get_job_by_id(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    resume_path = PROJECT_ROOT / "data" / "resumes" / f"{job_id}.pdf"
    if not resume_path.exists():
        return jsonify({"error": "Tailored resume not generated yet"}), 404

    company = job.get("company", "Company").replace(" ", "_").replace("/", "-")
    title = job.get("title", "Role").replace(" ", "_").replace("/", "-")
    download_name = f"Resume_{company}_{title}.pdf"

    return send_file(
        str(resume_path),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


def _generate_pdf(cover_letter: str, job: dict, profile: dict, base_name: str):
    """Generate a professional cover letter PDF with Unicode support."""
    import io
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=25)

    # Register Arial TTF (Unicode-safe) with regular + bold variants
    pdf.add_font("arial", "", "/System/Library/Fonts/Supplemental/Arial.ttf", uni=True)
    pdf.add_font("arial", "B", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", uni=True)
    pdf.add_font("arial", "I", "/System/Library/Fonts/Supplemental/Arial Italic.ttf", uni=True)

    pdf.add_page()

    # Header — candidate name
    pdf.set_font("arial", "B", 18)
    pdf.cell(0, 10, profile.get("name", ""), new_x="LMARGIN", new_y="NEXT")

    # Contact line
    pdf.set_font("arial", "", 9)
    pdf.set_text_color(100, 100, 100)
    contact_parts = [
        profile.get("email", ""),
        profile.get("phone", ""),
        profile.get("location", ""),
    ]
    pdf.cell(0, 5, "  |  ".join(p for p in contact_parts if p), new_x="LMARGIN", new_y="NEXT")

    # LinkedIn / GitHub line
    links = [profile.get("linkedin", ""), profile.get("github", "")]
    links_str = "  |  ".join(l for l in links if l)
    if links_str:
        pdf.cell(0, 5, links_str, new_x="LMARGIN", new_y="NEXT")

    # Divider line
    pdf.set_draw_color(200, 200, 200)
    pdf.ln(4)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # Date and target
    from datetime import datetime
    pdf.set_text_color(100, 100, 100)
    pdf.set_font("arial", "", 10)
    pdf.cell(0, 5, datetime.now().strftime("%B %d, %Y"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("arial", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, f"{job.get('title', '')} at {job.get('company', '')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Cover letter body
    pdf.set_font("arial", "", 11)
    pdf.set_text_color(30, 30, 30)
    for paragraph in cover_letter.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            pdf.multi_cell(0, 6, paragraph)
            pdf.ln(4)

    # Sign off
    pdf.ln(4)
    pdf.set_font("arial", "", 11)
    pdf.cell(0, 6, "Best regards,", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("arial", "B", 11)
    pdf.cell(0, 6, profile.get("name", ""), new_x="LMARGIN", new_y="NEXT")

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    return Response(
        buf.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.pdf"'},
    )


def _generate_docx(cover_letter: str, job: dict, profile: dict, base_name: str):
    """Generate a professional cover letter DOCX."""
    import io
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor(30, 30, 30)

    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Header — name
    name_para = doc.add_paragraph()
    name_run = name_para.add_run(profile.get("name", ""))
    name_run.bold = True
    name_run.font.size = Pt(18)
    name_run.font.color.rgb = RGBColor(0, 0, 0)
    name_para.space_after = Pt(2)

    # Contact info
    contact_parts = [
        profile.get("email", ""),
        profile.get("phone", ""),
        profile.get("location", ""),
    ]
    contact_para = doc.add_paragraph()
    contact_run = contact_para.add_run("  |  ".join(p for p in contact_parts if p))
    contact_run.font.size = Pt(9)
    contact_run.font.color.rgb = RGBColor(100, 100, 100)
    contact_para.space_after = Pt(1)

    # Links
    links = [profile.get("linkedin", ""), profile.get("github", "")]
    links_str = "  |  ".join(l for l in links if l)
    if links_str:
        links_para = doc.add_paragraph()
        links_run = links_para.add_run(links_str)
        links_run.font.size = Pt(9)
        links_run.font.color.rgb = RGBColor(100, 100, 100)
        links_para.space_after = Pt(6)

    # Divider
    divider = doc.add_paragraph()
    divider_run = divider.add_run("_" * 80)
    divider_run.font.size = Pt(6)
    divider_run.font.color.rgb = RGBColor(200, 200, 200)
    divider.space_after = Pt(8)

    # Date
    from datetime import datetime
    date_para = doc.add_paragraph()
    date_run = date_para.add_run(datetime.now().strftime("%B %d, %Y"))
    date_run.font.size = Pt(10)
    date_run.font.color.rgb = RGBColor(100, 100, 100)
    date_para.space_after = Pt(2)

    # Target role
    role_para = doc.add_paragraph()
    role_run = role_para.add_run(f"{job.get('title', '')} at {job.get('company', '')}")
    role_run.bold = True
    role_run.font.size = Pt(10)
    role_para.space_after = Pt(12)

    # Body
    for paragraph in cover_letter.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            p = doc.add_paragraph(paragraph)
            p.space_after = Pt(8)

    # Sign-off
    doc.add_paragraph()
    regards = doc.add_paragraph("Best regards,")
    regards.space_after = Pt(2)
    sign = doc.add_paragraph()
    sign_run = sign.add_run(profile.get("name", ""))
    sign_run.bold = True

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.docx"'},
    )


@app.route("/api/skip", methods=["POST"])
def api_skip():
    """Skip selected jobs."""
    data = request.get_json()
    job_ids = data.get("job_ids", [])
    for job_id in job_ids:
        update_job(job_id, status="skipped", score_reason="[MANUAL] Skipped via dashboard")
    return jsonify({"status": "ok", "skipped": len(job_ids)})


@app.route("/api/job/<job_id>/cover-letter", methods=["PUT"])
def api_update_cover_letter(job_id):
    """Update a job's cover letter."""
    data = request.get_json()
    cover_letter = data.get("cover_letter", "")
    update_job(job_id, cover_letter=cover_letter)
    return jsonify({"status": "ok"})


@app.route("/api/profile")
def api_profile():
    """Return the candidate profile fields that will be used for applications."""
    profile = load_profile()
    name_parts = profile["name"].split(" ", 1)
    return jsonify({
        "first_name": name_parts[0],
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "location": profile.get("location", ""),
        "linkedin": profile.get("linkedin", ""),
        "github": profile.get("github", ""),
    })


@app.route("/api/submit/preview", methods=["POST"])
def api_submit_preview():
    """Return preview data for selected jobs before submission."""
    data = request.get_json()
    job_ids = data.get("job_ids", [])

    if not job_ids:
        return jsonify({"error": "No jobs selected"}), 400

    profile = load_profile()
    name_parts = profile["name"].split(" ", 1)

    profile_fields = {
        "first_name": name_parts[0],
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "location": profile.get("location", ""),
        "linkedin": profile.get("linkedin", ""),
        "github": profile.get("github", ""),
    }

    jobs_preview = []
    for job_id in job_ids:
        job = get_job_by_id(job_id)
        if not job:
            continue
        jobs_preview.append({
            "id": job["id"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "url": job.get("url", ""),
            "source": job.get("source", ""),
            "has_cover_letter": bool(job.get("cover_letter")),
            "cover_letter_preview": (job.get("cover_letter") or "")[:200] + ("..." if len(job.get("cover_letter") or "") > 200 else ""),
        })

    return jsonify({"profile": profile_fields, "jobs": jobs_preview})


@app.route("/api/submit", methods=["POST"])
def api_submit():
    """Mark selected jobs as submitted and return their URLs for the browser to open."""
    data = request.get_json()
    job_ids = data.get("job_ids", [])

    if not job_ids:
        return jsonify({"error": "No jobs selected"}), 400

    results = []
    apply_urls = []
    for job_id in job_ids:
        job = get_job_by_id(job_id)
        if not job:
            results.append({"id": job_id, "status": "skipped", "reason": "Job not found"})
            continue

        update_job(job_id, status="submitted")
        from utils.db import insert_application
        insert_application(job_id, "Submitted via web dashboard")
        apply_urls.append(f"/apply/{job_id}")
        results.append({
            "id": job_id,
            "status": "submitted",
            "url": job["url"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
        })

    return jsonify({"results": results, "urls": apply_urls})


# ---------------------------------------------------------------------------
# API — Auto-fill (Playwright)
# ---------------------------------------------------------------------------

_autofill_progress = {"current": 0, "total": 0, "status": "idle", "message": "", "results": []}


@app.route("/api/autofill", methods=["POST"])
def api_autofill():
    """Launch Playwright to auto-fill application forms for selected jobs."""
    data = request.get_json()
    job_ids = data.get("job_ids", [])

    if not job_ids:
        return jsonify({"error": "No jobs selected"}), 400

    if _autofill_progress["status"] == "running":
        return jsonify({"error": "Auto-fill already in progress"}), 409

    _autofill_progress["current"] = 0
    _autofill_progress["total"] = len(job_ids)
    _autofill_progress["status"] = "running"
    _autofill_progress["message"] = "Launching browser..."
    _autofill_progress["results"] = []

    def progress_callback(current, total, job, result):
        _autofill_progress["current"] = current
        if job:
            status = result.get("status", "unknown")
            filled_count = len(result.get("filled", {}))
            fields = ", ".join(result.get("filled", {}).keys()) if result.get("filled") else "none"
            _autofill_progress["message"] = f"{job.get('title', '')} at {job.get('company', '')} — {filled_count} fields filled"
            _autofill_progress["results"].append({
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "ats_type": result.get("ats_type", ""),
                "status": status,
                "filled_fields": list(result.get("filled", {}).keys()),
                "filled_details": result.get("filled", {}),
            })
        else:
            _autofill_progress["message"] = "Job not found, skipping..."

    def run_autofill():
        from pipeline.submitter import autofill_jobs_sync
        try:
            autofill_jobs_sync(job_ids, progress_callback)
        except Exception as e:
            _autofill_progress["message"] = f"Error: {e}"
        finally:
            _autofill_progress["status"] = "done"
            _autofill_progress["message"] = f"Done — {len(_autofill_progress['results'])} jobs processed"

            # Mark jobs as submitted
            for job_id in job_ids:
                job = get_job_by_id(job_id)
                if job:
                    update_job(job_id, status="submitted")
                    from utils.db import insert_application
                    insert_application(job_id, "Auto-filled via dashboard")

    thread = threading.Thread(target=run_autofill, daemon=True)
    thread.start()

    return jsonify({"status": "started", "total": len(job_ids)})


@app.route("/api/autofill/progress")
def api_autofill_progress():
    """SSE endpoint for auto-fill progress."""
    def stream():
        import time
        while True:
            data = json.dumps(_autofill_progress)
            yield f"data: {data}\n\n"
            if _autofill_progress["status"] in ("done", "idle"):
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_dashboard(port=5050):
    """Start the dashboard server and open browser."""
    import webbrowser
    init_db()
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
