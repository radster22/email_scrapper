# AGENTS.md

Instructions for coding agents (Codex and similar) working in this repo.

## What this repo does

It builds one master CSV, `faculty_emails.csv`, of university faculty: name, email, title,
department, university, and the public page each person was found on. It reads only public
faculty directories, respects `robots.txt`, and waits between requests.

| File | Role |
|---|---|
| `faculty_scraper.py` | Core scraper and CSV writer. Also scrapes the hand-written listings in `departments.json` (University of Maryland). |
| `multi_scraper.py` | Finds and scrapes ~51 departments at every university in `universities.json`. |
| `universities.json` | The universities to cover: `{"university", "domain", "region"}`. |
| `status.py` | Prints progress per university and the CSV totals. |
| `sync_to_sheets.py` | Copies new CSV rows into the Google Sheet (optional). |

Local state that must never be committed: `faculty_emails.csv` (the data), `discovered.json`
(per-department progress), `*.log`, `*.out`, `service_account.json`. All are in `.gitignore`.

## How duplicates are prevented (don't break this)

- **People:** every row is keyed by lowercased email. Before each append, the scraper takes
  `faculty_emails.csv.lock`, re-reads the CSV and skips any email already in it. Re-running
  anything never duplicates a person.
- **Work:** `discovered.json` records every department attempted per university. A rerun
  skips those, so a stopped run resumes where it left off.

Never delete or hand-edit `faculty_emails.csv` or `discovered.json` to "start fresh". Never
write to the CSV except through `FacultyScraper.append_rows`.

## Task 1: Resume the remaining scrape

1. Set up once: `python -m pip install -r requirements.txt`
2. Check state: `python status.py`. It lists the complete, partial and not-started universities.
3. If `faculty_emails.csv.lock` exists and no scraper is running, delete it (it's stale).
4. Run the scrape in a real terminal, in the foreground, so it isn't killed with the agent's session:

   ```
   python -u multi_scraper.py --workers 3 2>&1 | tee -a multi_run.out
   ```

   - `--workers 3` keeps memory down. Earlier runs at 6 workers were killed for low memory.
   - It takes a few hours. Progress is in `multi_scraper.log`. Lines read
     `<university> <department> <status> found N, added N <url>`.
   - If it's interrupted for any reason, run the same command again. It resumes.
5. When the run ends (log line `Done. N new people added this run.`), run `python status.py`
   and confirm every university shows `51/51`. If any don't, run step 4 again.
6. Report to the user: new people added this run, the CSV total, unique email count (must equal
   the row count), and universities with low yield (fewer than 5 `ok` departments).
7. If `service_account.json` exists, run `python sync_to_sheets.py` and report its output.

## Task 2: Retry departments that found nobody

When the user asks to capture missing departments:

```
python -u multi_scraper.py --workers 3 --retry-failed 2>&1 | tee -a multi_run.out
```

This re-attempts only departments whose status isn't `ok`. Already-captured people are skipped
automatically.

## Task 3: Add new universities (only when the user asks)

Don't add universities or start new runs on your own. When the user names new universities:

1. Append one entry per university to `universities.json`:
   `{"university": "Full Official Name", "domain": "example.edu", "region": "..."}`.
   Use the main domain without `www.`. Skip any university already in the file, compared by
   name and domain.
2. Run only the new ones:

   ```
   python -u multi_scraper.py --workers 3 --only "Full Official Name" "Another University" 2>&1 | tee -a multi_run.out
   ```

3. Follow steps 5 to 7 of Task 1, then report per-university results.

## Rules

- Don't lower `REQUEST_DELAY_SECONDS`, raise `--workers` above 6, or bypass the `robots.txt` check.
- Collect only faculty from public university directory pages. No students, and no logins or
  CAPTCHAs.
- Don't commit or push data, logs, progress files or credentials.
- When changing scraper code, check the change doesn't alter existing results. Run
  `python faculty_scraper.py --only <a department> --out /tmp/check.csv` before and after, and compare.

## Status values in `discovered.json`

| Status | Meaning |
|---|---|
| `ok` | People found and added |
| `no_site` | No website found for the department |
| `no_listing` | Site found, no faculty listing |
| `no_emails` | Listing found, but it doesn't publish emails (or they load via JavaScript) |
| `error` | Request failed; `--retry-failed` will try again |

## Known issues

- A department can be matched to the wrong page. For example, UC Santa Cruz "History" matched an
  engineering "BE History" page. Check a department's `url` in `discovered.json` when its counts
  look off.
- Low or zero yield at Caltech, UC Riverside, NYU, UC Davis and Stanford. Their directories are
  mostly rendered by JavaScript or don't list emails.
