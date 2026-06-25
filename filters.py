"""
Per-user job filtering for DisTern.
Handles categories, subcategories, countries, cities, terms, remote pref, and keywords.
"""

import json


def matches_user_prefs(job: dict, prefs: dict) -> bool:
    """Return True if this job should be delivered to the user based on their preferences."""

    # ── Countries ────────────────────────────────────────────────────────────
    countries = json.loads(prefs.get("countries") or "[]")
    if countries and "🌐 Any / Worldwide" not in countries:
        loc = (job.get("location") or "").lower()
        # Strip emoji prefix for matching (e.g. "🇺🇸 United States" → "united states")
        country_names = [c.split(" ", 1)[-1].strip().lower() if " " in c else c.lower()
                         for c in countries]
        if not any(cn in loc for cn in country_names):
            return False

    # ── Cities (if user selected specific cities) ────────────────────────────
    cities = json.loads(prefs.get("cities") or "[]")
    if cities:
        loc = (job.get("location") or "").lower()
        if not any(city.lower() in loc for city in cities):
            # "Remote" city selection matches remote jobs anywhere in that country
            if not ("remote" in [ci.lower() for ci in cities] and "remote" in loc):
                return False

    # ── Categories (main) ────────────────────────────────────────────────────
    fields = json.loads(prefs.get("fields") or "[]")
    if fields and "All Fields" not in fields:
        job_cat = job.get("category") or ""
        if job_cat not in fields:
            return False

    # ── Subcategories ────────────────────────────────────────────────────────
    subcategories = json.loads(prefs.get("subcategories") or "[]")
    if subcategories:
        job_sub = job.get("subcategory") or ""
        if job_sub and job_sub not in subcategories:
            return False

    # ── Year / term ──────────────────────────────────────────────────────────
    terms = json.loads(prefs.get("terms") or "[]")
    if terms and "Any Year" not in terms:
        term = (job.get("term") or "").lower()
        if term and not any(t.lower() in term for t in terms):
            return False

    # ── Remote preference ────────────────────────────────────────────────────
    remote_pref = prefs.get("remote_pref", "any")
    loc_lower = (job.get("location") or "").lower()
    if remote_pref == "remote" and "remote" not in loc_lower:
        return False
    if remote_pref == "onsite" and "remote" in loc_lower:
        return False

    # ── Keywords (comma-separated, any must match title/company/description) ─
    keywords = (prefs.get("keywords") or "").strip()
    if keywords:
        text = f"{job.get('title','')} {job.get('company','')} {job.get('description','')}".lower()
        kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
        if kws and not any(kw in text for kw in kws):
            return False

    return True
