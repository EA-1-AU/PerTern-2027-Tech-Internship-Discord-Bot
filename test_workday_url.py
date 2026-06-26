"""Run this on the Pi to see raw externalPath values from Workday API."""
import requests
from urllib.parse import urlparse

USER_AGENT = {"User-Agent": "Mozilla/5.0 (compatible; PerTern/1.0)"}

companies = [
    {"name": "Intel",   "url": "https://intel.wd1.myworkdayjobs.com/External"},
    {"name": "Leidos",  "url": "https://leidos.wd5.myworkdayjobs.com/External"},
    {"name": "Comcast", "url": "https://comcast.wd5.myworkdayjobs.com/Comcast_Careers"},
]

for company in companies:
    parsed = urlparse(company["url"])
    domain = parsed.netloc
    tenant = domain.split(".")[0]
    board  = parsed.path.strip("/")
    api_url = f"https://{domain}/wday/cxs/{tenant}/{board}/jobs"
    try:
        r = requests.post(
            api_url,
            json={"limit": 3, "offset": 0, "searchText": "intern", "appliedFacets": {}},
            headers={**USER_AGENT, "Content-Type": "application/json"},
            timeout=15,
        )
        data = r.json()
        postings = data.get("jobPostings", [])[:2]
        print(f"\n=== {company['name']} ===")
        for p in postings:
            print(f"  title:        {p.get('title')}")
            print(f"  externalPath: {p.get('externalPath')}")
            print(f"  full URL:     https://{domain}{p.get('externalPath','')}")
    except Exception as e:
        print(f"{company['name']}: ERROR {e}")
