# JobSniper

Automated job application pipeline. Scrapes 70+ company boards + Hiring Cafe, scores jobs against your resume using AI, generates tailored cover letters and ATS-optimized resumes.

**You review and approve every application before it's sent.**

## How It Works

```
Upload Resume → Scrape → Score → Generate → Review & Apply
```

1. **Setup** — upload your resume in the web UI, AI parses it and fills your profile automatically
2. **Scrape** — pulls jobs from Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs, Hiring Cafe + 70 company boards (Stripe, Airbnb, Coinbase, etc.)
3. **Score** — filters out staffing companies and no-visa jobs, then AI scores each job 0-100 against your profile
4. **Generate** — writes a tailored cover letter, resume bullets, and a full ATS-optimized resume PDF for top matches
5. **Review** — browse everything in the web dashboard, download materials, apply on your own terms

## Getting Started

### 1. Clone & install
```bash
git clone https://github.com/charuthri05/jobsniper.git
cd jobsniper
pip install -r requirements.txt
playwright install chromium
```

### 2. Set up your API key
Create a `.env` file:
```bash
cp .env.example .env
```
Add your OpenAI or Anthropic API key to `.env`:
```
OPENAI_API_KEY=sk-...
```

### 3. Launch the dashboard
```bash
python run.py dashboard
```

That's it. The dashboard opens at `http://localhost:5050`.

- **First time?** You'll be redirected to the setup page automatically
- **Upload your resume** (PDF, DOCX, or TXT) — AI parses it and fills all fields
- **Review & edit** the parsed profile, set your preferences (locations, salary, visa, etc.)
- **Save & Go to Dashboard** — you're ready to scrape

### 4. Scrape & score

From the dashboard:
- Click **Scrape Jobs** in the top navbar to fetch latest jobs
- Select jobs and click **Generate Cover Letters** to create tailored materials
- Download cover letters as PDF, Word, or plain text
- Click **Auto-Fill & Apply** to open applications with pre-filled forms

Or from the terminal:
```bash
python run.py all        # scrape + score + generate in one go
python run.py dashboard  # then open the dashboard to review
```

## AI Providers

| Provider | Model | ~Cost per 100 jobs |
|----------|-------|--------------------|
| **OpenAI** (recommended) | GPT-4o-mini | $0.02 |
| Anthropic | Claude Sonnet | $1.00 |

Set `AI_PROVIDER=openai` or `AI_PROVIDER=anthropic` in `.env`. Both give free credits on signup.

## What Gets Scraped

**Job boards:** Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs

**Hiring Cafe:** AI-powered aggregator scraping 30K+ company career pages

**70+ company boards (Greenhouse & Lever):** Stripe, Anthropic, Databricks, Airbnb, Figma, Coinbase, Robinhood, Brex, Affirm, Chime, SoFi, Cloudflare, Datadog, MongoDB, Reddit, Discord, Duolingo, Dropbox, Twilio, Okta, GitLab, OpenAI, Netflix, and [40+ more](data/preferences.json)

Edit boards and preferences from the **Settings** page (gear icon in dashboard).

## Dashboard Features

- **Profile Setup** — upload resume, AI auto-fills your profile, edit preferences
- **Scrape Button** — fetch new jobs from all sources with live progress
- **Job Browser** — browse by status (Queued / Ready / Submitted / Skipped), sort by score
- **AI Scoring** — view match score, strengths, skill gaps for each job
- **Cover Letter Generation** — generate for selected jobs, view results, edit inline
- **Download** — cover letters as PDF, Word, or TXT; bulk download as ZIP
- **Auto-Fill** — Playwright opens applications and pre-fills forms (Greenhouse, Lever, Workday, etc.)
- **Per-Job Apply Page** — all your info with copy buttons for manual applications

## Commands

| Command | Description |
|---------|-------------|
| `python run.py dashboard` | **Start here** — web UI at localhost:5050 |
| `python run.py all` | Full pipeline (scrape + score + generate) |
| `python run.py scrape` | Scrape only |
| `python run.py score` | Score only |
| `python run.py generate` | Generate only |
| `python run.py stats` | Application statistics |
| `python run.py export` | Export jobs to CSV |

## Config

- **`.env`** — API keys, AI provider, score threshold
- **`data/preferences.json`** — target roles, locations, companies, salary, seniority, visa, board list
- **`data/candidate_profile.json`** — your profile (auto-created from setup)

All editable from the web UI via the gear icon.

## Privacy

All data stays local. Only job descriptions are sent to the AI provider for scoring. Your resume, API keys, and database are gitignored.

## License

MIT
