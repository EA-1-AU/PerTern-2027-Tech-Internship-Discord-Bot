"""
Auto-tagging for DisTern: category, subcategory, term, location, salary, deadline.
"""

import re

# ── Category hierarchy ────────────────────────────────────────────────────────
# Each entry: (main_category, subcategory, [keywords])
# First match wins; keywords are checked as substrings of lowercased title+description.

CATEGORY_RULES = [
    # ── Software Engineering ───────────────────────────────────────────────
    ("💻 Software Engineering", "General Software Engineering",
     ["software engineer", "software developer", "swe intern", "full stack", "fullstack",
      "software intern", "software development intern"]),
    ("💻 Software Engineering", "Frontend Development",
     ["frontend", "front-end", "react developer", "vue.js", "angular developer",
      "javascript developer", "web developer", "ui engineer", "html/css",
      "next.js developer", "typescript developer"]),
    ("💻 Software Engineering", "Backend Development",
     ["backend", "back-end", "api developer", "server-side", "java developer",
      "python developer", "node.js developer", "golang developer", "ruby on rails",
      "rust developer", "c++ developer", "scala developer"]),
    ("💻 Software Engineering", "Mobile Development",
     ["mobile developer", "ios developer", "android developer", "swift developer",
      "kotlin developer", "react native", "flutter developer", "mobile intern"]),
    ("💻 Software Engineering", "Game Development",
     ["game developer", "game engineer", "unity developer", "unreal engine",
      "gameplay programmer", "game design intern", "game programming"]),

    # ── DevOps & Cloud ────────────────────────────────────────────────────
    ("☁️ DevOps & Cloud", "DevOps & CI/CD",
     ["devops", "devsecops", "ci/cd", "jenkins", "github actions", "platform engineer",
      "release engineer"]),
    ("☁️ DevOps & Cloud", "Cloud Engineering",
     ["cloud engineer", "aws intern", "azure intern", "gcp intern", "cloud infrastructure",
      "cloud architect", "solutions architect intern", "cloud computing intern"]),
    ("☁️ DevOps & Cloud", "Site Reliability & Infrastructure",
     ["infrastructure engineer", "kubernetes", "docker", "site reliability", " sre ",
      "systems reliability", "distributed systems", "reliability engineer"]),
    ("☁️ DevOps & Cloud", "IT & Systems Administration",
     ["it support", "it intern", "information technology", "help desk",
      "systems administrator", "network administrator", "sysadmin", "network engineer",
      "it operations"]),

    # ── Hardware & Embedded ───────────────────────────────────────────────
    ("🔧 Hardware & Embedded", "Embedded & Firmware",
     ["embedded", "firmware", "rtos", "fpga", "microcontroller", "iot engineer",
      "embedded software", "vhdl", "verilog", "embedded systems"]),
    ("🔧 Hardware & Embedded", "Hardware Engineering",
     ["hardware engineer", "hardware design", "asic", "vlsi", "circuit design",
      "pcb design", "electrical engineering intern", "analog design", "digital design"]),
    ("🔧 Hardware & Embedded", "Robotics & Automation",
     ["robotics", "automation engineer", "mechatronics", " ros ", "control systems",
      "autonomous systems", "robot software", "motion planning"]),

    # ── Data Science ──────────────────────────────────────────────────────
    ("📊 Data Science", "Data Science",
     ["data scientist", "data science intern", "research scientist", "applied scientist"]),

    # ── Data Engineering ──────────────────────────────────────────────────
    ("🔩 Data Engineering", "Data Engineering",
     ["data engineer", "data pipeline", " etl ", "apache spark", "hadoop", "airflow",
      "data infrastructure", "analytics engineer", "data platform", "dbt intern"]),

    # ── Data Analytics ────────────────────────────────────────────────────
    ("📈 Data Analytics", "Data Analytics",
     ["data analyst", "analytics intern", "business analyst", "tableau", "power bi",
      "looker", "sql analyst", "quantitative analyst", "business intelligence",
      "bi analyst", "reporting analyst"]),

    # ── AI & Machine Learning ─────────────────────────────────────────────
    ("🤖 AI & Machine Learning", "Machine Learning & AI",
     ["machine learning", "deep learning", "artificial intelligence", " ai engineer",
      "llm", "large language model", "generative ai", "ai intern", "ml intern",
      "ai researcher", "ml researcher", "foundation model"]),
    ("🤖 AI & Machine Learning", "Computer Vision",
     ["computer vision", "image recognition", "opencv", "vision engineer", "object detection",
      "perception engineer", "3d vision"]),
    ("🤖 AI & Machine Learning", "NLP & Language AI",
     ["natural language processing", "nlp intern", "text mining", "speech recognition",
      "computational linguistics", "conversational ai"]),

    # ── Cybersecurity ──────────────────────────────────────────────────────
    ("🔒 Cybersecurity", "Security Engineering",
     ["security engineer", "application security", "appsec", "product security",
      "security developer", "infosec engineer", "security software"]),
    ("🔒 Cybersecurity", "Penetration Testing",
     ["penetration test", "pen test", "ethical hacker", "red team", "offensive security",
      "vulnerability researcher"]),
    ("🔒 Cybersecurity", "SOC & Threat Intelligence",
     ["soc analyst", "threat intelligence", "threat hunting", "blue team",
      "security operations center", "detection engineer"]),
    ("🔒 Cybersecurity", "Incident Response & Forensics",
     ["incident response", "ir analyst", "digital forensics", "malware analyst",
      "cyber forensics"]),
    ("🔒 Cybersecurity", "Compliance & GRC",
     ["grc analyst", "risk management", "security audit",
      "iso 27001", "nist", "fedramp"]),
    ("🔒 Cybersecurity", "Cryptography",
     ["cryptography", "cryptographer", "encryption engineer", "zero-knowledge"]),

    # ── Blockchain & Web3 ─────────────────────────────────────────────────
    ("⛓️ Blockchain & Web3", "Blockchain Development",
     ["blockchain", "web3", "cryptocurrency", "smart contract", "solidity", "defi", "nft",
      "ethereum", "protocol engineer", "crypto intern"]),

    # ── Business & Finance ─────────────────────────────────────────────────
    ("💼 Business & Finance", "Investment Banking",
     ["investment banking", "ib analyst", "mergers and acquisitions", "m&a intern",
      "capital markets", "equity research"]),
    ("💼 Business & Finance", "Private Equity & VC",
     ["private equity", "venture capital", "vc intern", "growth equity", "pe analyst"]),
    ("💼 Business & Finance", "Consulting",
     ["management consulting", "strategy consulting", "consulting intern", "mckinsey",
      "bcg", "bain", "deloitte", "accenture"]),
    ("💼 Business & Finance", "Financial Analysis",
     ["financial analyst", "fp&a", "financial planning", "financial modeling",
      "finance intern", "corporate finance"]),
    ("💼 Business & Finance", "Accounting",
     ["accounting intern", "audit intern", "tax intern", "cpa", "accounts payable",
      "financial reporting"]),
    ("💼 Business & Finance", "Product Management",
     ["product manager", "product management", "pm intern", "product intern",
      "associate product manager", "apm"]),
    ("💼 Business & Finance", "Business Development",
     ["business development", "biz dev", "corporate development", "partnerships intern",
      "bd intern"]),
    ("💼 Business & Finance", "Sales",
     ["sales intern", "account executive", "sdr intern", "bdr intern",
      "sales development", "revenue intern"]),
    ("💼 Business & Finance", "Strategy & Operations",
     ["strategy intern", "strategic operations", "chief of staff", "biz ops",
      "business operations"]),

    # ── Creative & Design ──────────────────────────────────────────────────
    ("🎨 Creative & Design", "UI/UX Design",
     ["ux design", "ui design", "user experience", "user interface design",
      "product designer", "interaction design", "ux research"]),
    ("🎨 Creative & Design", "Graphic Design",
     ["graphic design", "graphic designer", "visual designer", "illustrator"]),
    ("🎨 Creative & Design", "Brand & Marketing Design",
     ["brand designer", "brand identity", "marketing design", "creative design",
      "art director"]),
    ("🎨 Creative & Design", "Video & Animation",
     ["video editor", "motion graphics", "3d animator", "vfx artist", "animation intern",
      "after effects"]),
    ("🎨 Creative & Design", "Architecture & Urban Design",
     ["architecture intern", "architectural design", "urban design",
      "landscape architecture", "interior design"]),
    ("🎨 Creative & Design", "Industrial & Product Design",
     ["industrial design", "product design", "cad design", "solidworks", "fusion 360"]),
    ("🎨 Creative & Design", "Fashion & Apparel",
     ["fashion design", "apparel design", "textile", "merchandising intern",
      "fashion intern"]),
    ("🎨 Creative & Design", "Content Creation",
     ["content creator", "copywriter intern", "creative writer", "content design",
      "content strategist"]),

    # ── Science & Research ─────────────────────────────────────────────────
    ("🔬 Science & Research", "Biology & Life Sciences",
     ["biology intern", "life sciences", "genetics", "genomics", "molecular biology",
      "biochemistry", "cell biology"]),
    ("🔬 Science & Research", "Chemistry",
     ["chemistry intern", "chemist", "chemical engineer", "organic chemistry",
      "analytical chemistry"]),
    ("🔬 Science & Research", "Physics",
     ["physics intern", "physicist", "quantum computing", "optics", "photonics"]),
    ("🔬 Science & Research", "Environmental Science",
     ["environmental science", "ecology", "earth science", "geology intern",
      "hydrology", "environmental engineering"]),
    ("🔬 Science & Research", "Materials Science",
     ["materials science", "materials engineer", "nanotechnology", "polymer science",
      "metallurgy"]),
    ("🔬 Science & Research", "Neuroscience",
     ["neuroscience", "neuroscientist", "cognitive science", "computational neuroscience",
      "brain research"]),
    ("🔬 Science & Research", "Space & Aerospace",
     ["astronomy", "astrophysics", "space science", "nasa", "aerospace engineer",
      "satellite", "rocket", "spacecraft"]),
    ("🔬 Science & Research", "Climate & Sustainability",
     ["climate research", "renewable energy intern", "clean energy", "sustainability",
      "carbon research", "environmental sustainability"]),

    # ── Healthcare & Medicine ──────────────────────────────────────────────
    ("🏥 Healthcare & Medicine", "Clinical Research",
     ["clinical research", "clinical trial", "clinical operations", "cra intern",
      "clinical study"]),
    ("🏥 Healthcare & Medicine", "Pharmacy & Biotech",
     ["pharmacy intern", "pharmaceutical", "biotech intern", "drug discovery",
      "pharmacology"]),
    ("🏥 Healthcare & Medicine", "Public Health",
     ["public health", "epidemiology", "global health", "health policy intern"]),
    ("🏥 Healthcare & Medicine", "Medical Devices",
     ["medical device", "medtech", "biomedical engineer", "medical equipment"]),
    ("🏥 Healthcare & Medicine", "Healthcare IT",
     ["healthcare it", "health informatics", "ehr", "health technology", "digital health"]),
    ("🏥 Healthcare & Medicine", "Nursing & Allied Health",
     ["nursing intern", "allied health", "physical therapy", "occupational therapy"]),

    # ── Law & Policy ───────────────────────────────────────────────────────
    ("⚖️ Law & Policy", "Legal Research",
     ["legal intern", "law clerk", "paralegal", "legal research", "litigation intern"]),
    ("⚖️ Law & Policy", "Public Policy",
     ["public policy", "policy analyst", "policy research intern", "think tank"]),
    ("⚖️ Law & Policy", "Compliance & Regulatory",
     ["compliance intern", "regulatory affairs", "regulatory intern", "legal compliance"]),
    ("⚖️ Law & Policy", "Intellectual Property",
     ["intellectual property", "patent intern", "trademark", "ip law"]),
    ("⚖️ Law & Policy", "Government Affairs",
     ["government affairs", "lobbying intern", "legislative affairs",
      "government relations"]),

    # ── Media & Communications ─────────────────────────────────────────────
    ("📰 Media & Communications", "Journalism & Writing",
     ["journalist intern", "editorial intern", "news writer", "staff writer intern",
      "reporting intern"]),
    ("📰 Media & Communications", "Public Relations",
     ["public relations", "pr intern", "communications intern", "media relations"]),
    ("📰 Media & Communications", "Marketing & Advertising",
     ["marketing intern", "digital marketing", "advertising intern", "growth intern",
      "paid media", "seo intern", "performance marketing"]),
    ("📰 Media & Communications", "Social Media",
     ["social media intern", "community manager", "social media marketing",
      "content marketing"]),
    ("📰 Media & Communications", "Broadcasting & Film",
     ["broadcasting", "film production", "television intern", "production assistant",
      "video production"]),
    ("📰 Media & Communications", "Podcast & Audio",
     ["podcast intern", "audio engineer", "radio intern", "sound design"]),

    # ── Government & Defense ───────────────────────────────────────────────
    ("🏛️ Government & Defense", "Intelligence & National Security",
     ["intelligence intern", "national security", "defense intelligence", "cia", "nsa"]),
    ("🏛️ Government & Defense", "Military & Defense Tech",
     ["defense contractor", "military intern", "dod", "darpa", "defense tech"]),
    ("🏛️ Government & Defense", "Civil Service",
     ["civil service", "federal government", "government intern", "state government",
      "municipal intern"]),
    ("🏛️ Government & Defense", "International Relations",
     ["international relations", "foreign affairs", "diplomacy intern",
      "united nations", "nato", "embassy intern"]),
    ("🏛️ Government & Defense", "Political Campaigns",
     ["political campaign", "campaign intern", "political intern", "elections"]),

    # ── Education & Non-profit ─────────────────────────────────────────────
    ("🎓 Education & Non-profit", "Teaching & Tutoring",
     ["teaching intern", "tutor", "instructor intern", "education intern",
      "classroom intern"]),
    ("🎓 Education & Non-profit", "Curriculum Development",
     ["curriculum development", "instructional design", "learning design", "e-learning"]),
    ("🎓 Education & Non-profit", "Social Work",
     ["social work intern", "case manager intern", "community service", "social services"]),
    ("🎓 Education & Non-profit", "Non-profit Management",
     ["non-profit intern", "nonprofit", "ngo intern", "charity intern",
      "foundation intern"]),
    ("🎓 Education & Non-profit", "EdTech",
     ["edtech", "education technology", "learning platform", "lms intern",
      "online learning"]),

    # ── Operations & HR ────────────────────────────────────────────────────
    ("⚙️ Operations & HR", "Supply Chain & Logistics",
     ["supply chain", "logistics intern", "procurement intern", "sourcing intern",
      "inventory", "warehouse intern"]),
    ("⚙️ Operations & HR", "Project Management",
     ["project management intern", "pmo", "program manager intern", "scrum master",
      "agile intern"]),
    ("⚙️ Operations & HR", "Human Resources",
     ["human resources", "hr intern", "recruiting intern", "talent acquisition",
      "people operations"]),
    ("⚙️ Operations & HR", "Real Estate",
     ["real estate intern", "property management", "commercial real estate", "cre intern"]),
    ("⚙️ Operations & HR", "Hospitality & Events",
     ["hospitality intern", "hotel intern", "event planning intern", "events intern"]),
    ("⚙️ Operations & HR", "Customer Success",
     ["customer success", "customer support intern", "customer experience", "cx intern"]),
]

# Quick lookups derived from CATEGORY_RULES
ALL_MAIN_CATEGORIES = list(dict.fromkeys(r[0] for r in CATEGORY_RULES))
SUBCATEGORIES_BY_CATEGORY: dict[str, list[str]] = {}
for _main, _sub, _ in CATEGORY_RULES:
    SUBCATEGORIES_BY_CATEGORY.setdefault(_main, []).append(_sub)

# ── Countries + cities ────────────────────────────────────────────────────────

COUNTRIES_WITH_CITIES: dict[str, list[str]] = {
    "🇺🇸 United States": [
        "New York", "San Francisco Bay Area", "Seattle", "Austin", "Boston",
        "Chicago", "Los Angeles", "Washington D.C.", "Denver", "Atlanta",
        "Miami", "San Diego", "Raleigh / Durham", "Dallas", "Remote",
    ],
    "🇬🇧 United Kingdom": [
        "London", "Manchester", "Edinburgh", "Bristol", "Cambridge",
        "Oxford", "Birmingham", "Leeds", "Remote",
    ],
    "🇨🇦 Canada": [
        "Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa",
        "Waterloo", "Edmonton", "Remote",
    ],
    "🇩🇪 Germany": [
        "Berlin", "Munich", "Hamburg", "Frankfurt", "Stuttgart",
        "Cologne", "Düsseldorf", "Dresden", "Remote",
    ],
    "🇦🇺 Australia": [
        "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
        "Canberra", "Remote",
    ],
    "🇫🇷 France": [
        "Paris", "Lyon", "Bordeaux", "Toulouse", "Marseille",
        "Grenoble", "Nice", "Remote",
    ],
    "🇸🇬 Singapore": [
        "Central Business District", "One-North", "Jurong", "Changi Business Park", "Remote",
    ],
    "🇮🇳 India": [
        "Bangalore", "Mumbai", "Delhi / NCR", "Hyderabad", "Pune",
        "Chennai", "Kolkata", "Ahmedabad", "Remote",
    ],
    "🇳🇱 Netherlands": [
        "Amsterdam", "Rotterdam", "Eindhoven", "Utrecht", "The Hague",
        "Delft", "Remote",
    ],
    "🇯🇵 Japan": [
        "Tokyo", "Osaka", "Kyoto", "Yokohama", "Nagoya", "Remote",
    ],
    "🌐 Any / Worldwide": [],
}

# ── Salary regex ──────────────────────────────────────────────────────────────

_SALARY_HOURLY_RE = re.compile(
    r'\$\s*(\d+(?:\.\d{1,2})?)\s*(?:[-–]\s*\$?\s*(\d+(?:\.\d{1,2})?))?'
    r'\s*(?:per\s*(?:hour|hr)|/\s*(?:hour|hr))',
    re.IGNORECASE,
)
_SALARY_ANNUAL_RE = re.compile(
    r'\$\s*(\d+[Kk]|\d{1,3}(?:,\d{3})+)\s*(?:[-–]\s*\$?\s*(\d+[Kk]|\d{1,3}(?:,\d{3})+))?',
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r'(?:'
    r'deadline'
    r'|apply\s+by'
    r'|application\s+deadline'
    r'|applications?\s+(?:close[sd]?|due|end|must\s+be\s+(?:submitted|received))'
    r'|closing\s+date'
    r'|close\s+date'
    r'|position\s+closes?'
    r'|posting\s+closes?'
    r'|job\s+closes?'
    r'|priority\s+deadline'
    r'|submit\s+(?:your\s+)?application\s+by'
    r'|last\s+day\s+to\s+apply'
    r'|open\s+until'
    r')[:\s]+'
    r'('
    r'[A-Za-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?'
    r'|\d{1,2}\s+[A-Za-z]+\.?(?:\s+\d{4})?'
    r'|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
    r'|\d{4}-\d{2}-\d{2}'
    r')',
    re.IGNORECASE,
)
_INTERN_WORD  = re.compile(r'\bintern(ship)?\b', re.IGNORECASE)
_YEAR_RE      = re.compile(r'20\d{2}')
_SEASON_RE    = re.compile(r'\b(summer|fall|spring|winter)\b', re.IGNORECASE)


# ── Guessing functions ────────────────────────────────────────────────────────

def guess_category(title: str, description: str = "") -> tuple[str, str | None]:
    """Return (main_category, subcategory). Falls back to ('General / Other', None)."""
    text = f"{title} {description}".lower()
    for main, sub, keywords in CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return main, sub
    return "General / Other", None


def guess_term(title: str, description: str = "", url: str = "") -> str | None:
    text = f"{title} {description} {url}".lower()
    year   = (_YEAR_RE.search(text) or object()).group(0) if _YEAR_RE.search(text) else None
    season_m = _SEASON_RE.search(text)
    season = season_m.group(1).title() if season_m else None
    if season and year:
        return f"{season} {year}"
    if season:
        return season
    if year:
        return year
    return None


def guess_salary(description: str) -> str | None:
    if not description:
        return None
    m = _SALARY_HOURLY_RE.search(description)
    if m:
        lo, hi = m.group(1), m.group(2)
        return f"${lo}–${hi}/hr" if hi else f"${lo}/hr"
    m = _SALARY_ANNUAL_RE.search(description)
    if m:
        lo, hi = m.group(1), m.group(2)
        return f"${lo}–${hi}" if hi else f"${lo}"
    return None


def guess_deadline(description: str) -> str | None:
    m = _DEADLINE_RE.search(description or "")
    return m.group(1).strip() if m else None


_DEADLINE_DATE_FMTS = [
    "%B %d, %Y", "%b %d, %Y",    # January 15, 2026 / Jan 15, 2026
    "%B %d %Y",  "%b %d %Y",     # January 15 2026
    "%B %dst, %Y", "%B %dnd, %Y", "%B %drd, %Y", "%B %dth, %Y",
    "%b %dst, %Y", "%b %dnd, %Y", "%b %drd, %Y", "%b %dth, %Y",
    "%B %d",     "%b %d",        # January 15 (no year — assumes current/next year)
    "%d %B %Y",  "%d %b %Y",     # 15 January 2026
    "%d %B",     "%d %b",        # 15 January
    "%m/%d/%Y",  "%m/%d/%y",     # 01/15/2026 / 01/15/26
    "%m-%d-%Y",  "%m-%d-%y",
    "%Y-%m-%d",                  # 2026-01-15
]


def parse_deadline_date(deadline_str: str) -> "datetime.date | None":
    """Try to parse a deadline string into a date object. Returns None if unparseable."""
    import datetime as _dt
    s = deadline_str.strip()
    # strip ordinal suffixes before trying formats without them
    cleaned = re.sub(r'(\d+)(?:st|nd|rd|th)', r'\1', s, flags=re.IGNORECASE)
    for text in (s, cleaned):
        for fmt in _DEADLINE_DATE_FMTS:
            try:
                d = _dt.datetime.strptime(text, fmt).date()
                # If no year in format, assign current or next year
                if "%Y" not in fmt and "%y" not in fmt:
                    today = _dt.date.today()
                    d = d.replace(year=today.year)
                    if d < today:
                        d = d.replace(year=today.year + 1)
                return d
            except ValueError:
                continue
    return None


def is_probably_real_internship(title: str) -> bool:
    return bool(_INTERN_WORD.search(title or ""))


def tag_job(job: dict) -> dict:
    title       = job.get("title", "")
    description = job.get("description", "")
    url         = job.get("url", "")
    main_cat, sub_cat = guess_category(title, description)
    job["category"]    = main_cat
    job["subcategory"] = sub_cat
    job["term"]        = guess_term(title, description, url)
    job["salary"]      = guess_salary(description)
    job["deadline"]    = guess_deadline(description)
    return job
