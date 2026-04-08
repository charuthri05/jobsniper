# JobSniper

Automated job application pipeline. Scrapes 70+ company boards, scores jobs against your resume using AI, generates tailored cover letters and ATS-optimized resumes.

**You review and approve every application before it's sent.**

## How It Works

```
Scrape → Score → Generate → Review
```

1. **Scrape** — pulls jobs from Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs + 70 company boards (Stripe, Airbnb, Coinbase, etc.)
2. **Score** — filters out staffing companies and no-visa jobs, then AI scores each job 0-100 against your profile
3. **Generate** — writes a tailored cover letter, resume bullets, and a full ATS-optimized resume PDF for top matches
4. **Review** — browse everything in the web dashboard, download materials, apply on your own terms

## Getting Started

### 1. Clone & install
```bash
git clone https://github.com/charuthri05/jobsniper.git
cd jobsniper
pip install -r requirements.txt
playwright install chromium
```

### 2. Run setup
```bash
python run.py setup
```

The setup wizard walks you through:
- **Choose AI provider** — OpenAI (~$0.02/100 jobs) or Anthropic (~$1/100 jobs)
- **Enter API key** — creates `.env` file automatically
- **LinkedIn cookie** (optional) — adds LinkedIn as a job source
- **Your info** — name, email, phone, location, LinkedIn, GitHub
- **Professional summary** — 2-3 sentences about you
- **Skills** — languages, frameworks, databases, infrastructure, etc.
- **Experience** — add each role with bullet points
- **Education** — degree, school, year
- **Resume import** — import from PDF, paste as text, or auto-generate from the info above
- **Preferences** — target roles, locations, salary, seniority, visa sponsorship, company blacklist

### 3. Run the pipeline
```bash
python run.py all
```

Scrapes all sources, scores with AI, generates cover letters + tailored resumes for top matches.

### 4. Review in the dashboard
```bash
python run.py dashboard
```

Opens web UI at `localhost:5050` where you can:
- Browse jobs by tab (Queued / Ready / Submitted / New / Scored / Contract)
- View AI scores, strengths, and skill gaps
- Edit cover letters inline
- Download tailored resume PDFs
- Download cover letters as PDF, Word, or plain text

## AI Providers

| Provider | Model | ~Cost per 100 jobs |
|----------|-------|--------------------|
| **OpenAI** (recommended) | GPT-4o-mini | $0.02 |
| Anthropic | Claude Sonnet | $1.00 |

Both give free credits on signup. You choose during setup.

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
- **`data/preferences.json`** — target roles, companies, salary, seniority, visa, board list

## Commands

| Command | Description |
|---------|-------------|
| `python run.py setup` | Profile + API key setup wizard |
| `python run.py all` | Full pipeline (scrape + score + generate) |
| `python run.py dashboard` | Web UI at localhost:5050 |
| `python run.py scrape` | Scrape only |
| `python run.py score` | Score only |
| `python run.py generate` | Generate only |
| `python run.py stats` | Application statistics |
| `python run.py export` | Export jobs to CSV |

## Privacy

All data stays local. Only job descriptions are sent to the AI provider for scoring. Your resume, API keys, and database are gitignored.

## License

MIT
