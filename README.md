# WorldMark Seaside Availability Agent

Checks WorldMark Seaside rental inventory for **July 11–18, 2027** on Go-Koala and RedWeek, stores price history, and emails an alert when listings are found or prices change.

## Important limitation

The two sites can change their HTML, require JavaScript, login, CAPTCHA, or otherwise restrict automated access. The included collectors use Playwright and intentionally fail safely rather than attempting to bypass anti-bot controls. If a site changes, update that collector.

## Setup

1. Create a GitHub repository and upload these files.
2. In GitHub: **Settings → Secrets and variables → Actions**, add:
   - `ALERT_EMAIL`
   - `SMTP_HOST` (example: `smtp.gmail.com`)
   - `SMTP_PORT` (example: `465`)
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD` (for Gmail, use an App Password)
3. Run **Actions → WorldMark Seaside Daily Check → Run workflow** once manually.
4. The workflow then runs daily at 8:00 AM Pacific.

The database is stored as a workflow artifact after each run. For a more permanent database, replace `data/history.json` with SQLite/Postgres/Supabase.

## Configuration

Edit `config.json` to change dates, sites, or alert behavior.

The agent searches the resort name and date range and attempts to extract listing cards. Site-specific selectors are deliberately isolated in `agent.py`.

## Output

Each run writes:
- `data/history.json` — historical observations
- `data/latest.json` — latest results
- `data/report.txt` — human-readable report

The email only sends when availability is found or a previously observed listing changes price/disappears.
