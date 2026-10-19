# email_scrapper

A faculty directory scraper that builds one deduplicated CSV of university faculty: name, email,
title, department and university. It covers the departments of many universities from their
public directory pages.

Author: **Aradhya Singh Bisht** ([@radster22](https://github.com/radster22))

## Features

- **Works on most directory layouts without site-specific selectors.** For each `mailto:` link
  it finds the person's "card" on the page and takes the name and title from it. When a listing
  has no emails, it visits each profile page.
- **Finds departments automatically.** Give it a university's domain and it locates about 51
  department sites (engineering, sciences, social sciences, humanities, business and more) and
  their faculty listings.
- **One master CSV, no duplicates.** Rows are keyed by email. Re-running never adds anyone twice,
  and parallel workers share a file lock.
- **Resumable.** Progress per department is saved to `discovered.json`, so a stopped run picks up
  where it left off.
- **Polite.** It respects `robots.txt`, waits between requests and retries failed connections.
- **Google Sheets sync (optional).** Copies new rows into a Google Sheet.

## Setup

```
python -m pip install -r requirements.txt
```

## Usage

```
# Scrape every university in universities.json (resumes automatically)
python -u multi_scraper.py --workers 3

# Only some universities
python -u multi_scraper.py --only "Purdue University" "Yale University"

# Retry departments that found nobody last time
python -u multi_scraper.py --retry-failed

# Scrape the hand-configured listings in departments.json
python faculty_scraper.py
python faculty_scraper.py --only Mathematics Physics

# Progress report
python status.py

# Push new rows to Google Sheets
python sync_to_sheets.py
```

To add a university, append `{"university": "...", "domain": "example.edu", "region": "..."}`
to `universities.json` and run it with `--only`.

### Output columns

`Name, Email, Title, Department, University, Source URL, Date Added`

### Google Sheets setup

1. In Google Cloud, create a project and enable the Google Sheets API.
2. Create a service account with a JSON key and save it as `service_account.json`. It is
   gitignored.
3. Share the target sheet with the service account's email as Editor, and pass `--sheet-id` if
   it isn't the default.

## Files

| File | Purpose |
|---|---|
| `faculty_scraper.py` | Core extraction, CSV writing and the `departments.json` runner |
| `multi_scraper.py` | Automatic department discovery across universities |
| `departments.json` | Hand-picked directory URLs (University of Maryland) |
| `universities.json` | Universities for automatic discovery |
| `status.py` | Progress report |
| `sync_to_sheets.py` | Google Sheets sync |
| `AGENTS.md` | Instructions for coding agents running or extending the scrape |

Scraped data (`*.csv`), progress (`discovered.json`), logs and credentials are gitignored and
never published.

## Responsible use

This tool collects contact details that universities publish for professional contact. Use the
results in line with each site's terms and applicable law, such as CAN-SPAM and GDPR. Don't use
it for unsolicited bulk email, and don't republish the collected data.

## Credits

The idea comes from
[pChitral/University-at-Buffalo-Faculty-Web-Scraper](https://github.com/pChitral/University-at-Buffalo-Faculty-Web-Scraper),
which was rewritten here to be generic and to cover multiple universities.
