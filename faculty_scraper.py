"""
Faculty directory scraper.

Reads departments.json, scrapes each public faculty directory page for
name + email pairs, and appends any new people to a single master CSV
(faculty_emails.csv). Re-running never duplicates rows: people are keyed
by email address.

Adapted from https://github.com/pChitral/University-at-Buffalo-Faculty-Web-Scraper,
but instead of hard-coded, site-specific CSS classes it uses a generic rule
that works on most directory layouts: for every mailto: link, walk up the
page to the smallest "card" that contains that one email and a person's
name, and take the name from that card. This keeps each name paired with
its own email (the original zipped two separately-scraped lists together,
which mis-aligns rows when counts differ).

Usage:
    python faculty_scraper.py                  # scrape everything in departments.json
    python faculty_scraper.py --only Mathematics Physics
    python faculty_scraper.py --config other.json --out other.csv
"""

import argparse
import contextlib
import csv
import datetime as dt
import json
import logging
import os
import re
import threading
import time
import urllib.robotparser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; faculty-directory-scraper/1.0)"
REQUEST_DELAY_SECONDS = 2
MAX_PAGES_PER_DIRECTORY = 30
MAX_CARD_TEXT_LENGTH = 2000
CSV_COLUMNS = ["Name", "Email", "Title", "Department", "University", "Source URL", "Date Added"]

EMAIL_RE = re.compile(r"^[\w.+'-]+@[\w-]+(\.[\w-]+)+$")
# A person's name: 2-7 words of letters plus . ' " - , ( ) (for "Jr.", nicknames, accents), no digits.
NAME_RE = re.compile(r"^[^\W\d_][^\W\d_.'\"\-,()]*(?:[.'\"\-,()]*\s*[^\W\d_]*){1,12}[.)\"]?$", re.UNICODE)
NAME_WORDS = (2, 7)
NOT_A_NAME = re.compile(
    r"\b(professor|lecturer|department|contact|email|office|phone|website|"
    r"homepage|director|chair|faculty|staff|research|lab|view|profile|more|"
    r"building|room|bldg|university|institute|center|program|school|college|"
    r"engineering|science|sciences|studies|computer|physics|mathematics|psychology|"
    r"chemistry|biology|systems|materials|technology|and|of|the|for|with|us|our|"
    r"connect|follow|visit|about|info|help|apply|give|learn|send|message|"
    r"home|menu|site|web|webmaster|accessibility|skip|search|login|privacy)\b",
    re.IGNORECASE,
)
TITLE_RE = re.compile(
    r"\b(professor|lecturer|instructor|scientist|chair|director|fellow|faculty|dean|specialist)\b", re.IGNORECASE
)
# Used by "faculty_only": true to drop staff / students from mixed directories.
FACULTY_RE = re.compile(r"\b(professor|lecturer|instructor|faculty|dean)\b", re.IGNORECASE)
NOT_FACULTY_RE = re.compile(r"\b(graduate|student|postdoc|post-doctoral|assistant to)\b", re.IGNORECASE)
# Where to look for a name inside a card, most specific first. A table cell or
# paragraph often holds name + title together, so it's only a last resort.
NAME_TAG_GROUPS = (["h1", "h2", "h3", "h4", "h5", "h6", "a"], ["strong", "b"], ["span", "p", "td", "div"])
MAX_PROFILES_PER_DIRECTORY = 800
# An email that appears on this many profile pages is a shared office address, not the person's.
SHARED_EMAIL_MIN_PROFILES = 3

log = logging.getLogger("faculty_scraper")
_thread_lock = threading.Lock()


@contextlib.contextmanager
def csv_lock(path, timeout=120):
    """Cross-process lock: a <csv>.lock file created exclusively, plus a thread lock."""
    lock_path = path + ".lock"
    with _thread_lock:
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.time() > deadline:  # stale lock from a killed run
                    os.remove(lock_path)
                    deadline = time.time() + timeout
                time.sleep(0.2)
        try:
            yield
        finally:
            os.close(fd)
            os.remove(lock_path)


class FacultyScraper:
    """Scrapes one or more faculty directory pages into a single CSV."""

    def __init__(self, out_csv):
        self.out_csv = out_csv
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = {}
        self.last_request = 0.0
        self.known_emails = self._load_known_emails()

    # ---------- master CSV ----------

    def _load_known_emails(self):
        if not os.path.exists(self.out_csv):
            return set()
        with open(self.out_csv, newline="", encoding="utf-8-sig") as f:
            return {row["Email"].lower() for row in csv.DictReader(f) if row.get("Email")}

    def append_rows(self, rows):
        """Append rows whose email isn't already in the CSV. Returns count added.

        Safe to call from several threads or processes writing the same CSV.
        """
        with csv_lock(self.out_csv):
            self.known_emails = self._load_known_emails()
            return self._append_unlocked(rows)

    def _append_unlocked(self, rows):
        new_rows, batch_emails = [], set()
        for r in rows:
            key = r["Email"].lower()
            if key not in self.known_emails and key not in batch_emails:
                batch_emails.add(key)
                new_rows.append(r)
        if not new_rows:
            return 0
        write_header = not os.path.exists(self.out_csv) or os.path.getsize(self.out_csv) == 0
        with open(self.out_csv, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        self.known_emails.update(r["Email"].lower() for r in new_rows)
        return len(new_rows)

    # ---------- fetching ----------

    def allowed_by_robots(self, url):
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if root not in self.robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(root + "/robots.txt", timeout=20)
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                parser.parse([])
            self.robots[root] = parser
        return self.robots[root].can_fetch(USER_AGENT, url)

    def fetch(self, url):
        if not self.allowed_by_robots(url):
            log.warning("robots.txt disallows %s - skipping", url)
            return None
        wait = REQUEST_DELAY_SECONDS - (time.time() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            self.last_request = time.time()
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.ConnectionError:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))

    # ---------- parsing ----------

    @staticmethod
    def clean_email(href):
        email = unquote(href)
        while email.lower().startswith("mailto:"):
            email = email[7:]
        email = email.split("?")[0].strip().strip(".")
        return email if EMAIL_RE.match(email) else None

    @staticmethod
    def normalize_name(raw):
        name = re.sub(r"\s+", " ", raw).strip(" ,")
        name = re.sub(r",?\s*(Ph\.?\s?D\.?|M\.?D\.?)$", "", name).strip(" ,")
        # "Last, First M." -> "First M. Last" (leave "Last, Jr., First" etc. as-is)
        if name.count(",") == 1:
            last, first = (p.strip() for p in name.split(","))
            if first and last:
                name = f"{first} {last}"
        return name

    @staticmethod
    def looks_like_name(text):
        return (
            3 <= len(text) <= 60
            and NAME_WORDS[0] <= len(text.split()) <= NAME_WORDS[1]
            and "@" not in text
            and NAME_RE.match(text) is not None
            and not NOT_A_NAME.search(text)
        )

    def find_name(self, card):
        """First name-looking heading/link, else bold text, else plain text block in the card."""
        for tags in NAME_TAG_GROUPS:
            for el in card.find_all(tags):
                href = el.get("href", "") if el.name == "a" else ""
                if href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
                if self.looks_like_name(text):
                    return text
        return None

    @staticmethod
    def find_title(node):
        for line in node.get_text("\n", strip=True).split("\n"):
            line = re.sub(r"\s+", " ", line)
            if TITLE_RE.search(line) and len(line) < 100:
                return line
        return ""

    def find_name_and_title(self, card):
        name = self.find_name(card)
        return (name, self.find_title(card)) if name else (None, "")

    def ordered_emails(self, node):
        emails = []
        for a in node.find_all("a", href=re.compile(r"^\s*mailto:", re.I)):
            email = self.clean_email(a["href"].strip())
            if email and email.lower() not in (e.lower() for e in emails):
                emails.append(email)
        return emails

    def text_emails(self, node):
        emails = []
        for match in re.findall(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", node.get_text(" ")):
            email = self.clean_email(match)
            if email and email.lower() not in (e.lower() for e in emails):
                emails.append(email)
        return emails

    def emails_in(self, node):
        return {e.lower() for e in self.ordered_emails(node)}

    def extract_people(self, soup):
        """Pair every mailto: email with the name in its enclosing card.

        The card is the largest ancestor of the mailto link that still contains
        only that one email address, i.e. this person's whole directory entry.
        """
        people = {}
        for link in soup.find_all("a", href=re.compile(r"^\s*mailto:", re.I)):
            email = self.clean_email(link["href"].strip())
            if not email or email.lower() in people:
                continue
            card = link
            while card.parent is not None and card.parent.name not in ("body", "html", "[document]"):
                parent = card.parent
                if len(self.emails_in(parent)) > 1 or len(parent.get_text()) > MAX_CARD_TEXT_LENGTH:
                    break
                card = parent
            name, title = self.find_name_and_title(card)
            if name:
                people[email.lower()] = (self.normalize_name(name), email, title)
            else:
                log.debug("No name found for %s", email)
        return list(people.values())

    @staticmethod
    def _listing_path(path):
        """Path with any WordPress-style /page/N/ suffix removed."""
        return re.sub(r"/page/\d+/?$", "", path).rstrip("/")

    def pagination_links(self, soup, page_url):
        """Links to other pages of the same listing (?page=N or /page/N/)."""
        here = urlparse(page_url)
        links = set()
        for a in soup.find_all("a", href=True):
            url = urljoin(page_url, a["href"])
            parsed = urlparse(url)
            if parsed.netloc != here.netloc or self._listing_path(parsed.path) != self._listing_path(here.path):
                continue
            if "page" in parse_qs(parsed.query) or re.search(r"/page/\d+/?$", parsed.path):
                links.add(url.split("#")[0])
        return links

    # ---------- profile pages ----------

    def profile_name(self, soup):
        h1 = soup.find("h1")
        if h1:
            text = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
            if self.looks_like_name(text):
                return text
        og = soup.find("meta", property="og:title")
        candidates = [og.get("content", "")] if og else []
        if soup.title:
            candidates.append(soup.title.get_text())
        for c in candidates:
            text = re.split(r"\s+[|\-–—]\s+", c.strip())[0]
            if self.looks_like_name(text):
                return text
        return None

    @staticmethod
    def best_email_for(name, emails):
        """Prefer an email whose local part contains a piece of the person's name."""
        parts = [p.lower() for p in re.findall(r"[^\W\d_]{3,}", name)]
        for email in emails:
            local = email.split("@")[0].lower()
            if any(p[:4] in local for p in parts):
                return email
        return emails[0] if emails else None

    def scrape_profiles(self, urls, max_profiles=None):
        """Visit each profile page and return (name, email, title, url) tuples."""
        pages, counts = [], {}
        for url in urls[:max_profiles or MAX_PROFILES_PER_DIRECTORY]:
            try:
                resp = self.fetch(url)
            except requests.RequestException as e:
                log.warning("Profile %s failed: %s", url, e)
                continue
            if resp is None:
                continue
            soup = BeautifulSoup(resp.content, "html.parser")
            main = soup.find("main") or soup
            # Some sites print the address as plain text instead of a mailto: link.
            emails = self.ordered_emails(main) or self.text_emails(main)
            for e in emails:
                counts[e.lower()] = counts.get(e.lower(), 0) + 1
            pages.append((url, self.profile_name(soup), emails, self.find_title(main)))
        people = []
        for url, name, emails, title in pages:
            own = [e for e in emails if counts[e.lower()] < SHARED_EMAIL_MIN_PROFILES]
            email = self.best_email_for(name, own) if name else None
            if name and email:
                people.append((self.normalize_name(name), email, title, url))
            else:
                log.debug("No name/email on profile %s", url)
        return people

    # ---------- driver ----------

    def scrape_directory(self, university, department, url, profile_links=None, faculty_only=False, max_profiles=None):
        """Scrape one directory listing (following its pagination).

        profile_links: regex for profile URLs on the listing. When set, emails are
            read from each person's profile page instead of the listing itself.
        faculty_only: keep only people whose title looks like a faculty position.
        """
        profile_re = re.compile(profile_links) if profile_links else None
        found, profile_urls, seen_pages, queue = [], [], set(), [url]
        while queue and len(seen_pages) < MAX_PAGES_PER_DIRECTORY:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            resp = self.fetch(page_url)
            if resp is None:
                continue
            soup = BeautifulSoup(resp.content, "html.parser")
            if profile_re:
                for a in (soup.find("main") or soup).find_all("a", href=True):
                    link = urljoin(resp.url, a["href"]).split("#")[0]
                    if profile_re.search(link) and link not in profile_urls:
                        profile_urls.append(link)
            else:
                found.extend((n, e, t, page_url) for n, e, t in self.extract_people(soup))
            queue.extend(sorted(self.pagination_links(soup, page_url) - seen_pages))
        if profile_re:
            log.info("%s: visiting %d profile pages", department, len(profile_urls))
            found = self.scrape_profiles(profile_urls, max_profiles)

        rows, seen_emails = [], set()
        today = dt.date.today().isoformat()
        for name, email, title, source in found:
            if email.lower() in seen_emails:
                continue
            if faculty_only and (not FACULTY_RE.search(title) or NOT_FACULTY_RE.search(title)):
                continue
            seen_emails.add(email.lower())
            rows.append({
                "Name": name,
                "Email": email,
                "Title": title,
                "Department": department,
                "University": university,
                "Source URL": source,
                "Date Added": today,
            })
        return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="departments.json")
    ap.add_argument("--out", default="faculty_emails.csv")
    ap.add_argument("--only", nargs="*", help="only scrape these department names")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler("scraper.log", encoding="utf-8"), logging.StreamHandler()],
    )

    with open(args.config, encoding="utf-8") as f:
        directories = json.load(f)
    if args.only:
        wanted = {d.lower() for d in args.only}
        directories = [d for d in directories if d["department"].lower() in wanted]

    scraper = FacultyScraper(args.out)
    total_added = 0
    for d in directories:
        try:
            rows = scraper.scrape_directory(
                d["university"], d["department"], d["url"],
                profile_links=d.get("profile_links"), faculty_only=d.get("faculty_only", False),
            )
        except requests.RequestException as e:
            log.error("%s / %s failed: %s", d["university"], d["department"], e)
            continue
        added = scraper.append_rows(rows)
        total_added += added
        log.info("%-40s found %3d, added %3d new", f'{d["university"]} / {d["department"]}', len(rows), added)
        if not rows:
            log.warning("No name+email pairs found at %s - the page may hide emails or load them with JavaScript", d["url"])

    log.info("Done. %d new rows added; %d people total in %s", total_added, len(scraper.known_emails), args.out)


if __name__ == "__main__":
    main()
