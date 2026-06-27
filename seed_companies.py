"""
One-time (or repeatable) import of companies.csv into the companies table.

    python seed_companies.py [path/to/companies.csv]

Safe to re-run — upserts on (name, source) so URL/slug fixes in the CSV
are applied on every run without losing existing data. Also re-activates
previously deactivated companies so the CSV is always the source of truth.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db


def seed(csv_path: Path | None = None) -> int:
    """Seed companies from CSV. Returns number of rows processed."""
    if csv_path is None:
        csv_path = Path(__file__).parent / "companies.csv"

    if not csv_path.exists():
        return 0

    added = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name     = (row.get("name")     or "").strip()
            source   = (row.get("source")   or "").strip().lower()
            slug     = (row.get("slug")     or "").strip() or None
            url      = (row.get("url")      or "").strip() or None
            priority = int((row.get("priority") or "0").strip() or 0)

            if not name or not source:
                continue

            db.upsert_company(name=name, source=source, slug=slug, url=url, priority=priority)
            added += 1

    return added


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    db.init_db()
    added = seed(csv_path)
    print(f"Processed {added} rows.")
    print(f"Companies table now has {len(db.get_all_active_companies())} active entries.")


if __name__ == "__main__":
    main()
