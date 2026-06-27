"""
scraper package — entry point used by bot.py.
Queries active companies from the DB and dispatches to the right ATS fetcher.
"""

import logging
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
)

log = logging.getLogger("distern.scraper")

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
}


def run_all_scrapers(on_batch=None) -> list[dict]:
    """Synchronous — call from a thread pool executor.

    on_batch(company_name, jobs): called immediately after each company
    finishes scraping so callers can process/post jobs without waiting
    for all 310 companies to finish.
    """
    companies = db.get_all_active_companies()
    all_jobs: list[dict] = []

    for company in companies:
        source = (company.get("source") or "").lower()
        fetcher = _FETCHERS.get(source)
        if not fetcher:
            log.warning("No fetcher for source '%s' (company: %s)", source, company["name"])
            continue
        try:
            jobs = fetcher(company) or []
            log.info("  ✓ %-35s  %d jobs", company["name"], len(jobs))
            all_jobs.extend(jobs)
            db.reset_company_failures(company["name"], company["source"])
            if on_batch and jobs:
                on_batch(company["name"], jobs)
        except Exception as e:
            log.warning("  ✗ %-35s  %s", company["name"], e)
            count, deactivated = db.record_company_failure(company["name"], company["source"])
            if deactivated:
                log.info("Deactivated %s after %d failures", company["name"], count)

    log.info("Scraped %d companies → %d raw jobs", len(companies), len(all_jobs))
    return all_jobs
