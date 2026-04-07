# Job Application Pipeline

Automated job application pipeline for Software Engineers. Scrapes 70+ company job boards and 5 major job sites, scores postings against your profile using AI, generates tailored cover letters, and auto-fills application forms.

**Nothing is ever submitted without your approval.** You review every application before it goes out.

## Features

- Scrapes **Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs** via JobSpy
- Fetches from **69 Greenhouse + 1 Lever boards** (Stripe, Airbnb, Databricks, Coinbase, etc.)
- AI-powered scoring (0-100) with detailed reasoning
- Auto-generates **tailored cover letters** and **resume bullets** per job
- Filters out **staffing/consultancy companies** automatically
- Detects **"no visa sponsorship"** language (configurable)
- Interactive **review queue** — approve, edit, skip
- **Auto-fills** Greenhouse, Lever, and generic application forms via Playwright
- Web dashboard for visual job browsing
- Everything stored locally in SQLite — your data never leaves your machine

## Quick Start

```bash
git clone https://github.com/youruser/job-pipeline.git
cd job-pipeline
pip install -r requirements.txt
playwright install chromium
python run.py setup
```

The setup wizard will:
1. Ask you to choose an AI provider (OpenAI or Anthropic) and enter your API key
2. Optionally configure your LinkedIn session cookie
3. Build your candidate profile (import from PDF or enter manually)
4. Set your job search preferences

## AI Provider Options

| Provider | Model | Cost per 100 jobs | Sign up |
|----------|-------|--------------------|---------|
| **OpenAI** (recommended) | GPT-4o-mini | ~$0.02 | [platform.openai.com](https://platform.openai.com/api-keys) |
| Anthropic | Claude Sonnet | ~$1.00 | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

Both offer free credits for new accounts.

## Daily Use

```bash
# Option A: step by step
python run.py scrape       # scrape all sources (~2-3 min)
python run.py score        # AI scores new jobs (~15 min for 1000 jobs)
python run.py generate     # generate cover letters for top matches
python run.py review       # review and approve

# Option B: run pipeline overnight, review in the morning
python run.py all          # scrape + score + generate (cron at 2am)
python run.py review       # review each morning
```

## Commands

| Command | Description |
|---------|-------------|
| `python run.py setup` | Interactive profile + API key setup |
| `python run.py scrape` | Scrape all configured job sources |
| `python run.py score` | Score new jobs (hard filters + AI) |
| `python run.py generate` | Generate cover letters + resume bullets |
| `python run.py review` | Interactive review queue |
| `python run.py all` | Full pipeline (scrape + score + generate) |
| `python run.py stats` | Print application statistics |
| `python run.py export` | Export jobs.db to CSV |
| `python run.py dashboard` | Launch web-based dashboard |

## Review Queue

Your daily driver. For each matching job:

```
------------------------------------------------------------
[2/15]  Backend Engineer — Stripe
        San Francisco, CA · $180,000 - $250,000
        Score: 91/100  |  strong fit
        Why: distributed systems, payments domain match
        Missing: Kafka experience

  COVER LETTER PREVIEW:
  +----------------------------------------------------+
  | My experience building high-throughput systems...   |
  +----------------------------------------------------+

  [a] approve + submit   [e] edit   [r] read JD   [v] view letter   [s] skip
```

## How Scoring Works

**Stage 1 — Hard filters (free, instant):**
- Filters out non-engineering titles
- Blocks known staffing/consultancy companies (Infosys, Revature, etc.)
- Detects "no visa sponsorship" language (if you need sponsorship)
- Checks company blacklist and seniority level

**Stage 2 — AI scoring:**
- Sends your profile + job description to GPT-4o-mini / Claude
- Returns a 0-100 score with reasoning, strengths, and gaps
- Jobs scoring above threshold (default: 72) advance to cover letter generation

## Pre-configured Company Boards (69 Greenhouse + 1 Lever)

**Big Tech:** Lyft, Pinterest, Block, DeepMind, Waymo
**AI:** Anthropic
**Fintech:** Stripe, Robinhood, Coinbase, Brex, Affirm, Chime, SoFi, Mercury, Marqeta, Nubank, Upstart, Blend, Monzo, Lithic, Melio, TreasuryPrime
**Data/Infra:** Databricks, Cloudflare, Datadog, MongoDB, Elastic, Fivetran, ClickHouse, SingleStore, CockroachLabs, Temporal, PlanetScale
**Consumer:** Airbnb, Reddit, Discord, Instacart, Duolingo, Dropbox, Airtable, Asana, Spotify
**SaaS:** Twilio, Okta, PagerDuty, Zscaler, HubSpot, GitLab, Samsara, Toast, Gusto, Lattice
**DevTools:** Figma, Vercel, Fastly, Netlify, CircleCI, LaunchDarkly, Amplitude, Mixpanel, Webflow, Contentful

Edit `data/preferences.json` to add or remove boards.

## Configuration

All config lives in two files:

- **`.env`** — API keys, AI provider, LinkedIn cookie, score threshold
- **`data/preferences.json`** — Target roles, locations, salary, seniority, company boards, blacklist

## Cron Setup

```bash
crontab -e
# Add:
0 2 * * * cd /path/to/job-pipeline && python run.py all >> logs/cron.log 2>&1
```

## Project Structure

```
job-pipeline/
├── run.py                  # CLI entry point
├── .env.example            # template (never commit .env)
├── requirements.txt
├── data/
│   ├── candidate_profile.json   # your profile (gitignored)
│   ├── preferences.json         # job search config
│   └── jobs.db                  # SQLite database (gitignored)
├── scrapers/
│   ├── ats_scraper.py           # Greenhouse + Lever APIs
│   ├── jobspy_scraper.py        # Indeed, LinkedIn, Glassdoor, etc.
│   └── hiringcafe_scraper.py    # HiringCafe
├── pipeline/
│   ├── normalizer.py            # merge + dedup all sources
│   ├── scorer.py                # hard filters + AI scoring
│   ├── generator.py             # cover letter + bullet generation
│   └── submitter.py             # Playwright form auto-fill
├── review/
│   └── cli.py                   # terminal review queue
├── utils/
│   ├── ai_client.py             # OpenAI / Anthropic abstraction
│   ├── db.py                    # SQLite helpers
│   ├── profile.py               # profile loader/validator
│   └── resume_parser.py         # PDF resume parser
├── web/
│   └── app.py                   # web dashboard
└── logs/
    └── submissions.log
```

## Privacy

- All data stays on your machine (SQLite database, local files)
- API keys are stored in `.env` (gitignored)
- Your profile and resume are in `data/candidate_profile.json` (gitignored)
- Only job descriptions are sent to the AI provider for scoring/generation

## License

MIT
