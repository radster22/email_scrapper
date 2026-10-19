# AGENTS.md

Instructions for coding agents (Codex and similar) working in this repo.

## What this repo does

It builds one local master CSV, `faculty_emails.csv`, of university faculty: name, email,
title, department, university, and the public page each person was found on. It reads only public
faculty directories, respects `robots.txt`, and waits between requests. The local CSV is the
only output.

| File | Role |
|---|---|
| `universities.json` | **The list of universities to cover.** Add new ones here. |
| `multi_scraper.py` | Finds and scrapes ~51 departments at every university in `universities.json`. |
| `faculty_scraper.py` | Core scraper and CSV writer. Also scrapes the hand-written listings in `departments.json` (University of Maryland). |
| `status.py` | Shows which universities are complete, partial or not started, plus CSV totals. |

Local state, never committed: `faculty_emails.csv` (the data), `discovered.json` (progress),
`*.log` and `*.out`. All are in `.gitignore`.

## How skipping and deduplication work (don't break this)

The same command always works. It does only what's left:

- **Universities:** `discovered.json` records every department attempted per university. Any
  university with all departments attempted is **skipped entirely**. Repeated entries in
  `universities.json` (same name or domain) are ignored with a warning.
- **Departments:** a university that stopped part-way resumes at its first unattempted department.
- **People:** every row is keyed by lowercased email. Before each append, the scraper takes
  `faculty_emails.csv.lock`, re-reads the CSV and skips any email already in it. A person listed
  in two departments or universities is stored once.

Never delete or hand-edit `faculty_emails.csv` or `discovered.json` to "start fresh". Never
write to the CSV except through `FacultyScraper.append_rows`.

## The one command

```
python -u multi_scraper.py --workers 3 2>&1 | tee -a multi_run.out
```

Run it in a real terminal, in the foreground, so it isn't killed with the agent's session.

- At the start it logs `Skipping N already-complete universities` and
  `M universities to scrape: ...`. Check that list is what you expect.
- `--workers 3` keeps memory down; earlier runs at 6 workers were killed for low memory.
- Progress is in `multi_scraper.log`. Lines read
  `<university> <department> <status> found N, added N <url>`.
- If it stops for any reason, run the same command again. It resumes.
- It ends with `SUMMARY` lines and `Done. N new people added this run.`

## Task 1: Finish the current list

On a fresh clone there's no CSV or `discovered.json` yet, so this starts from scratch.
Requires Python 3.9+.

If your session might end before the run finishes (it takes hours), give the user the command
to run in their own terminal instead, and pick up from step 5 when they're back.

1. Set up once: `python -m pip install -r requirements.txt`
2. Run `python status.py` to see what's left.
3. If `faculty_emails.csv.lock` exists and no scraper is running, delete it (it's stale).
4. Run **the one command**.
5. When it ends, run `python status.py`. Every university should be under *Complete*. If any
   aren't, run the command again.
6. Report to the user:
   - new people added this run, and the CSV total;
   - unique email count, which must equal the row count;
   - universities with low yield (fewer than 5 `ok` departments).

## Task 2: Cover new universities (only when the user asks)

Don't add universities or start runs on your own. When the user names new universities:

1. Run `python status.py` and read `universities.json`. Drop any requested university that's
   already listed, compared by name or domain, and tell the user which ones were already covered.
2. Append the rest to the end of `universities.json`, one per university:
   `{"university": "Full Official Name", "domain": "example.edu", "region": "..."}`.
   Use the official name and the main domain without `www.`. Keep the file valid JSON.
3. Run **the one command**. No `--only` is needed: complete universities are skipped, so only
   the new ones (and any unfinished ones) are scraped. People already in the CSV are skipped
   automatically.
4. Follow steps 5 and 6 of Task 1, and report the results for each new university.

## Task 3: Retry departments that found nobody (only when the user asks)

```
python -u multi_scraper.py --workers 3 --retry-failed 2>&1 | tee -a multi_run.out
```

This re-attempts every department whose status isn't `ok`, including at complete universities.
People already captured are still skipped.

## Rules

- Don't lower `REQUEST_DELAY_SECONDS`, raise `--workers` above 6, or bypass the `robots.txt` check.
- Collect only faculty from public university directory pages. No students, and no logins or
  CAPTCHAs.
- Output goes only to the local `faculty_emails.csv`. Don't upload it anywhere.
- Don't commit or push data, logs or progress files.
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
