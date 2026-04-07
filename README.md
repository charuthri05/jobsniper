# JobSniper

Automated job application pipeline. Scrapes 70+ company boards, scores jobs against your resume using AI, generates tailored cover letters, and auto-fills applications.

**You review and approve every application before it's sent.**

## How It Works

```
Scrape → Score → Generate → Review → Submit
```

1. **Scrape** — pulls jobs from Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs + 70 company boards (Stripe, Airbnb, Coinbase, etc.)
2. **Score** — filters out staffing companies and no-visa jobs, then AI scores each job 0-100 against your profile
3. **Generate** — writes a tailored cover letter + resume bullets for top matches
4. **Review** — you approve, edit, or skip each one
5. **Submit** — auto-fills the application form via Playwright

## Setup

```bash
git clone https://github.com/charuthri05/jobsniper.git
cd jobsniper
pip install -r requirements.txt
playwright install chromium
python run.py setup
```

Setup walks you through everything: AI provider, API key, LinkedIn cookie, your profile, and job preferences.

## Usage

```bash
python run.py all        # run full pipeline (scrape + score + generate)
python run.py review     # review and submit
python run.py stats      # see your numbers
python run.py dashboard  # web UI
```

Or step by step: `scrape` → `score` → `generate` → `review`

## AI Providers

| Provider | Model | ~Cost per 100 jobs |
|----------|-------|--------------------|
| **OpenAI** | GPT-4o-mini | $0.02 |
| Anthropic | Claude Sonnet | $1.00 |

Both give free credits on signup. You choose during `setup`.

## What Gets Scraped

**Job boards:** Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs

**70 company boards:** Stripe, Anthropic, Databricks, Airbnb, Figma, Coinbase, Robinhood, Brex, Affirm, Chime, SoFi, Mercury, Cloudflare, Datadog, MongoDB, Reddit, Discord, Duolingo, Dropbox, Twilio, Okta, GitLab, Pinterest, Block, DeepMind, Waymo, Spotify, and [40+ more](data/preferences.json)

Edit `data/preferences.json` to add or remove companies.

## Built-in Filters

- Blocks 40+ known **staffing/consultancy companies** (Infosys, Revature, TCS, etc.)
- Detects **"no visa sponsorship"** language (if you need sponsorship)
- Skips non-engineering titles before wasting API credits
- Company blacklist, seniority level, salary floor

## Config

- **`.env`** — API keys, AI provider, score threshold
- **`data/preferences.json`** — roles, companies, salary, seniority, visa

## Automate It

```bash
crontab -e
0 2 * * * cd /path/to/jobsniper && python run.py all >> logs/cron.log 2>&1
```

Run the pipeline at 2am, review each morning with `python run.py review`.

## Privacy

All data stays local. Only job descriptions are sent to the AI provider for scoring. Your resume, API keys, and database are gitignored.

## License

MIT
