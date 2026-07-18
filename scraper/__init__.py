"""
scraper package — entry point used by bot.py.
Queries active companies from the DB and dispatches to the right ATS fetcher.
"""

import logging
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
from scraper.ats import (
    fetch_greenhouse,
    fetch_lever,
    fetch_ashby,
    fetch_smartrecruiters,
    fetch_workday,
    fetch_simplify,
    fetch_custom_company,
    fetch_oracle,
    fetch_adp,
    fetch_icims,
    fetch_github_md_table,
)

log = logging.getLogger("pertern.scraper")

_FETCHERS = {
    "greenhouse":      lambda c: fetch_greenhouse(c["slug"] or c["name"].lower().replace(" ", "")),
    "lever":           lambda c: fetch_lever(c["slug"] or c["name"].lower().replace(" ", "")),
    "ashby":           lambda c: fetch_ashby(c["slug"] or c["name"].lower().replace(" ", "")),
    "smartrecruiters": lambda c: fetch_smartrecruiters(c["slug"] or c["name"].lower().replace(" ", "")),
    "workday":         lambda c: fetch_workday(c),
    "simplify":        lambda c: fetch_simplify(c),
    "custom":          lambda c: fetch_custom_company(c),
    "oracle":          lambda c: fetch_oracle(c),
    "adp":             lambda c: fetch_adp(c),
    "icims":           lambda c: fetch_icims(c),
    "github_md":       lambda c: fetch_github_md_table(c),
}

# Seconds to wait between consecutive requests to the same ATS to avoid rate limits
_SOURCE_DELAY = {
    "workday": 2.0,
    "ashby":   1.5,
}


def run_all_scrapers(on_batch=None) -> list[dict]:
    """Synchronous — call from a thread pool executor.

    on_batch(company_name, jobs): called immediately after each company
    finishes scraping so callers can process/post jobs without waiting
    for all companies to finish.
    """
    companies = db.get_all_active_companies()
    all_jobs: list[dict] = []
    last_source_time: dict[str, float] = {}

    for company in companies:
        source = (company.get("source") or "").lower()
        fetcher = _FETCHERS.get(source)
        if not fetcher:
            log.warning("No fetcher for source '%s' (company: %s)", source, company["name"])
            continue

        # Rate-limit per ATS source
        delay = _SOURCE_DELAY.get(source, 0)
        if delay:
            elapsed = time.monotonic() - last_source_time.get(source, 0)
            if elapsed < delay:
                time.sleep(delay - elapsed)

        try:
            jobs = fetcher(company) or []
            log.info("  ✓ %-35s  %d jobs", company["name"], len(jobs))
            all_jobs.extend(jobs)
            db.reset_company_failures(company["name"], company["source"])
            if on_batch and jobs:
                on_batch(company["name"], jobs)
        except Exception as e:
            err_msg = f"[{type(e).__name__}] {e}"
            log.warning("  ✗ %-35s  %s", company["name"], err_msg)
            db.log_scrape_error(company["name"], source, err_msg)
            count, deactivated = db.record_company_failure(company["name"], company["source"])
            if deactivated:
                log.info("Deactivated %s after %d failures", company["name"], count)
        finally:
            last_source_time[source] = time.monotonic()

    log.info("Scraped %d companies → %d raw jobs", len(companies), len(all_jobs))
    return all_jobs
