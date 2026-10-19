"""
Multi-university faculty scraper.

For every university in universities.json and every department in DEPARTMENTS,
this automatically:
  1. finds the department's website (links on the university's academics /
     college pages, then common subdomains like physics.<domain>),
  2. finds its faculty listing (Faculty / People / Directory links, common paths),
  3. scrapes it with FacultyScraper - from the listing itself, or, when the
     listing has no emails, from each person's profile page,
and appends everyone to the same master CSV used by faculty_scraper.py.

Progress is saved to discovered.json after every department, so a stopped run
can simply be restarted and will skip what's already done. That file also
records which URL each department's data came from, for checking or for
copying into departments.json.

Usage:
    python multi_scraper.py                          # all universities
    python multi_scraper.py --only "Purdue University"
    python multi_scraper.py --workers 4 --retry-failed
"""

import argparse
import concurrent.futures
import json
import logging
import os
import re
import socket
import threading
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import faculty_scraper as fs

# (department, regex matched against link text, subdomain guesses)
DEPARTMENTS = [
    ("Electrical and Computer Engineering", r"electrical", ["ece", "eecs", "ee"]),
    ("Computer Science", r"^computer science|department of computer science|computer science (and|&) engineering", ["cs", "cse", "eecs"]),
    ("Mechanical Engineering", r"mechanical", ["me", "mae", "meche", "mechse"]),
    ("Biomedical Engineering", r"bioengineering|biomedical engineering", ["bme", "bioe", "be"]),
    ("Aerospace Engineering", r"aerospace|aeronautic", ["aero", "aae", "ae", "aeroastro"]),
    ("Civil and Environmental Engineering", r"civil", ["cee", "ce", "civil"]),
    ("Chemical Engineering", r"chemical (and [a-z]+ )?engineering|chemical (&|and) bio", ["che", "chbe", "cheme", "chemeng"]),
    ("Materials Science and Engineering", r"materials science|materials engineering", ["mse", "dmse", "materials"]),
    ("Mathematics", r"^mathematics$|department of mathematics|^math(ematical sciences)?$", ["math", "mathematics", "www-math"]),
    ("Physics", r"^physics|department of physics|physics (and|&) astronomy", ["physics"]),
    ("Astronomy", r"astronomy|astrophysic", ["astro", "astronomy"]),
    ("Chemistry", r"^chemistry|department of chemistry", ["chem", "chemistry"]),
    ("Biology", r"^biology$|biological sciences|department of biology|^molecular (and|&) cell", ["bio", "biology", "biosci", "mcb"]),
    ("Earth and Atmospheric Sciences", r"earth|atmospheric|geolog|geoscience|geophysic", ["eas", "eps", "geology", "geosciences", "eaps", "atmos"]),
    ("Psychology", r"psycholog", ["psych", "psychology", "psy"]),
    ("Economics", r"^economics|department of economics", ["econ", "economics"]),
    ("Sociology", r"sociolog", ["soc", "sociology"]),
    ("Political Science", r"political science|^government$|department of government|^politics$", ["polisci", "gov", "government", "politics"]),
    ("Anthropology", r"anthropolog", ["anth", "anthro", "anthropology"]),
    ("Geography", r"geograph", ["geog", "geography"]),
    ("Criminology", r"criminolog|criminal justice", ["crim", "criminology"]),
    ("Linguistics", r"linguistic", ["linguistics", "ling"]),
    ("English", r"^english|department of english", ["english"]),
    ("History", r"^history$|department of history", ["history"]),
    ("Philosophy", r"philosoph", ["philosophy", "phil"]),
    ("Classics", r"classic", ["classics"]),
    ("Art History", r"history of art|art history", ["arthistory", "histart", "arthist"]),
    ("Art", r"^art$|^art (and|&) design|department of art|^visual arts|^fine arts", ["art", "arts", "visarts"]),
    ("Music", r"music", ["music"]),
    ("Theatre and Dance", r"theat(re|er)|dance|performance studies", ["theatre", "theater", "dance", "tdps"]),
    ("Communication", r"^communication|department of communication", ["comm", "communication"]),
    ("Languages and Literatures", r"languages|literatures|romance|comparative literature", ["languages", "complit", "romance"]),
    ("Gender Studies", r"gender|women.s (and gender )?studies", ["wgs", "wgss", "gender"]),
    ("American Studies", r"american studies", ["amst", "americanstudies"]),
    ("Jewish Studies", r"jewish|judaic", ["jewishstudies", "judaic"]),
    ("African American Studies", r"african american|africana|black studies|african (and|&) african", ["aas", "africana", "aaas"]),
    ("Business", r"business|school of management|management school", ["business", "gsb", "som"]),
    ("Education", r"school of education|college of education|graduate school of education|^education$", ["education", "gse", "soe"]),
    ("Public Health", r"public health|epidemiolog", ["publichealth", "sph"]),
    ("Kinesiology", r"kinesiolog|exercise science|health and kinesiology", ["kinesiology", "hk"]),
    ("Public Policy", r"public policy|public affairs|school of policy", ["publicpolicy", "spp", "policy"]),
    ("Journalism", r"journalism", ["journalism"]),
    ("Information Science", r"information school|school of information|information science", ["ischool", "si", "infosci"]),
    ("Architecture", r"architecture", ["arch", "architecture"]),
    ("Agricultural Economics", r"agricultural (and resource )?economics|agricultural (and|&) applied economics", ["are", "agecon", "arec"]),
    ("Animal Science", r"animal sci", ["ansc", "animalscience", "ans"]),
    ("Entomology", r"entomolog", ["entomology", "entm"]),
    ("Environmental Science", r"environmental science|environmental studies", ["envs", "environment", "ess"]),
    ("Nutrition and Food Science", r"nutrition|food science", ["nutrition", "foodscience"]),
    ("Plant Sciences", r"plant (and soil )?science|plant biology|plant sciences|agronomy|horticulture", ["plantsciences", "plantbio", "agry"]),
    ("Veterinary Medicine", r"veterinary", ["vet", "vetmed"]),
]

INDEX_PATHS = ["/", "/academics", "/academics/departments", "/departments", "/academics/schools-colleges",
               "/academics/colleges-schools", "/schools-and-colleges", "/academics/departments-programs", "/a-z"]
# College / school sites that usually list their departments.
COLLEGE_SUBDOMAINS = ["engineering", "eng", "coe", "science", "sciences", "cos", "las", "cla", "cas", "artsci", "as",
                      "humanities", "socsci", "liberalarts", "arts", "fas", "ls", "letters", "ag", "cals", "cfaes",
                      "agriculture", "hhs", "education", "business", "publichealth", "sph", "fineart"]
COLLEGE_LINK_RE = re.compile(r"\b(college|school) of\b|\bschool$|\bcollege$|faculty of", re.I)
MAX_COLLEGE_PAGES = 25
FACULTY_LINK_TEXT_RE = re.compile(
    r"^(our |all |full[- ]time |core |ladder |regular )?(faculty|people|directory|faculty (directory|list|members|& staff|and staff))$", re.I
)
FACULTY_PATHS = ["/people/faculty", "/faculty", "/people", "/directory", "/faculty-directory", "/people/faculty.html",
                 "/faculty.html", "/people/faculty-directory", "/about/people", "/directory/faculty"]
MIN_PEOPLE = 5
MAX_AUTO_PROFILES = 150
SKIP_LINK_RE = re.compile(r"news|event|calendar|giving|donate|apply|admission|alumni|login|\.pdf$|mailto:|tel:", re.I)

log = logging.getLogger("multi_scraper")
progress_lock = threading.Lock()


def load_progress(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(path, progress):
    with progress_lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=1)
        os.replace(tmp, path)


def host_exists(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


class UniversityScraper:
    def __init__(self, uni, out_csv, progress, progress_path, retry_failed):
        self.uni = uni
        self.name = uni["university"]
        self.domain = uni["domain"]
        self.scraper = fs.FacultyScraper(out_csv)
        self.progress = progress
        self.progress_path = progress_path
        self.retry_failed = retry_failed

    # ---------- helpers ----------

    def on_campus(self, url):
        host = urlparse(url).netloc.lower().split(":")[0]
        return host == self.domain or host.endswith("." + self.domain)

    def get(self, url):
        """Fetch an HTML page; returns (final_url, soup) or (None, None)."""
        try:
            resp = self.scraper.fetch(url)
        except requests.RequestException:
            return None, None
        if resp is None or "html" not in resp.headers.get("content-type", "html").lower():
            return None, None
        if len(resp.content) > 5_000_000:
            return None, None
        return resp.url, BeautifulSoup(resp.content, "html.parser")

    @staticmethod
    def links(base_url, soup):
        out = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if SKIP_LINK_RE.search(href):
                continue
            text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            out.append((text, urljoin(base_url, href).split("#")[0]))
        return out

    # ---------- step 1: department websites ----------

    def collect_campus_links(self):
        links, seen_pages = [], set()
        roots = [f"https://www.{self.domain}", f"https://{self.domain}"]
        for root in roots:
            for path in INDEX_PATHS:
                url, soup = self.get(root + path)
                if not soup or url in seen_pages:
                    continue
                seen_pages.add(url)
                links.extend(l for l in self.links(url, soup) if self.on_campus(l[1]))
            if links:
                break
        # One hop into college / school sites, where department lists usually live.
        colleges = [f"http://{sub}.{self.domain}/" for sub in COLLEGE_SUBDOMAINS if host_exists(f"{sub}.{self.domain}")]
        for text, url in links:
            if COLLEGE_LINK_RE.search(text) and url not in seen_pages and url not in colleges:
                colleges.append(url)
        for url in colleges[:MAX_COLLEGE_PAGES + len(COLLEGE_SUBDOMAINS)]:
            final, soup = self.get(url)
            if soup:
                seen_pages.add(final)
                links.extend(l for l in self.links(final, soup) if self.on_campus(l[1]))
        log.info("%s: collected %d campus links from %d pages", self.name, len(links), len(seen_pages))
        return links

    def find_department_site(self, campus_links, text_re, subdomains):
        rx = re.compile(text_re, re.I)
        candidates = []
        for text, url in campus_links:
            if text and len(text) < 90 and rx.search(text):
                path = urlparse(url).path.strip("/")
                # Prefer a department's own (sub)domain root, then short paths.
                candidates.append((0 if not path else 1, len(url), url))
        for slug in subdomains:
            for host in (f"{slug}.{self.domain}", f"www.{slug}.{self.domain}"):
                if host_exists(host):
                    # http:// so a host without its own certificate can redirect to the real site
                    candidates.append((2, 0, f"http://{host}/"))
                    break
        seen, ordered = set(), []
        for _, _, url in sorted(candidates):
            if url not in seen:
                seen.add(url)
                ordered.append(url)
        return ordered[:4]

    # ---------- step 2: faculty listing ----------

    def faculty_listing_candidates(self, site_url):
        final, soup = self.get(site_url)
        if not soup:
            return []
        cands = []
        for text, url in self.links(final, soup):
            if not self.on_campus(url):
                continue
            path = urlparse(url).path.lower()
            if FACULTY_LINK_TEXT_RE.match(text) or re.search(r"/(people/)?faculty(-directory)?(\.html)?/?$|/people/?$|/directory/?$", path):
                score = 0 if "faculty" in (text.lower() + path) else 1
                cands.append((score, url))
        base = "{0.scheme}://{0.netloc}".format(urlparse(final))
        prefix = urlparse(final).path.rstrip("/")
        for p in FACULTY_PATHS:
            cands.append((2, base + prefix + p))
            if prefix:
                cands.append((3, base + p))
        # Only accept listings on the department's own host and under its path, so a
        # "History" link on a college's About page can't pull in the college's whole directory.
        site = urlparse(final)
        site_path = site.path.rsplit("/", 1)[0] if "." in site.path.rsplit("/", 1)[-1] else site.path.rstrip("/")
        out, seen = [], set()
        for _, url in sorted(cands, key=lambda c: c[0]):
            parsed = urlparse(url)
            if parsed.netloc != site.netloc or not parsed.path.lower().startswith(site_path.lower()):
                continue
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out[:8]

    def auto_profile_pattern(self, page_url, soup):
        """Find the repeating profile-link pattern on a listing page, e.g. /people/<slug>."""
        groups = defaultdict(set)
        for a in (soup.find("main") or soup).find_all("a", href=True):
            url = urljoin(page_url, a["href"]).split("#")[0].split("?")[0]
            parsed = urlparse(url)
            if not self.on_campus(url) or SKIP_LINK_RE.search(url):
                continue
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) < 2 or not re.match(r"^[a-z0-9][a-z0-9._-]*$", parts[-1], re.I):
                continue
            groups[(parsed.scheme, parsed.netloc, "/".join(parts[:-1]))].add(url)
        if not groups:
            return None
        (scheme, netloc, prefix), urls = max(groups.items(), key=lambda kv: len(kv[1]))
        if len(urls) < 8:
            return None
        return "^" + re.escape(f"{scheme}://{netloc}{prefix}/") + r"[^/?#]+/?$"

    # ---------- step 3: scrape ----------

    def scrape_department(self, dept, text_re, subdomains, campus_links):
        best = {"status": "no_site", "people": 0}
        for site in self.find_department_site(campus_links, text_re, subdomains):
            best = {"status": "no_listing", "site": site, "people": 0}
            for listing in self.faculty_listing_candidates(site):
                faculty_page = "faculty" in listing.lower()
                try:
                    rows = self.scraper.scrape_directory(self.name, dept, listing, faculty_only=not faculty_page)
                except requests.RequestException:
                    continue
                if len(rows) >= MIN_PEOPLE:
                    return rows, {"status": "ok", "mode": "listing", "site": site, "url": listing,
                                  "faculty_only": not faculty_page, "people": len(rows)}
                # No emails on the listing: try the people's profile pages.
                final, soup = self.get(listing)
                pattern = self.auto_profile_pattern(final, soup) if soup else None
                if pattern:
                    try:
                        rows = self.scraper.scrape_directory(self.name, dept, listing, profile_links=pattern,
                                                             faculty_only=not faculty_page,
                                                             max_profiles=MAX_AUTO_PROFILES)
                    except requests.RequestException:
                        rows = []
                    if len(rows) >= MIN_PEOPLE:
                        return rows, {"status": "ok", "mode": "profiles", "site": site, "url": listing,
                                      "profile_links": pattern, "faculty_only": not faculty_page, "people": len(rows)}
                    best = {"status": "no_emails", "site": site, "url": listing, "people": len(rows)}
        return [], best

    def run(self):
        done = self.progress.setdefault(self.name, {})
        todo = [d for d in DEPARTMENTS
                if d[0] not in done or (self.retry_failed and done[d[0]].get("status") != "ok")]
        if not todo:
            log.info("%s: already complete", self.name)
            return 0
        campus_links = self.collect_campus_links()
        added_total = 0
        for dept, text_re, subdomains in todo:
            try:
                rows, info = self.scrape_department(dept, text_re, subdomains, campus_links)
            except Exception as e:  # never let one department kill the university
                log.exception("%s / %s crashed", self.name, dept)
                rows, info = [], {"status": "error", "error": str(e)[:200], "people": 0}
            info["added"] = self.scraper.append_rows(rows) if rows else 0
            added_total += info["added"]
            done[dept] = info
            save_progress(self.progress_path, self.progress)
            log.info("%-45s %-36s %-10s found %3d, added %3d  %s", self.name, dept, info["status"],
                     info.get("people", 0), info["added"], info.get("url", info.get("site", "")))
        log.info("=== %s finished: %d new people", self.name, added_total)
        return added_total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universities", default="universities.json")
    ap.add_argument("--out", default="faculty_emails.csv")
    ap.add_argument("--progress", default="discovered.json")
    ap.add_argument("--only", nargs="*", help="only these university names")
    ap.add_argument("--workers", type=int, default=6, help="universities scraped in parallel")
    ap.add_argument("--retry-failed", action="store_true", help="re-try departments that found nobody last time")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler("multi_scraper.log", encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger("faculty_scraper").setLevel(logging.ERROR)
    # Each worker thread handles a different university, so this is ~1 request/second per site.
    fs.REQUEST_DELAY_SECONDS = 1

    with open(args.universities, encoding="utf-8") as f:
        universities = json.load(f)
    if args.only:
        wanted = {u.lower() for u in args.only}
        universities = [u for u in universities if u["university"].lower() in wanted]

    progress = load_progress(args.progress)
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(UniversityScraper(u, args.out, progress, args.progress, args.retry_failed).run): u
                   for u in universities}
        for fut in concurrent.futures.as_completed(futures):
            try:
                total += fut.result()
            except Exception:
                log.exception("%s failed", futures[fut]["university"])

    summary = defaultdict(lambda: [0, 0])
    for uni, depts in progress.items():
        for info in depts.values():
            summary[uni][0] += info.get("status") == "ok"
            summary[uni][1] += info.get("people", 0)
    for uni, (ok, people) in sorted(summary.items()):
        log.info("SUMMARY %-45s %2d/%d departments, %4d people", uni, ok, len(DEPARTMENTS), people)
    log.info("Done. %d new people added this run.", total)


if __name__ == "__main__":
    main()
