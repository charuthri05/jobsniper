"""
Load and validate candidate_profile.json and preferences.json.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILE_PATH = DATA_DIR / "candidate_profile.json"
PREFERENCES_PATH = DATA_DIR / "preferences.json"

REQUIRED_PROFILE_FIELDS = [
    "name", "email", "phone", "location", "summary",
    "years_of_experience", "current_title", "target_titles",
    "skills", "experience", "education", "raw_resume_text",
]

REQUIRED_SKILLS_KEYS = ["languages", "frameworks", "infrastructure", "databases", "other"]


def load_profile() -> dict:
    """
    Load candidate_profile.json, validate required fields, and return the dict.
    Raises FileNotFoundError if the file is missing.
    Raises ValueError if required fields are absent or malformed.
    """
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run 'python run.py setup' first."
        )
    with open(PROFILE_PATH, "r") as f:
        profile = json.load(f)

    validate_profile(profile)
    return profile


def validate_profile(profile: dict) -> None:
    """
    Check that all required fields are present and non-empty.
    Raises ValueError with a descriptive message on failure.
    """
    missing = [f for f in REQUIRED_PROFILE_FIELDS if f not in profile or not profile[f]]
    if missing:
        raise ValueError(f"Profile is missing required fields: {', '.join(missing)}")

    skills = profile.get("skills", {})
    missing_skills = [k for k in REQUIRED_SKILLS_KEYS if k not in skills]
    if missing_skills:
        raise ValueError(f"Profile skills missing keys: {', '.join(missing_skills)}")

    if not isinstance(profile.get("experience"), list) or len(profile["experience"]) == 0:
        raise ValueError("Profile must include at least one experience entry.")

    for i, exp in enumerate(profile["experience"]):
        for field in ("title", "company", "start", "bullets"):
            if field not in exp:
                raise ValueError(f"Experience entry {i} is missing '{field}'.")

    if not isinstance(profile.get("education"), list) or len(profile["education"]) == 0:
        raise ValueError("Profile must include at least one education entry.")


def save_profile(profile: dict) -> None:
    """Write profile dict to candidate_profile.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)


def get_default_preferences() -> dict:
    """Return the default preferences — baked into the codebase so any
    fresh clone starts with these values pre-filled.

    Greenhouse/Lever boards are verified active as of March 2026.
    """
    return {
        "target_roles": [
            "Software Engineer", "Senior Software Engineer", "SWE",
            "Backend Engineer", "Full Stack Engineer", "Frontend Engineer",
            "Full Stack Developer", "Backend Developer", "Frontend Developer",
            "SWE II", "Founding Engineer",
        ],
        "target_companies": [],
        "blacklist_companies": [],
        "locations": [],
        "remote_only": False,
        "min_salary": 0,
        "seniority_levels": ["entry-level", "mid", "senior"],
        "visa_sponsorship_required": False,
        "greenhouse_boards": [
            # Big Tech
            "lyft", "pinterest", "block", "deepmind", "waymo",
            # AI
            "anthropic",
            # Fintech
            "stripe", "robinhood", "coinbase", "brex", "affirm", "chime",
            "sofi", "marqeta", "nubank", "mercury", "lithic",
            "treasuryprime", "melio", "upstart", "blend", "monzo",
            # Data / Infrastructure
            "databricks", "cloudflare", "datadog", "mongodb", "elastic",
            "fivetran", "temporal", "clickhouse", "singlestore",
            "cockroachlabs", "planetscale",
            # Consumer / Marketplace
            "airbnb", "reddit", "discord", "instacart", "duolingo",
            "dropbox", "airtable", "asana",
            # Enterprise SaaS
            "twilio", "okta", "pagerduty", "zscaler", "hubspot", "gitlab",
            "samsara", "toast", "gusto", "lattice",
            # DevTools / Infra
            "figma", "vercel", "fastly", "netlify", "circleci",
            "launchdarkly", "amplitude", "mixpanel", "webflow",
            "contentful", "storyblok",
            # Other
            "squarespace", "remote", "cultureamp", "shield",
            "poshmark", "veracyte", "nuro",
        ],
        "lever_boards": [
            "spotify",
        ],
    }


def get_default_profile() -> dict:
    """Return an empty profile template for new users.
    All fields are blank — the setup command fills them interactively."""
    return {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "summary": "",
        "years_of_experience": 0,
        "current_title": "",
        "target_titles": [
            "Software Engineer", "Full Stack Engineer", "Backend Engineer",
            "Frontend Engineer", "SWE II", "Senior Software Engineer",
        ],
        "skills": {
            "languages": [],
            "frameworks": [],
            "infrastructure": [],
            "databases": [],
            "other": [],
        },
        "experience": [],
        "education": [],
        "raw_resume_text": "",
    }


def load_preferences() -> dict:
    """
    Load preferences.json.
    If the file doesn't exist, create it with baked-in defaults and return that.
    """
    if not PREFERENCES_PATH.exists():
        defaults = get_default_preferences()
        save_preferences(defaults)
        return defaults

    with open(PREFERENCES_PATH, "r") as f:
        return json.load(f)


def save_preferences(prefs: dict) -> None:
    """Write preferences dict to preferences.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PREFERENCES_PATH, "w") as f:
        json.dump(prefs, f, indent=2)


def get_all_bullets(profile: dict) -> list[str]:
    """Extract all experience bullets from the profile into a flat list."""
    bullets = []
    for exp in profile.get("experience", []):
        bullets.extend(exp.get("bullets", []))
    return bullets
