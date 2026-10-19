"""
Push faculty_emails.csv to a Google Sheet, adding only rows whose email isn't
already in the sheet. Safe to run repeatedly.

Setup (one time):
  1. Google Cloud console: create a project, enable the Google Sheets API.
  2. Create a service account, add a JSON key, save it as service_account.json here.
  3. Share the sheet with the service account's email (Editor).

Usage:
  python sync_to_sheets.py
  python sync_to_sheets.py --csv faculty_emails.csv --sheet-id <id> --creds service_account.json
"""

import argparse
import csv

import gspread

from faculty_scraper import CSV_COLUMNS

DEFAULT_SHEET_ID = "1eAYKjR1S6Ag9Atgp0v72wqimI1GklKtQj4q9-KhpG7E"
BATCH_SIZE = 5000  # rows per append call, well under the API's request size limit


def sync(csv_path, sheet_id, creds_path):
    worksheet = gspread.service_account(filename=creds_path).open_by_key(sheet_id).sheet1

    header = worksheet.row_values(1)
    if header != CSV_COLUMNS:
        worksheet.update([CSV_COLUMNS], "A1")

    email_col = CSV_COLUMNS.index("Email") + 1
    known = {e.strip().lower() for e in worksheet.col_values(email_col)[1:] if e.strip()}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        new_rows = [[row.get(c, "") for c in CSV_COLUMNS]
                    for row in csv.DictReader(f)
                    if row["Email"].strip().lower() not in known]

    # RAW keeps values as text, so nothing gets reinterpreted as a number or date
    for start in range(0, len(new_rows), BATCH_SIZE):
        worksheet.append_rows(new_rows[start:start + BATCH_SIZE], value_input_option="RAW")

    print(f"{len(new_rows)} new rows added; {len(known) + len(new_rows)} people in the sheet")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default="faculty_emails.csv")
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--creds", default="service_account.json")
    args = parser.parse_args()
    sync(args.csv, args.sheet_id, args.creds)


if __name__ == "__main__":
    main()
