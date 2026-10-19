"""
Show how far the multi-university scrape has got.

For every university in universities.json: departments attempted / total,
departments that yielded people, and how many people from it are in the CSV.

Usage:
    python status.py
    python status.py --universities universities.json --progress discovered.json --csv faculty_emails.csv
"""

import argparse
import csv
import json
import os
from collections import Counter

from multi_scraper import DEPARTMENTS, load_universities


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universities", default="universities.json")
    ap.add_argument("--progress", default="discovered.json")
    ap.add_argument("--csv", default="faculty_emails.csv")
    args = ap.parse_args()

    universities = [u["university"] for u in load_universities(args.universities)]
    progress = {}
    if os.path.exists(args.progress):
        with open(args.progress, encoding="utf-8") as f:
            progress = json.load(f)
    people, emails = Counter(), set()
    if os.path.exists(args.csv):
        with open(args.csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                people[row["University"]] += 1
                emails.add(row["Email"].strip().lower())

    total = len(DEPARTMENTS)
    complete, partial, not_started = [], [], []
    print(f"{'University':45} {'attempted':>9} {'ok':>4} {'people':>7}")
    for uni in universities:
        depts = progress.get(uni, {})
        ok = sum(d.get("status") == "ok" for d in depts.values())
        print(f"{uni:45} {len(depts):>4}/{total:<4} {ok:>4} {people[uni]:>7}")
        (complete if len(depts) >= total else partial if depts else not_started).append(uni)

    others = sum(n for uni, n in people.items() if uni not in universities)
    print(f"\nComplete: {len(complete)}  Partial: {len(partial)}  Not started: {len(not_started)}")
    if partial:
        print("Partial: " + ", ".join(partial))
    if not_started:
        print("Not started: " + ", ".join(not_started))
    print(f"CSV: {sum(people.values())} rows, {len(emails)} unique emails"
          + (f" ({others} from departments.json / other sources)" if others else ""))


if __name__ == "__main__":
    main()
