import hashlib
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_INTERN_RE = re.compile(r'\bintern(ship)?\b', re.IGNORECASE)

# Broader whitelist — anything that signals a student / early-career role
_INTERN_WHITELIST = re.compile(
    r'\b(intern(ship)?|co[-\s]?op|placement|apprentice|trainee|'
    r'summer\s+analyst|summer\s+associate|student\s+(worker|developer|engineer|researcher)|'
    r'graduate\s+(program|scheme|trainee)|rotational\s+program|'
    r'early\s+career|new\s+grad|entry[\s-]level\s+program|'
    r'fellowship|externship|practicum|junior\s+intern|'
    r'associate\s+intern|technology\s+program)\b',
    re.IGNORECASE,
)

# Titles with these words are almost certainly full-time senior roles
_FULLTIME_BLACKLIST = re.compile(
    r'\b(senior|sr\.|staff|principal|lead\s+(engineer|developer|scientist|analyst)|'
    r'director|manager|head\s+of|vp\s+of|vice\s+president|chief|'
    r'cto|cfo|ceo|coo|partner|full[- ]time(?!\s+intern)|permanent)\b',
    re.IGNORECASE,
)


def is_internship_title(title: str) -> bool:
    """Return True only if the job title looks like an internship or student role."""
    if _INTERN_WHITELIST.search(title):
        return True
    if _FULLTIME_BLACKLIST.search(title):
        return False
    # No explicit intern signal → reject to avoid polluting the feed
    return False

USER_AGENT = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def make_id(source, company, title, url):
    raw = f"{source}:{company}:{title}:{url}"
    return hashlib.sha256(raw.encode()).hexdigest()


def clean_text(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def fetch_greenhouse(company_slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    r = requests.get(url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        if not is_internship_title(title):
            continue
        # Fetch full description from detail endpoint
        desc = ""
        try:
            detail = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs/{job.get('id')}",
                headers=USER_AGENT, timeout=15,
            )
            if detail.ok:
                html = detail.json().get("content", "")
                desc = clean_text(BeautifulSoup(html, "html.parser").get_text(" "))[:1500]
        except Exception:
            pass
        jobs.append({
            "job_id": f"greenhouse:{company_slug}:{job.get('id')}",
            "company": company_slug,
            "source": "Greenhouse",
            "title": title,
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "description": desc,
        })
    return jobs


def fetch_lever(company_slug):
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    r = requests.get(url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for job in data:
        title = job.get("text", "")
        if not is_internship_title(title):
            continue
        categories = job.get("categories", {}) or {}
        jobs.append({
            "job_id": f"lever:{company_slug}:{job.get('id')}",
            "company": company_slug,
            "source": "Lever",
            "title": title,
            "location": categories.get("location", ""),
            "url": job.get("hostedUrl", ""),
            "description": job.get("descriptionPlain", "") or "",
        })
    return jobs


def fetch_ashby(company_slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    r = requests.get(url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        if not is_internship_title(title):
            continue
        location_obj = job.get("location")
        location = location_obj.get("locationName", "") if isinstance(location_obj, dict) else ""
        jobs.append({
            "job_id": f"ashby:{company_slug}:{job.get('id')}",
            "company": company_slug,
            "source": "Ashby",
            "title": title,
            "location": location,
            "url": job.get("jobUrl", ""),
            "description": job.get("descriptionPlain", "") or "",
        })
    return jobs


def fetch_smartrecruiters(company_slug):
    url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings"
    r = requests.get(url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for job in data.get("content", []):
        title = job.get("name", "")
        if not is_internship_title(title):
            continue
        loc = job.get("location", {}) or {}
        location_text = ", ".join(
            p for p in [loc.get("city", ""), loc.get("region", ""), loc.get("country", "")] if p
        )
        jobs.append({
            "job_id": f"smartrecruiters:{company_slug}:{job.get('id')}",
            "company": company_slug,
            "source": "SmartRecruiters",
            "title": title,
            "location": location_text,
            "url": job.get("ref", ""),
            "description": "",
        })
    return jobs


def _workday_post(api_url, payload, headers):
    """POST to Workday API with up to 3 payload variations before giving up."""
    r = requests.post(api_url, json=payload, headers=headers, timeout=30)
    if r.status_code == 422:
        # Some boards reject searchText
        p2 = {k: v for k, v in payload.items() if k != "searchText"}
        r = requests.post(api_url, json=p2, headers=headers, timeout=30)
    if r.status_code == 422:
        # Some boards reject appliedFacets too — bare minimum
        r = requests.post(
            api_url,
            json={"limit": payload.get("limit", 20), "offset": payload.get("offset", 0)},
            headers=headers,
            timeout=30,
        )
    if r.status_code == 422:
        return None   # board uses non-standard API, skip silently
    r.raise_for_status()
    return r


def fetch_workday(company):
    """
    Uses Workday's JSON API instead of scraping HTML.
    Workday is a JS-rendered SPA; plain GET returns nothing useful.

    URL format:  https://{tenant}.wd{N}.myworkdayjobs.com/{Board}
    API endpoint: POST https://{domain}/wday/cxs/{tenant}/{board}/jobs
    """
    company_name = company["name"]
    parsed = urlparse(company["url"])
    domain = parsed.netloc          # pfizer.wd1.myworkdayjobs.com
    tenant = domain.split(".")[0]   # pfizer
    board  = parsed.path.strip("/") # PfizerCareers

    api_url = f"https://{domain}/wday/cxs/{tenant}/{board}/jobs"
    headers = {**USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"}

    jobs, offset, limit = [], 0, 20
    while True:
        payload = {"limit": limit, "offset": offset, "searchText": "intern", "appliedFacets": {}}
        r = _workday_post(api_url, payload, headers)
        if r is None:
            break   # board rejected all payload variants
        data = r.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            ext_path = p.get("externalPath", "")
            # externalPath is relative to the board (e.g. /job/Location/Title_ID)
            # Prepend the board so the URL resolves: domain/board/job/Location/Title_ID
            url = f"https://{domain}/{board}{ext_path}" if ext_path else ""
            jobs.append({
                "job_id":      make_id("workday", company_name, p.get("title", ""), url),
                "company":     company_name,
                "source":      "Workday",
                "title":       p.get("title", ""),
                "location":    p.get("locationsText", ""),
                "url":         url,
                "description": "",
            })
        offset += limit
        if offset >= data.get("total", 0) or offset >= 200:
            break
    return jobs


def fetch_simplify(company):
    """
    Fetches the SimplifyJobs GitHub internship listings JSON.
    URL in companies.csv should point to the raw GitHub JSON, e.g.:
    https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json
    """
    r = requests.get(company["url"], headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for item in data:
        if not item.get("active", True):
            continue
        company_name = item.get("company_name", "")
        title        = item.get("title", "")
        url          = item.get("url", "")
        locations    = item.get("locations", [])
        location     = ", ".join(str(loc) for loc in locations) if locations else ""
        sponsorship  = item.get("sponsorship", "")
        # Carry the season/term field that Simplify includes in their JSON
        # (e.g. "Summer 2027", "Spring 2027") so the 2027 filter can use it.
        term_raw     = item.get("term") or item.get("season") or ""
        desc_parts   = []
        if term_raw:
            desc_parts.append(term_raw)
        if sponsorship:
            desc_parts.append(f"Sponsorship: {sponsorship}")
        jobs.append({
            "job_id":      make_id("simplify", company_name, title, url),
            "company":     company_name,
            "source":      "Simplify",
            "title":       title,
            "location":    location,
            "url":         url,
            "description": " | ".join(desc_parts),
        })
    return jobs


def looks_like_job_link(title, href):
    text = f"{title} {href}".lower()
    if not is_internship_title(text):
        return False
    bad = [
        "blog", "article", "story", "stories", "news", "event", "events",
        "faq", "benefits", "culture", "life-at", "students", "programs",
        "internship-program", "internships-at", "search", "search-results",
        "job-search", "privacy", "terms", "login", "sign-in",
    ]
    if any(w in text for w in bad):
        return False
    good_url = [
        "/job/", "/jobs/", "jobid", "job_id", "requisition", "requisitions",
        "req", "gh_jid", "lever.co", "ashbyhq", "smartrecruiters",
        "myworkdayjobs", "oraclecloud",
    ]
    return any(w in href.lower() for w in good_url)


def extract_location_from_text(text):
    known = [
        "Charlotte, NC", "Raleigh, NC", "Atlanta, GA", "New York, NY",
        "Washington, D.C.", "San Francisco, CA", "Seattle, WA", "Austin, TX",
        "Dallas, TX", "Chicago, IL", "Boston, MA", "Denver, CO",
        "Los Angeles, CA", "Remote", "United States",
    ]
    tl = text.lower()
    for loc in known:
        if loc.lower() in tl:
            return loc
    return "United States"


def fetch_custom_company(company):
    company_name = company["name"]
    start_url = company["url"]
    r = requests.get(start_url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    jobs, seen_urls = [], set()
    for link in soup.find_all("a"):
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        if not title or not href:
            continue
        full_url = urljoin(start_url, href)
        if full_url in seen_urls or not looks_like_job_link(title, full_url):
            continue
        seen_urls.add(full_url)
        nearby = clean_text(link.parent.get_text(" ", strip=True)) if link.parent else title
        jobs.append({
            "job_id":      make_id("custom", company_name, title, full_url),
            "company":     company_name,
            "source":      "Custom Career Page",
            "title":       title,
            "location":    extract_location_from_text(nearby),
            "url":         full_url,
            "description": nearby[:1000],
        })
    return jobs


def fetch_oracle(company):
    company_name = company["name"]
    start_url = company["url"]
    r = requests.get(start_url, headers=USER_AGENT, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    jobs, seen_urls = [], set()
    for link in soup.find_all("a"):
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        if not title or not href:
            continue
        full_url = urljoin(start_url, href)
        if full_url in seen_urls:
            continue
        text = f"{title} {full_url}".lower()
        if not is_internship_title(title):
            continue
        if not ("oraclecloud" in full_url.lower() or "requisition" in full_url.lower() or "job" in full_url.lower()):
            continue
        seen_urls.add(full_url)
        nearby = clean_text(link.parent.get_text(" ", strip=True)) if link.parent else title
        jobs.append({
            "job_id":      make_id("oracle", company_name, title, full_url),
            "company":     company_name,
            "source":      "Oracle",
            "title":       title,
            "location":    extract_location_from_text(nearby),
            "url":         full_url,
            "description": nearby[:1000],
        })
    return jobs


def fetch_usajobs(api_key: str, email: str) -> list[dict]:
    """
    Scrape USAJobs (data.usajobs.gov) for internships matching the resume.
    Requires a free API key from https://developer.usajobs.gov/
    """
    if not api_key or not email:
        return []

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": api_key,
    }

    # Targeted searches matching resume focus areas
    keywords = [
        "cybersecurity intern",
        "information security intern",
        "IT intern",
        "cloud intern",
        "data analyst intern",
        "network security intern",
        "computer science intern",
        "intelligence analyst intern",
    ]

    seen: set[str] = set()
    jobs: list[dict] = []

    for kw in keywords:
        try:
            r = requests.get(
                "https://data.usajobs.gov/api/search",
                params={
                    "Keyword":        kw,
                    "ResultsPerPage": 25,
                    "WhoMayApply":    "public",
                    "DatePosted":     60,
                },
                headers=headers,
                timeout=20,
            )
            if not r.ok:
                continue
            items = (
                r.json()
                .get("SearchResult", {})
                .get("SearchResultItems", [])
            )
            for item in items:
                pos    = item.get("MatchedObjectDescriptor", {})
                job_id = pos.get("PositionID", "")
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)

                title = pos.get("PositionTitle", "")
                if not is_internship_title(title):
                    continue

                locs     = pos.get("PositionLocation", [])
                location = locs[0].get("LocationName", "") if locs else ""

                pay = pos.get("PositionRemuneration", [{}])
                salary = ""
                if pay:
                    lo = pay[0].get("MinimumRange", "")
                    hi = pay[0].get("MaximumRange", "")
                    rt = pay[0].get("RateIntervalCode", "")
                    if lo and hi:
                        salary = f"${float(lo):,.0f}–${float(hi):,.0f} {rt}"

                apply_uris = pos.get("ApplyURI", [])
                url = apply_uris[0] if apply_uris else pos.get("PositionURI", "")

                close_date = pos.get("ApplicationCloseDate", "")[:10] if pos.get("ApplicationCloseDate") else ""

                jobs.append({
                    "job_id":      f"usajobs:{job_id}",
                    "company":     pos.get("OrganizationName", "US Government"),
                    "source":      "USAJobs",
                    "title":       title,
                    "location":    location,
                    "url":         url,
                    "description": pos.get("QualificationSummary", "")[:1000],
                    "salary":      salary,
                    "deadline":    close_date,
                })
        except Exception:
            continue

    return jobs


def fetch_icims(company: dict) -> list[dict]:
    """
    iCIMS public jobs search API.
    URL format in CSV: https://{slug}.icims.com/jobs/search
    or: https://careers-{slug}.icims.com/jobs/search
    The slug is the company's iCIMS subdomain.
    """
    from urllib.parse import urlparse
    company_name = company["name"]
    raw_url = company.get("url", "")
    parsed = urlparse(raw_url)
    host = parsed.netloc  # e.g. careers-northropgrumman.icims.com

    api_base = f"https://{host}"
    headers = {
        **USER_AGENT,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }

    jobs = []
    page = 1

    while True:
        r = requests.get(
            f"{api_base}/jobs/search",
            params={
                "ss": "1",
                "searchRelation": "keyword_all",
                "searchKeyword": "intern",
                "searchLocation": "",
                "searchCategory": "",
                "in_iframe": "1",
                "page": page,
            },
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()

        try:
            data = r.json()
        except Exception:
            break

        postings = data.get("jobs") or data.get("results") or data.get("positions") or []
        if not postings:
            break

        for job in postings:
            title = job.get("jobtitle") or job.get("title") or job.get("Title") or ""
            if not is_internship_title(title):
                continue
            job_id = str(job.get("id") or job.get("jobId") or job.get("Id") or "")
            location = job.get("joblocation") or job.get("location") or ""
            if isinstance(location, dict):
                location = location.get("name") or location.get("city") or ""
            job_url = job.get("applyUrl") or job.get("url") or f"{api_base}/jobs/{job_id}/job"
            jobs.append({
                "job_id": f"icims:{host}:{job_id}",
                "company": company_name,
                "source": "iCIMS",
                "title": title,
                "location": str(location),
                "url": job_url,
                "description": "",
            })

        total = data.get("totalResults") or data.get("total") or 0
        if len(jobs) >= total or len(postings) == 0:
            break
        page += 1

    return jobs


def fetch_adp(company: dict) -> list[dict]:
    """
    ADP WorkforceNow public jobs API.
    URL format in CSV:  https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=XXXX
    The cid is the company's unique ADP client ID.
    """
    from urllib.parse import urlparse, parse_qs
    company_name = company["name"]
    raw_url = company.get("url", "")
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)
    cid = (params.get("cid") or params.get("client") or [None])[0]
    if not cid:
        raise ValueError(f"No cid found in ADP URL for {company_name}")

    api_url = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
    headers = {
        **USER_AGENT,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }

    jobs = []
    offset = 0
    limit = 50

    while True:
        r = requests.get(
            api_url,
            params={
                "cid": cid,
                "ccId": "19000101_000001",
                "type": "MP",
                "lang": "en_US",
                "selectedMenuKey": "CurrentOpenings",
                "offset": offset,
                "limit": limit,
            },
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()

        try:
            data = r.json()
        except Exception:
            break

        postings = data.get("jobPostings") or data.get("jobs") or []
        if not postings:
            break

        for job in postings:
            title = job.get("Title") or job.get("title") or ""
            if not is_internship_title(title):
                continue
            job_id = job.get("Id") or job.get("id") or job.get("jobId") or ""
            location = job.get("Location") or job.get("location") or ""
            if isinstance(location, dict):
                location = location.get("name") or location.get("locationName") or ""
            job_url = (
                f"https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
                f"?cid={cid}&ccId=19000101_000001&lang=en_US&jobId={job_id}"
            )
            jobs.append({
                "job_id": f"adp:{cid}:{job_id}",
                "company": company_name,
                "source": "ADP",
                "title": title,
                "location": str(location),
                "url": job_url,
                "description": "",
            })

        if len(postings) < limit:
            break
        offset += limit

    return jobs


def fetch_job_description(job: dict) -> str:
    """
    Fetch the full job description on-demand for a stored job.
    Returns plain text (up to 2000 chars) or empty string on failure.
    """
    url    = job.get("url", "")
    source = job.get("source", "").lower()

    try:
        # ── Greenhouse ────────────────────────────────────────────────────────
        if source == "greenhouse" and "greenhouse.io" in url:
            # job_id format: greenhouse:{slug}:{id}
            parts = job.get("job_id", "").split(":")
            if len(parts) == 3:
                slug, jid = parts[1], parts[2]
                r = requests.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}",
                    headers=USER_AGENT, timeout=15,
                )
                if r.ok:
                    html = r.json().get("content", "")
                    return clean_text(BeautifulSoup(html, "html.parser").get_text(" "))[:2000]

        # ── Lever ─────────────────────────────────────────────────────────────
        elif source == "lever" and "lever.co" in url:
            parts = job.get("job_id", "").split(":")
            if len(parts) == 3:
                slug, jid = parts[1], parts[2]
                r = requests.get(
                    f"https://api.lever.co/v0/postings/{slug}/{jid}",
                    headers=USER_AGENT, timeout=15,
                )
                if r.ok:
                    data = r.json()
                    plain = data.get("descriptionPlain", "") or ""
                    lists = data.get("lists", [])
                    for lst in lists:
                        plain += f"\n\n{lst.get('text','')}\n"
                        plain += BeautifulSoup(lst.get("content",""), "html.parser").get_text("\n")
                    return clean_text(plain)[:2000]

        # ── Ashby ─────────────────────────────────────────────────────────────
        elif source == "ashby" and "ashbyhq.com" in url:
            parts = job.get("job_id", "").split(":")
            if len(parts) == 3:
                slug, jid = parts[1], parts[2]
                r = requests.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{slug}/published/{jid}",
                    headers=USER_AGENT, timeout=15,
                )
                if r.ok:
                    data = r.json()
                    html = data.get("descriptionHtml", "") or data.get("description", "")
                    plain = data.get("descriptionPlain", "")
                    text = plain or clean_text(BeautifulSoup(html, "html.parser").get_text(" "))
                    return text[:2000]

        # ── Workday ───────────────────────────────────────────────────────────
        elif source == "workday" and "myworkdayjobs.com" in url:
            parsed   = urlparse(url)
            domain   = parsed.netloc
            tenant   = domain.split(".")[0]
            path     = parsed.path   # /board/job/Location/Title_ID
            parts    = path.strip("/").split("/")
            if len(parts) >= 2:
                board = parts[0]
                job_path = "/" + "/".join(parts[1:])  # /job/Location/Title_ID
                api_url  = f"https://{domain}/wday/cxs/{tenant}/{board}{job_path}"
                r = requests.get(api_url, headers={**USER_AGENT, "Accept": "application/json"}, timeout=15)
                if r.ok:
                    data = r.json()
                    desc = data.get("jobPostingInfo", {}).get("jobDescription", "")
                    if desc:
                        return clean_text(BeautifulSoup(desc, "html.parser").get_text(" "))[:2000]

        # ── Generic fallback: scrape the page ────────────────────────────────
        if url:
            r = requests.get(url, headers=USER_AGENT, timeout=20)
            if r.ok and "text/html" in r.headers.get("Content-Type", ""):
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                return clean_text(soup.get_text(" "))[:2000]

    except Exception:
        pass

    return ""
