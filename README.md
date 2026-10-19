# email_scrapper

Build a spreadsheet (CSV) of university faculty from their public directory pages: names,
emails, titles, departments and universities.

Give it a list of universities. It finds about 51 departments at each one and adds every faculty
member it finds to **one CSV file**, `faculty_emails.csv`. Nobody is added twice. When you add
more universities later, it scrapes only the new ones.

Author: **Aradhya Singh Bisht** ([@radster22](https://github.com/radster22))

---

## Option A: Let an AI agent run it (easiest)

You don't need to know Python. The repo includes instructions an agent follows:
`AGENTS.md` for Codex, and `CLAUDE.md` (which points to it) for Claude Code.

**1. Get the code**

```
git clone https://github.com/radster22/email_scrapper.git
cd email_scrapper
```

**2. Open an agent in that folder**

- **Codex:** run `codex` in the folder.
- **Claude Code:** run `claude` in the folder.

**3. Paste one of these prompts**

| You want to... | Say this |
|---|---|
| Start, or continue where it stopped | `Set up this repo and run the scrape for all universities in universities.json. Tell me when it's done.` |
| Add universities | `Add Ohio State University and University of Michigan to universities.json and run the scrape for them.` |
| Check progress | `Run status.py and tell me where we are.` |
| Retry departments that came back empty | `Retry the departments that found nobody.` |

The agent installs what's needed, runs the scraper, and reports how many people were added.

> **Tip:** a full run takes a few hours. If the agent's session might close, ask it to give
> you the command, and run it yourself in a terminal (see Option B).

---

## Option B: Run it yourself

**1. Install Python 3.9+**, then in the repo folder:

```
python -m pip install -r requirements.txt
```

**2. Choose universities.** Edit `universities.json`. Each university is one line:

```json
{"university": "University of Michigan", "domain": "umich.edu", "region": "Midwest"}
```

**3. Run it**

```
python -u multi_scraper.py --workers 3
```

**4. Check progress at any time** (from a second terminal):

```
python status.py
```

**That's it.** Results are in `faculty_emails.csv`. Open it in Excel or Google Sheets.

### Common situations

| Situation | What to do |
|---|---|
| The run stopped (crash, shutdown, closed terminal) | Run the same command again. It resumes. |
| I want more universities | Add them to `universities.json` and run the same command. Finished universities are skipped. |
| Some departments found nobody | `python -u multi_scraper.py --workers 3 --retry-failed` |
| Only run specific universities | `python -u multi_scraper.py --only "Yale University" "Duke University"` |
| My computer runs low on memory | Use `--workers 2` |
| It says the CSV is locked and no scraper is running | Delete `faculty_emails.csv.lock` |

---

## What you get

`faculty_emails.csv`:

| Name | Email | Title | Department | University | Source URL | Date Added |
|---|---|---|---|---|---|---|
| Jane Doe | jdoe@example.edu | Associate Professor | Physics | Example University | https://physics.example.edu/people | 2026-10-19 |

The *Source URL* column shows where each person was found, so you can check it.

## How it works (short version)

1. **Finds each department's website** from the university's academics pages, or by trying
   common addresses like `physics.example.edu`.
2. **Finds the faculty listing** (the *Faculty*, *People* or *Directory* page).
3. **Reads names and emails.** It pairs each email with the name next to it. If the listing has
   no emails, it opens each person's profile page.
4. **Saves to the CSV,** skipping any email already there. It records progress in
   `discovered.json` after every department, so it can always resume.

It respects each site's `robots.txt`, waits between requests, and reads only public pages.

## Files

| File | What it is |
|---|---|
| `universities.json` | **Your list of universities.** Edit this. |
| `multi_scraper.py` | The main scraper (Option B, step 3) |
| `status.py` | Progress report |
| `faculty_scraper.py` | Core engine. Also runs hand-picked directory pages from `departments.json` with `python faculty_scraper.py`. |
| `departments.json` | Hand-picked directory pages (University of Maryland) |
| `AGENTS.md` / `CLAUDE.md` | Instructions for AI agents |

Created when you run it, and never uploaded to GitHub: `faculty_emails.csv` (results),
`discovered.json` (progress), and `*.log` / `*.out` (logs).

## Limitations

- Some universities build their directories with JavaScript or don't publish emails. Those
  departments come back empty (`no_emails` in `discovered.json`).
- A department is occasionally matched to the wrong page. Check the *Source URL* if a count
  looks odd.

## Responsible use

This collects contact details that universities publish for professional contact. Follow each
site's terms and the law (such as CAN-SPAM and GDPR). Don't send unsolicited bulk email, and
don't republish the collected data.

## Credits

Inspired by
[pChitral/University-at-Buffalo-Faculty-Web-Scraper](https://github.com/pChitral/University-at-Buffalo-Faculty-Web-Scraper),
rewritten here to work generically across many universities.
