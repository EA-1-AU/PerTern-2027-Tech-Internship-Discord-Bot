"""
PerTern — Personal Internship Bot
Scrapes 310+ companies and DMs matching internships directly to you.

.env variables:
  DISCORD_TOKEN            — your bot token
  MY_DISCORD_USER_ID       — your Discord user ID
  SCAN_INTERVAL_MINUTES    — how often to scan (default 10)
  DIGEST_HOUR_UTC          — hour (UTC) for daily digest DM (default 13 = 8am ET)
  REQUIRE_SALARY           — set to "true" to only show roles that list a salary
"""

import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
from datetime import timezone

import discord
from discord.ext import tasks
from dotenv import load_dotenv

import db
from scraper import run_all_scrapers
from scraper.ats import fetch_job_description
from tagging import tag_job

load_dotenv()

_LOG_PATH = os.path.join(os.path.dirname(__file__), "pertern.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("pertern")

TOKEN          = os.getenv("DISCORD_TOKEN", "")
MY_USER_ID     = int(os.getenv("MY_DISCORD_USER_ID", "0"))
SCAN_INTERVAL  = int(os.getenv("SCAN_INTERVAL_MINUTES", "10"))
DIGEST_HOUR    = int(os.getenv("DIGEST_HOUR_UTC", "13"))
REQUIRE_SALARY  = os.getenv("REQUIRE_SALARY", "false").lower() == "true"
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
_RESUME_PATH    = os.path.join(os.path.dirname(__file__), "resume.txt")

# ── Personal filter ───────────────────────────────────────────────────────────
MY_CATEGORIES = {
    "🔒 Cybersecurity",
    "☁️ DevOps & Cloud",
    "📈 Data Analytics",
    "📊 Data Science",
}

MY_TITLE_KEYWORDS = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "network security", "security analyst", "security engineer",
    "security operations", "soc analyst", "incident response",
    "vulnerability", "penetration", "pen test", "risk analyst",
    "compliance analyst", "grc", "identity", "iam",
    "cloud security", "cloud engineer", "cloud analyst", "cloud operations",
    "gcp", "google cloud", "cloud infrastructure",
    "data analyst", "data analytics", "business intelligence",
    "power bi", "looker", "reporting analyst", "operations analyst",
    "bi analyst", "bi developer",
    "it support", "systems administrator", "system administrator",
    "network administrator", "help desk", "technical analyst",
    "it analyst", "systems analyst",
    "python developer", "python engineer", "sql analyst",
]

FORTUNE_500_WATCHLIST = {
    "apple", "microsoft", "google", "alphabet", "amazon", "meta", "nvidia",
    "intel", "ibm", "oracle", "salesforce", "adobe", "cisco", "qualcomm",
    "texas instruments", "broadcom", "hp", "dell", "hewlett packard",
    "accenture", "cognizant",
    "crowdstrike", "palo alto networks", "fortinet", "sentinelone",
    "cyberark", "tenable", "rapid7", "splunk", "darktrace", "zscaler",
    "cloudflare", "okta", "sailpoint",
    "jpmorgan", "jp morgan", "bank of america", "wells fargo", "citigroup",
    "citibank", "goldman sachs", "morgan stanley", "american express",
    "visa", "mastercard", "capital one", "charles schwab", "fidelity",
    "blackrock", "deloitte", "pwc", "kpmg", "ernst & young", "ey",
    "lockheed martin", "boeing", "raytheon", "northrop grumman",
    "general dynamics", "l3harris", "leidos", "booz allen", "saic",
    "mantech", "peraton",
    "at&t", "verizon", "t-mobile", "comcast",
    "walmart", "target", "home depot", "lowe's", "lowes", "costco",
    "fedex", "ups",
    "unitedhealth", "cvs health", "anthem", "humana", "cigna",
    "johnson & johnson", "pfizer", "abbvie",
    "procter & gamble", "general electric", "honeywell", "3m",
    "exxon", "chevron", "general motors", "ford",
    "pepsico", "coca-cola",
}

MY_COMPANY_WATCHLIST = {
    "crowdstrike", "palo alto networks", "sentinelone", "wiz", "snyk",
    "darktrace", "zscaler", "cloudflare", "okta", "cyberark", "tenable",
    "rapid7", "splunk", "recorded future", "varonis", "secureworks",
    "arctic wolf", "check point", "trend micro", "sailpoint", "trellix",
    "google", "alphabet", "microsoft", "amazon",
    "deloitte", "pwc", "kpmg", "ernst & young", "ey",
    "booz allen", "leidos", "saic", "mantech", "peraton", "caci",
    "new relic", "dynatrace", "grafana labs", "hashicorp",
    "alteryx", "domo", "thoughtspot", "microstrategy", "qlik",
    "guidehouse",
}

_US_INDICATORS = [
    "united states", "u.s.", "u.s.a", "usa", " us ",
    "remote", "nationwide", "hybrid",
    "alabama","alaska","arizona","arkansas","california","colorado",
    "connecticut","delaware","florida","georgia","hawaii","idaho",
    "illinois","indiana","iowa","kansas","kentucky","louisiana",
    "maine","maryland","massachusetts","michigan","minnesota",
    "mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania",
    "rhode island","south carolina","south dakota","tennessee","texas",
    "utah","vermont","virginia","washington","west virginia",
    "wisconsin","wyoming",
    " al "," ak "," az "," ar "," ca "," co "," ct "," de ",
    " fl "," ga "," hi "," id "," il "," in "," ia "," ks ",
    " ky "," la "," me "," md "," ma "," mi "," mn "," ms ",
    " mo "," mt "," ne "," nv "," nh "," nj "," nm "," ny ",
    " nc "," nd "," oh "," ok "," or "," pa "," ri "," sc ",
    " sd "," tn "," tx "," ut "," vt "," va "," wa "," wv ",
    " wi "," wy ",
]

# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.dm_messages = True
client = discord.Client(intents=intents)
tree   = discord.app_commands.CommandTree(client)

_seen_job_ids: set[str] = set()
_seen_title_keys: set[str] = set()  # dedupe by company+normalized-title


def _title_key(company: str, title: str) -> str:
    """Normalize company+title for duplicate detection."""
    t = re.sub(r'[^a-z0-9]', '', title.lower())
    c = re.sub(r'[^a-z0-9]', '', company.lower())
    return f"{c}:{t}"

# Persistent summary message ID (saved to DB so it survives restarts)
_SUMMARY_MSG_KEY = "pertern_summary_msg_id"

# Current browse session (one at a time — personal bot)
_browse: dict = {
    "jobs":     [],    # list of job dicts in current session
    "index":    0,     # which job is showing
    "category": None,  # category filter active
}


# ── DB helpers (direct SQL for unreviewed job queries) ────────────────────────

def _db_unreviewed_by_category() -> dict[str, int]:
    """Return {category: unreviewed_count} for the summary."""
    uid = str(MY_USER_ID)
    with sqlite3.connect(str(db.DB_PATH)) as conn:
        rows = conn.execute("""
            SELECT j.category, COUNT(*) FROM jobs j
            LEFT JOIN user_jobs uj
                ON j.job_id = uj.job_id AND uj.user_id = ?
            WHERE (uj.status IS NULL OR uj.status NOT IN ('applied','skipped','snoozed','interview','offer'))
            AND j.category IS NOT NULL AND j.category != ''
            GROUP BY j.category
            ORDER BY COUNT(*) DESC
        """, (uid,)).fetchall()
    return {r[0]: r[1] for r in rows}


def _db_unreviewed_jobs(category: str | None = None) -> list[dict]:
    """Return all unreviewed jobs, optionally filtered to one category."""
    uid = str(MY_USER_ID)
    with sqlite3.connect(str(db.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        if category:
            rows = conn.execute("""
                SELECT j.*, COALESCE(c.priority, 0) as co_priority FROM jobs j
                LEFT JOIN user_jobs uj ON j.job_id = uj.job_id AND uj.user_id = ?
                LEFT JOIN companies c ON j.company = c.name
                WHERE (uj.status IS NULL OR uj.status NOT IN ('applied','skipped','snoozed','interview','offer'))
                AND j.category = ?
                ORDER BY co_priority DESC, j.first_seen DESC
            """, (uid, category)).fetchall()
        else:
            rows = conn.execute("""
                SELECT j.*, COALESCE(c.priority, 0) as co_priority FROM jobs j
                LEFT JOIN user_jobs uj ON j.job_id = uj.job_id AND uj.user_id = ?
                LEFT JOIN companies c ON j.company = c.name
                WHERE (uj.status IS NULL OR uj.status NOT IN ('applied','skipped','snoozed','interview','offer'))
                ORDER BY co_priority DESC, j.first_seen DESC
            """, (uid,)).fetchall()
    return [dict(r) for r in rows]


_FORTUNE_100 = {
    "Walmart", "Amazon", "Apple", "UnitedHealth Group", "CVS Health",
    "JPMorgan Chase", "ExxonMobil", "Google", "Cigna", "AT&T",
    "Ford", "Elevance Health", "Microsoft", "Home Depot", "Comcast",
    "General Motors", "Humana", "Pfizer", "Lowe's", "Target",
    "Johnson & Johnson", "MetLife", "Wells Fargo", "Boeing", "Verizon",
    "Procter & Gamble", "Delta Air Lines", "Goldman Sachs", "Raytheon",
    "Lockheed Martin", "Cisco", "IBM", "Best Buy", "Disney",
    "Warner Bros Discovery", "Northrop Grumman", "Bank of America",
    "Prudential", "Intel", "Caterpillar", "Thermo Fisher",
    "Bristol-Myers Squibb", "Nationwide", "Merck", "UPS", "Broadcom",
    "Charter Communications", "Morgan Stanley", "Allstate", "Abbott",
    "Liberty Mutual", "John Deere", "Accenture", "HPE", "Qualcomm",
    "PayPal", "Travelers", "Dell Technologies", "Dell", "Southwest Airlines",
    "Eli Lilly", "Honeywell", "Coca-Cola", "General Dynamics",
    "General Dynamics Mission Systems", "General Dynamics IT",
    "Salesforce", "Deloitte", "KPMG", "EY", "PwC",
    "American Express", "Charles Schwab", "BlackRock", "State Street",
    "Mastercard", "Visa", "T-Mobile", "3M", "Eaton", "Parker Hannifin",
    "Cummins", "Medtronic", "Stryker", "Boston Scientific",
    "L3Harris", "BAE Systems", "Leidos", "Booz Allen Hamilton",
    "SAIC", "Textron", "S&P Global", "Marsh McLennan", "Aon",
    "Travelers", "FIS", "Fiserv", "UPS", "Lumen Technologies",
}


def _db_fortune100_jobs() -> list[dict]:
    """Return unreviewed jobs from Fortune 100 companies."""
    uid  = str(MY_USER_ID)
    names = list(_FORTUNE_100)
    placeholders = ",".join("?" * len(names))
    with sqlite3.connect(str(db.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"""
            SELECT j.*, COALESCE(c.priority, 0) as co_priority FROM jobs j
            LEFT JOIN user_jobs uj ON j.job_id = uj.job_id AND uj.user_id = ?
            LEFT JOIN companies c ON j.company = c.name
            WHERE (uj.status IS NULL OR uj.status NOT IN ('applied','skipped','snoozed','interview','offer'))
            AND j.company IN ({placeholders})
            ORDER BY co_priority DESC, j.first_seen DESC
        """, [uid] + names).fetchall()
    return [dict(r) for r in rows]


def _db_total_unreviewed() -> int:
    uid = str(MY_USER_ID)
    with sqlite3.connect(str(db.DB_PATH)) as conn:
        row = conn.execute("""
            SELECT COUNT(*) FROM jobs j
            LEFT JOIN user_jobs uj
                ON j.job_id = uj.job_id AND uj.user_id = ?
            WHERE (uj.status IS NULL OR uj.status NOT IN ('applied','skipped','snoozed','interview','offer'))
        """, (uid,)).fetchone()
    return row[0] if row else 0


# ── Filter logic ──────────────────────────────────────────────────────────────

def _is_us_location(location: str) -> bool:
    if not location or location.strip() == "":
        return True
    loc = f" {location.lower()} "
    # Accept remote anywhere + any US location; reject everything else
    if any(w in loc for w in ("remote", "anywhere", "nationwide", "hybrid", "virtual")):
        return True
    return any(ind in loc for ind in _US_INDICATORS)


def _matches_me(job: dict) -> tuple[bool, str]:
    title    = job.get("title", "").lower()
    cat      = job.get("category", "") or ""
    company  = job.get("company", "").lower()
    location = job.get("location", "") or ""
    salary   = job.get("salary", "") or ""

    if not _is_us_location(location):
        return False, ""
    if REQUIRE_SALARY and not salary:
        return False, ""

    if any(w in company for w in MY_COMPANY_WATCHLIST):
        return True, f"Watchlist: {job.get('company','')}"
    if any(f in company for f in FORTUNE_500_WATCHLIST):
        return True, f"Fortune 500: {job.get('company','')}"
    if cat in MY_CATEGORIES:
        return True, f"Category: {cat}"
    for kw in MY_TITLE_KEYWORDS:
        if kw in title:
            return True, f"Keyword: {kw}"

    return False, ""


_SKILLBRIDGE_RE = re.compile(r'skill\s*bridge', re.IGNORECASE)

_TITLE_BLACKLIST_RE = re.compile(
    r'\b(pharmac(y|ist|eutical|ology)|dispensing|compounding|'
    r'dental|dentist|optometr|ophthalmolog|veterinar|'
    r'nursing|nurse|clinical\s+trial|radiology|radiograph|'
    r'medical\s+assistant|phlebotom|surgical|anesthes|'
    r'ph\.?d|doctoral|postdoc)\b',
    re.IGNORECASE,
)

def _is_internship(title: str) -> bool:
    if _SKILLBRIDGE_RE.search(title):
        return False
    if _TITLE_BLACKLIST_RE.search(title):
        return False
    if re.search(r'\bintern(ship)?\b', title, re.IGNORECASE):
        return True
    # Co-op positions are internship-equivalent
    if re.search(r'\bco[\-\s]?op\b', title, re.IGNORECASE):
        return True
    # Finance/banking "Summer/Winter/Spring/Fall Analyst/Associate" programs
    if re.search(r'\b(summer|winter|spring|fall)\s+(analyst|associate|engineer|developer)\b', title, re.IGNORECASE):
        return True
    # "Extern", "apprentice", "trainee" programs
    if re.search(r'\b(extern(ship)?|apprentice(ship)?|trainee)\b', title, re.IGNORECASE):
        return True
    return False


def _2027_filter(job: dict) -> bool:
    """Only allow jobs that are explicitly 2027 or undated non-Simplify sources."""
    raw = f"{job.get('title','')} {job.get('description','')}".lower()
    if "2026" in raw:
        return False
    term = job.get("term") or ""
    yr   = re.search(r'(20\d{2})', term)
    if yr:
        return yr.group(1) == "2027"
    # Simplify repos are named "Summer2026" — undated Simplify = 2026 by default
    if job.get("source", "").lower() == "simplify":
        return False
    return True


# ── Embeds ────────────────────────────────────────────────────────────────────

def _make_job_embed(job: dict, reason: str = "", index: int = 0, total: int = 0, status: str = "") -> discord.Embed:
    title    = job.get("title", "No Title")
    company  = job.get("company", "Unknown")
    location = job.get("location", "")
    url      = job.get("url", "")
    term     = job.get("term", "")
    salary   = job.get("salary", "")
    cat      = job.get("category", "")
    deadline = job.get("deadline", "")

    status_prefix = {"applied": "✅ ", "skipped": "⏭️ "}.get(status, "")

    # Deadline urgency
    deadline_badge = ""
    if deadline and not status:
        from tagging import parse_deadline_date
        import datetime as _dt
        dl_date = parse_deadline_date(deadline)
        if dl_date:
            days_left = (dl_date - _dt.date.today()).days
            if days_left <= 3:
                color = discord.Color.red()
                deadline_badge = "🚨 "
            elif days_left <= 7:
                color = discord.Color.orange()
                deadline_badge = "⚠️ "
            else:
                color = discord.Color.from_rgb(88, 101, 242)
        else:
            color = discord.Color.from_rgb(88, 101, 242)
    else:
        color = {"applied": discord.Color.green(), "skipped": discord.Color.dark_gray()}.get(
            status, discord.Color.from_rgb(88, 101, 242)
        )

    em = discord.Embed(
        title=f"{deadline_badge}{status_prefix}{title}",
        url=url or None,
        color=color,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.set_author(name=company)

    if location: em.add_field(name="📍 Location", value=location,  inline=True)
    if term:     em.add_field(name="📅 Term",     value=term,       inline=True)
    if salary:   em.add_field(name="💰 Salary",   value=salary,     inline=True)
    if cat:      em.add_field(name="🏷️ Category", value=cat,        inline=True)
    if deadline:
        dl_display = deadline
        try:
            from tagging import parse_deadline_date
            import datetime as _dt
            dl_date = parse_deadline_date(deadline)
            if dl_date:
                days_left = (dl_date - _dt.date.today()).days
                if days_left < 0:
                    dl_display = f"{deadline} (closed)"
                elif days_left == 0:
                    dl_display = f"{deadline} (TODAY!)"
                elif days_left <= 7:
                    dl_display = f"{deadline} ({days_left}d left)"
        except Exception:
            pass
        em.add_field(name="⏰ Deadline", value=dl_display, inline=True)
    if reason:   em.add_field(name="🎯 Why sent", value=reason,     inline=False)
    if url:      em.add_field(name="🔗 Apply",    value=f"[Open listing]({url})", inline=False)
    if status:   em.add_field(name="📝 Status",   value=f"{status_prefix}{status.title()}", inline=False)

    counter = f"{index + 1}/{total} · " if total else ""
    em.set_footer(text=f"PerTern · {counter}ID: {job.get('job_id','')}")
    return em


def _make_summary_embed(cats: dict[str, int], new_count: int = 0) -> discord.Embed:
    total = sum(cats.values())
    lines = [f"{cat} — **{n}** unreviewed" for cat, n in cats.items()]
    if not lines:
        desc = "Nothing unreviewed right now. Check back after the next scan!"
    else:
        desc = "\n".join(lines)
        if new_count:
            desc = f"**+{new_count} new this scan**\n\n" + desc
        desc += f"\n\n**{total} total unreviewed** — use the dropdown below to browse."

    em = discord.Embed(
        title="📋 PerTern — Internship Summary",
        description=desc,
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.set_footer(text=f"PerTern · {db.get_job_count():,} total indexed · Scans every {SCAN_INTERVAL}min")
    return em


# ── Modals ───────────────────────────────────────────────────────────────────

class ApplyNoteModal(discord.ui.Modal, title="Application Note (optional)"):
    note = discord.ui.TextInput(
        label="Note",
        placeholder="Recruiter name, referral, cover letter needed, etc.",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, job: dict):
        super().__init__()
        self.job = job

    async def on_submit(self, interaction: discord.Interaction):
        jid = self.job.get("job_id", "")
        uid = str(MY_USER_ID)
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, "applied")
        if self.note.value.strip():
            db.add_user_note(uid, jid, self.note.value.strip())
        await _advance_after_mark(interaction, "applied")


class SnoozeModal(discord.ui.Modal, title="Snooze this job"):
    days = discord.ui.TextInput(
        label="Snooze for how many days?",
        placeholder="3",
        required=True,
        max_length=3,
    )

    def __init__(self, job: dict):
        super().__init__()
        self.job = job

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = max(1, min(30, int(self.days.value.strip())))
        except ValueError:
            n = 3
        jid      = self.job.get("job_id", "")
        uid      = str(MY_USER_ID)
        wake_at  = (datetime.datetime.now(timezone.utc) + datetime.timedelta(days=n)).isoformat()
        db.add_reminder(uid, jid, wake_at, message="snooze")
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, "snoozed")
        await _advance_after_mark(interaction, "snoozed")


# ── Browse helpers ────────────────────────────────────────────────────────────

_REVIEWED = {"applied", "skipped", "snoozed", "interview", "offer", "rejected"}


async def _advance_after_mark(interaction: discord.Interaction, marked_status: str):
    """After marking a job, advance to the next unreviewed one."""
    uid  = str(MY_USER_ID)
    jobs = _browse["jobs"]
    idx  = _browse["index"]

    next_idx = idx + 1
    while next_idx < len(jobs):
        j  = jobs[next_idx]
        uj = db.get_user_job(uid, j.get("job_id", ""))
        if (uj or {}).get("status", "") not in _REVIEWED:
            break
        next_idx += 1

    if next_idx >= len(jobs):
        em = discord.Embed(
            title="✅ All done!",
            description="You've reviewed all jobs in this category.\nCheck back after the next scan for new ones.\n\n*This message will disappear in 1 minute.*",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=em, view=None)
        msg = await interaction.original_response()
        await _update_summary()
        await asyncio.sleep(60)
        try:
            await msg.delete()
        except Exception:
            pass
    else:
        _browse["index"] = next_idx
        job    = jobs[next_idx]
        new_uj = db.get_user_job(uid, job.get("job_id", ""))
        new_st = (new_uj or {}).get("status", "")
        em     = _make_job_embed(job, index=next_idx, total=len(jobs), status=new_st)
        await interaction.response.edit_message(embed=em, view=BrowseView(job, message=interaction.message))
        asyncio.create_task(_update_summary())


# ── Browse UI ─────────────────────────────────────────────────────────────────

class BrowseView(discord.ui.View):
    """
    Row 0: ◀ Prev | ✅ Applied | ▶ Next
    Row 1: ⏭️ Skip | 🤖 Match | ••• More
    Auto-deletes after 3 minutes of inactivity.
    """

    def __init__(self, job: dict, message: discord.Message | None = None):
        super().__init__(timeout=180)
        self.job     = job
        self.message = message

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except discord.NotFound:
                pass

    async def _go(self, interaction: discord.Interaction, new_index: int):
        jobs = _browse["jobs"]
        new_index = max(0, min(len(jobs) - 1, new_index))
        _browse["index"] = new_index
        job    = jobs[new_index]
        uid    = str(MY_USER_ID)
        uj     = db.get_user_job(uid, job.get("job_id", ""))
        status = (uj or {}).get("status", "")
        em     = _make_job_embed(job, index=new_index, total=len(jobs), status=status)
        view   = BrowseView(job, message=self.message)
        await interaction.response.edit_message(embed=em, view=view)

    async def _mark_direct(self, interaction: discord.Interaction, status: str):
        jid = self.job.get("job_id", "")
        uid = str(MY_USER_ID)
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, status)
        await _advance_after_mark(interaction, status)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, _browse["index"] - 1)

    @discord.ui.button(label="✅ Applied", style=discord.ButtonStyle.success, row=0)
    async def applied_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyNoteModal(self.job))

    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, _browse["index"] + 1)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.danger, row=1)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "skipped")

    @discord.ui.button(label="🤖 Match", style=discord.ButtonStyle.primary, row=1)
    async def match_btn_browse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        loop = asyncio.get_event_loop()
        job  = self.job
        desc = await loop.run_in_executor(None, lambda: fetch_job_description(job))
        if not desc:
            desc = job.get("description", "")
        try:
            result, footer = await loop.run_in_executor(None, lambda: _claude_match(job, desc))
        except Exception as e:
            await interaction.followup.send(f"❌ Claude API error: `{e}`", ephemeral=True)
            return
        color = discord.Color.green() if "YES" in result else discord.Color.red()
        em = discord.Embed(
            title=f"🤖 AI Match — {job.get('title','')}",
            description=result,
            color=color,
            url=job.get("url") or None,
        )
        em.set_footer(text=footer)
        await interaction.followup.send(embed=em, ephemeral=True)

    @discord.ui.button(label="••• More", style=discord.ButtonStyle.secondary, row=1)
    async def more_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid    = str(MY_USER_ID)
        uj     = db.get_user_job(uid, self.job.get("job_id", ""))
        status = (uj or {}).get("status", "")
        em     = _make_job_embed(self.job, index=_browse["index"], total=len(_browse["jobs"]), status=status)
        await interaction.response.edit_message(embed=em, view=MoreView(self.job, message=self.message))



class MoreView(discord.ui.View):
    """
    Row 0: 🗣️ Interview | 🎉 Offer | ❌ Rejected | 💤 Snooze | ← Back
    Row 1: 🔗 Copy Link | ⭐ Priority | 📄 Details
    Auto-deletes after 3 minutes of inactivity (shared with BrowseView).
    """

    def __init__(self, job: dict, message: discord.Message | None = None):
        super().__init__(timeout=180)
        self.job     = job
        self.message = message

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except discord.NotFound:
                pass

    async def _mark_direct(self, interaction: discord.Interaction, status: str):
        jid = self.job.get("job_id", "")
        uid = str(MY_USER_ID)
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, status)
        await _advance_after_mark(interaction, status)

    @discord.ui.button(label="🗣️ Interview", style=discord.ButtonStyle.primary, row=0)
    async def interview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "interview")

    @discord.ui.button(label="🎉 Offer", style=discord.ButtonStyle.primary, row=0)
    async def offer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "offer")

    @discord.ui.button(label="❌ Rejected", style=discord.ButtonStyle.danger, row=0)
    async def rejected_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "rejected")

    @discord.ui.button(label="💤 Snooze", style=discord.ButtonStyle.secondary, row=0)
    async def snooze_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SnoozeModal(self.job))

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid    = str(MY_USER_ID)
        uj     = db.get_user_job(uid, self.job.get("job_id", ""))
        status = (uj or {}).get("status", "")
        em     = _make_job_embed(self.job, index=_browse["index"], total=len(_browse["jobs"]), status=status)
        await interaction.response.edit_message(embed=em, view=BrowseView(self.job, message=self.message))

    @discord.ui.button(label="🔗 Copy Link", style=discord.ButtonStyle.secondary, row=1)
    async def link_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = self.job.get("url", "")
        if url:
            await interaction.response.send_message(f"🔗 **Apply link** (tap to open or hold to copy):\n{url}", ephemeral=True)
        else:
            await interaction.response.send_message("No URL available for this listing.", ephemeral=True)

    @discord.ui.button(label="⭐ Priority", style=discord.ButtonStyle.secondary, row=1)
    async def priority_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        company = self.job.get("company", "")
        new_val = db.toggle_company_priority(company)
        label = "on" if new_val else "off"
        await interaction.response.send_message(
            f"⭐ **{company}** priority **{label}** — new jobs from this company will {'appear first' if new_val else 'sort normally'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="📄 Details", style=discord.ButtonStyle.secondary, row=1)
    async def details_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_event_loop()
        job  = self.job
        desc = await loop.run_in_executor(None, lambda: fetch_job_description(job))
        if not desc:
            desc = job.get("description", "")
        if not desc:
            await interaction.followup.send("No description available for this listing.", ephemeral=True)
            return
        em = discord.Embed(
            title=f"📄 {job.get('title','')} — {job.get('company','')}",
            description=desc[:4000],
            color=discord.Color.from_rgb(88, 101, 242),
            url=job.get("url") or None,
        )
        await interaction.followup.send(embed=em, ephemeral=True)

    @discord.ui.button(label="🤖 Match", style=discord.ButtonStyle.secondary, row=1)
    async def match_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        loop = asyncio.get_event_loop()
        job  = self.job

        # fetch description first
        desc = await loop.run_in_executor(None, lambda: fetch_job_description(job))
        if not desc:
            desc = job.get("description", "")

        try:
            result, footer = await loop.run_in_executor(None, lambda: _claude_match(job, desc))
        except Exception as e:
            await interaction.followup.send(
                f"❌ Claude API error: `{e}`",
                ephemeral=True,
            )
            return

        color = discord.Color.green() if "YES" in result else discord.Color.red()
        em = discord.Embed(
            title=f"🤖 AI Match — {job.get('title','')}",
            description=result,
            color=color,
            url=job.get("url") or None,
        )
        em.set_footer(text=footer)
        await interaction.followup.send(embed=em, ephemeral=True)


# ── Category select dropdown ──────────────────────────────────────────────────

class CategorySelect(discord.ui.Select):
    def __init__(self, cats: dict[str, int]):
        total = sum(cats.values())
        options = [
            discord.SelectOption(
                label="All Categories",
                value="__all__",
                description=f"{total} unreviewed internships",
                emoji="📋",
            )
        ]
        for cat, count in list(cats.items())[:24]:
            options.append(discord.SelectOption(
                label=cat[:100],
                value=cat,
                description=f"{count} unreviewed",
            ))
        super().__init__(
            placeholder="Choose a category to browse...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        category = None if self.values[0] == "__all__" else self.values[0]
        jobs = _db_unreviewed_jobs(category)
        if not jobs:
            await interaction.response.send_message(
                "No unreviewed jobs in that category right now!", ephemeral=True
            )
            return
        _browse["jobs"]     = jobs
        _browse["index"]    = 0
        _browse["category"] = category

        uid    = str(MY_USER_ID)
        job    = jobs[0]
        uj     = db.get_user_job(uid, job.get("job_id",""))
        status = (uj or {}).get("status","")
        cat_label = category or "All Categories"
        em = _make_job_embed(job, index=0, total=len(jobs), status=status)
        em.description = f"Browsing: **{cat_label}** — {len(jobs)} jobs\nUse ◀ ▶ to navigate · Applied/Skip to mark"

        view = BrowseView(job)
        await interaction.response.send_message(embed=em, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class SummaryView(discord.ui.View):
    def __init__(self, cats: dict[str, int]):
        super().__init__(timeout=None)
        if cats:
            self.add_item(CategorySelect(cats))


# ── Summary message (persistent, edited each scan) ───────────────────────────

async def _update_summary(new_count: int = 0):
    """Create or edit the one persistent summary DM message."""
    cats = _db_unreviewed_by_category()
    em   = _make_summary_embed(cats, new_count)
    view = SummaryView(cats)

    stored_id = db.get_bot_state(_SUMMARY_MSG_KEY)
    dm = await _get_dm()

    if stored_id:
        try:
            msg = await dm.fetch_message(int(stored_id))
            await msg.edit(embed=em, view=view)
            return
        except discord.NotFound:
            pass
        except Exception as e:
            log.warning("Summary edit failed: %s", e)

    # Create new summary message
    msg = await dm.send(embed=em, view=view)
    db.set_bot_state(_SUMMARY_MSG_KEY, str(msg.id))


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _delete_after(msg: discord.Message, delay: float):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def _get_dm() -> discord.DMChannel:
    user = await client.fetch_user(MY_USER_ID)
    return await user.create_dm()


async def _run_scan(label: str = "") -> int:
    log.info("Scan starting%s...", f" ({label})" if label else "")
    loop     = asyncio.get_event_loop()
    new_jobs: list[dict] = []

    def _on_batch(company: str, raw_jobs: list[dict]):
        for job in raw_jobs:
            if not _is_internship(job.get("title", "")):
                continue
            if not _2027_filter(job):
                continue
            tag_job(job)
            match, reason = _matches_me(job)
            if not match:
                continue
            jid = job.get("job_id", "")
            if jid in _seen_job_ids:
                continue
            if db.job_exists(jid):
                _seen_job_ids.add(jid)
                continue
            # Dedupe by company+title (catches same role across multiple ATS sources)
            tkey = _title_key(job.get("company",""), job.get("title",""))
            if tkey in _seen_title_keys:
                continue
            _seen_title_keys.add(tkey)
            _seen_job_ids.add(jid)
            db.insert_job(
                jid,
                job.get("company", ""), job.get("source", ""),
                job.get("title", ""),   job.get("location", ""),
                job.get("url", ""),
                description=job.get("description", ""),
                category=job.get("category"),
                subcategory=job.get("subcategory"),
                term=job.get("term"),
                deadline=job.get("deadline"),
                salary=job.get("salary"),
            )
            new_jobs.append(job)

    await loop.run_in_executor(None, lambda: run_all_scrapers(on_batch=_on_batch))

    count = len(new_jobs)
    log.info("Scan done — %d new matches", count)

    # Record scan time for /status
    now_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db.set_bot_state("last_scan_time", now_str)
    db.set_bot_state("last_scan_new", str(count))

    # Always update the summary (edit new count in, or just refresh totals)
    try:
        await _update_summary(new_count=count)
    except Exception as e:
        log.warning("Summary update failed: %s", e)

    # Ping notification for new matches (auto-deletes after 60s)
    if count:
        try:
            dm  = await _get_dm()
            msg = await dm.send(f"📬 **+{count} new internship{'s' if count != 1 else ''}** found — check your summary above!")
            await asyncio.sleep(60)
            await msg.delete()
        except Exception as e:
            log.warning("Ping notification error: %s", e)

    # Check for upcoming deadlines
    await _check_deadlines()

    return count


# ── Deadline reminders ────────────────────────────────────────────────────────

async def _check_deadlines():
    try:
        uid  = str(MY_USER_ID)
        jobs = db.get_user_jobs_with_deadlines(uid, days=3)
        now  = datetime.datetime.now(timezone.utc)
        for job in jobs:
            deadline_str = job.get("deadline", "")
            if not deadline_str:
                continue
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
                try:
                    dl        = datetime.datetime.strptime(deadline_str.strip(), fmt).replace(tzinfo=timezone.utc)
                    days_left = (dl - now).days
                    if 0 <= days_left <= 3:
                        state_key = f"reminded_{job.get('job_id','')}"
                        if not db.get_bot_state(state_key):
                            db.set_bot_state(state_key, "1")
                            em = discord.Embed(
                                title=f"⏰ Deadline in {days_left} day{'s' if days_left != 1 else ''}!",
                                description=(
                                    f"**{job.get('title')}** at **{job.get('company')}**\n"
                                    f"Deadline: **{deadline_str}**"
                                ),
                                color=discord.Color.red(),
                                url=job.get("url") or None,
                            )
                            dm = await _get_dm()
                            await dm.send(embed=em)
                    break
                except ValueError:
                    continue
    except Exception as e:
        log.warning("Deadline check error: %s", e)


# ── Weekly stats ──────────────────────────────────────────────────────────────

async def _send_weekly_stats():
    try:
        uid        = str(MY_USER_ID)
        total_jobs = db.get_job_count()
        unreviewed = _db_total_unreviewed()
        applied    = len(db.get_user_jobs_by_status(uid, "applied"))
        interviews = len(db.get_user_jobs_by_status(uid, "interview"))
        offers     = len(db.get_user_jobs_by_status(uid, "offer"))

        em = discord.Embed(
            title="📊 Your Weekly PerTern Report",
            description=(
                f"**{total_jobs:,}** total internships indexed\n"
                f"**{unreviewed:,}** waiting for your review\n\n"
                f"**Your pipeline:**\n"
                f"• ✅ Applied — **{applied}**\n"
                f"• 🗣️ Interview — **{interviews}**\n"
                f"• 🎉 Offer — **{offers}**\n\n"
                "Keep pushing! 🚀"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(timezone.utc),
        )
        em.set_footer(text="PerTern Weekly · Every Sunday")
        dm = await _get_dm()
        msg = await dm.send(embed=em)
        asyncio.create_task(_delete_after(msg, 3600))
    except Exception as e:
        log.warning("Weekly stats error: %s", e)


# ── Loops ─────────────────────────────────────────────────────────────────────

@tasks.loop(minutes=SCAN_INTERVAL)
async def scan_loop():
    try:
        await _run_scan()
    except Exception:
        log.exception("Scan loop error")


@tasks.loop(time=datetime.time(hour=DIGEST_HOUR, minute=0, tzinfo=timezone.utc))
async def daily_digest_loop():
    """Morning digest — refresh the summary so you see overnight finds."""
    try:
        await _update_summary(new_count=0)
    except Exception:
        log.exception("Daily digest error")


@tasks.loop(time=datetime.time(hour=14, minute=0, tzinfo=timezone.utc))
async def weekly_stats_loop():
    if datetime.datetime.now(timezone.utc).weekday() == 6:
        await _send_weekly_stats()


@tasks.loop(minutes=15)
async def snooze_check_loop():
    """Wake up snoozed jobs whose reminder time has passed."""
    try:
        reminders = db.get_due_reminders()
        for r in reminders:
            if r.get("message") != "snooze":
                continue
            uid = str(MY_USER_ID)
            jid = r.get("job_id", "")
            uj  = db.get_user_job(uid, jid)
            if uj and uj.get("status") == "snoozed":
                db.set_user_status(uid, jid, "new")
            db.mark_reminder_sent(r["id"])
        if reminders:
            await _update_summary()
    except Exception:
        log.exception("Snooze check error")


@tasks.loop(hours=12)
async def followup_reminder_loop():
    """DM a follow-up nudge for jobs applied 14+ days ago with no status change."""
    try:
        uid   = str(MY_USER_ID)
        stale = db.get_stale_user_applied_jobs(uid, days=14)
        dm    = await _get_dm()
        for job in stale:
            key = f"followup_{job.get('job_id','')}"
            if db.get_bot_state(key):
                continue
            db.set_bot_state(key, "1")
            em = discord.Embed(
                title="📬 Time to follow up!",
                description=(
                    f"**{job.get('title')}** at **{job.get('company')}**\n"
                    f"You applied **14+ days ago** and haven't heard back.\n"
                    f"Consider sending a follow-up email!"
                ),
                color=discord.Color.orange(),
                url=job.get("url") or None,
            )
            await dm.send(embed=em)
    except Exception:
        log.exception("Follow-up reminder error")


@scan_loop.before_loop
@daily_digest_loop.before_loop
@weekly_stats_loop.before_loop
@snooze_check_loop.before_loop
@followup_reminder_loop.before_loop
async def before_loops():
    await client.wait_until_ready()


# ── Slash commands ────────────────────────────────────────────────────────────

def _owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == MY_USER_ID


_VERSION = "1.0"


@tree.command(name="version", description="Show PerTern version and last scan info")
async def slash_version(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return

    last_scan  = db.get_bot_state("last_scan_time") or "Never"
    last_count = db.get_bot_state("last_scan_new")  or "0"
    uptime_sec = (datetime.datetime.now(timezone.utc) - client.launch_time).total_seconds() if hasattr(client, "launch_time") else None
    uptime_str = ""
    if uptime_sec is not None:
        h, rem = divmod(int(uptime_sec), 3600)
        m, s   = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

    em = discord.Embed(title="PerTern", color=discord.Color.blurple())
    em.add_field(name="Version",    value=f"`v{_VERSION}`",  inline=True)
    em.add_field(name="Last Scan",  value=last_scan,         inline=True)
    em.add_field(name="New Jobs",   value=last_count,        inline=True)
    if uptime_str:
        em.add_field(name="Uptime", value=uptime_str,        inline=True)
    em.add_field(name="Log",        value=f"`{_LOG_PATH}`",  inline=False)
    await interaction.response.send_message(embed=em, ephemeral=True)


@tree.command(name="check", description="Trigger a manual scan right now")
async def slash_check(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.send_message("🔍 Scanning now...", ephemeral=True)
    count = await _run_scan(label="manual")
    await interaction.followup.send(
        f"Done — {'no new matches' if count == 0 else f'{count} new matches added to your summary'}.",
        ephemeral=True,
    )


@tree.command(name="stats", description="Your application pipeline stats")
async def slash_stats(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)

    uid        = str(MY_USER_ID)
    total_jobs = db.get_job_count()
    unreviewed = _db_total_unreviewed()
    applied    = len(db.get_user_jobs_by_status(uid, "applied"))
    interviews = len(db.get_user_jobs_by_status(uid, "interview"))
    offers     = len(db.get_user_jobs_by_status(uid, "offer"))

    em = discord.Embed(
        title="📊 PerTern Stats",
        description=(
            f"**{total_jobs:,}** total internships indexed\n"
            f"**{unreviewed:,}** waiting for your review\n\n"
            f"**Your pipeline:**\n"
            f"• ✅ Applied — **{applied}**\n"
            f"• 🗣️ Interview — **{interviews}**\n"
            f"• 🎉 Offer — **{offers}**"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(timezone.utc),
    )
    await interaction.followup.send(embed=em, ephemeral=True)


@tree.command(name="summary", description="Refresh the summary message")
async def slash_summary(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    await _update_summary()
    await interaction.followup.send("Summary refreshed!", ephemeral=True)


def _make_pi_embed() -> discord.Embed:
    """Build a live Pi stats embed."""
    s = _pi_stats()
    now = datetime.datetime.now().strftime("%H:%M:%S")

    cpu_temp = s.get("cpu_temp", "N/A")
    gpu_temp = s.get("gpu_temp", "N/A")
    cpu_pct  = s.get("cpu_pct", "N/A")
    ram_used = s.get("ram_used", "N/A")
    ram_tot  = s.get("ram_total", "N/A")
    ram_pct  = s.get("ram_pct", "N/A")
    disk_free= s.get("disk_free", "N/A")
    disk_pct = s.get("disk_pct", "N/A")
    uptime   = s.get("uptime", "N/A")
    throttled= s.get("throttled", False)

    if isinstance(cpu_temp, float):
        color = discord.Color.red() if cpu_temp >= 75 else discord.Color.orange() if cpu_temp >= 60 else discord.Color.green()
    else:
        color = discord.Color.blurple()

    em = discord.Embed(title="🍓 Pi Live Monitor", color=color, timestamp=datetime.datetime.now(timezone.utc))
    em.add_field(name="🌡️ CPU Temp",  value=f"`{cpu_temp}°C`",                        inline=True)
    em.add_field(name="🎮 GPU Temp",  value=f"`{gpu_temp}`",                           inline=True)
    em.add_field(name="⚡ CPU Usage", value=f"`{cpu_pct}%`",                           inline=True)
    em.add_field(name="🧠 RAM",       value=f"`{ram_used}/{ram_tot} GB ({ram_pct}%)`", inline=False)
    em.add_field(name="💾 Disk Free", value=f"`{disk_free} GB ({disk_pct}% used)`",    inline=False)
    em.add_field(name="⏱️ Uptime",    value=f"`{uptime}`",                             inline=True)
    if throttled:
        em.add_field(name="⚠️ Throttled", value="`Yes — check cooling`",              inline=True)
    em.set_footer(text=f"Refreshes every 5s · Last update {now}")
    return em


class LivePiView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self._task: asyncio.Task | None = None

    def set_task(self, task: asyncio.Task):
        self._task = task

    async def on_timeout(self):
        if self._task:
            self._task.cancel()

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._task:
            self._task.cancel()
        button.disabled = True
        em = _make_pi_embed()
        em.set_footer(text="Monitoring stopped.")
        await interaction.response.edit_message(embed=em, view=self)


@tree.command(name="live-pi", description="Live Raspberry Pi hardware monitor — refreshes every 5s")
async def slash_live_pi(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return

    view = LivePiView()
    await interaction.response.send_message(embed=_make_pi_embed(), view=view, ephemeral=True)

    async def _refresh_loop():
        try:
            while True:
                await asyncio.sleep(5)
                try:
                    await interaction.edit_original_response(embed=_make_pi_embed(), view=view)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_refresh_loop())
    view.set_task(task)


@tree.command(name="fortune-100", description="Browse unreviewed internships from Fortune 100 companies")
async def slash_fortune100(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return

    jobs = _db_fortune100_jobs()
    if not jobs:
        await interaction.response.send_message(
            "No unreviewed Fortune 100 internships right now.", ephemeral=True
        )
        return

    _browse["jobs"]     = jobs
    _browse["index"]    = 0
    _browse["category"] = None

    uid    = str(MY_USER_ID)
    job    = jobs[0]
    uj     = db.get_user_job(uid, job.get("job_id", ""))
    status = (uj or {}).get("status", "")
    em     = _make_job_embed(job, index=0, total=len(jobs), status=status)
    em.description = f"🏆 Fortune 100 — {len(jobs)} unreviewed internships\nUse ◀ ▶ to navigate · Applied/Skip to mark"

    view = BrowseView(job)
    await interaction.response.send_message(embed=em, view=view, ephemeral=True)
    view.message = await interaction.original_response()


def _load_resume() -> str:
    try:
        with open(_RESUME_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _claude_match(job: dict, description: str) -> str:
    """Send job + resume to Claude API and return a YES/NO match result."""
    import urllib.request
    resume = _load_resume()
    if not resume:
        return "❌ No resume found. Add your resume text to `resume.txt` in the bot folder.", ""
    if not ANTHROPIC_KEY:
        return "❌ ANTHROPIC_API_KEY not set in .env", ""

    title    = job.get("title", "Unknown Role")
    company  = job.get("company", "Unknown Company")
    location = job.get("location", "")
    desc     = description[:2000] if description else "No description available."

    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 120,
        "messages": [{
            "role": "user",
            "content": (
                f"You are a career advisor. Based on this student's resume and the job posting, "
                f"should they apply? Reply with ONLY:\n"
                f"Line 1: YES or NO\n"
                f"Line 2: One sentence reason (max 20 words).\n"
                f"Line 3: TERM: when in 2027 (e.g. Summer 2027, Spring 2027) or NOT 2027 if not a 2027 internship.\n\n"
                f"RESUME:\n{resume[:1500]}\n\n"
                f"JOB: {title} at {company} ({location})\n{desc}"
            ),
        }],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    raw        = data["content"][0]["text"].strip()
    usage      = data.get("usage", {})
    in_tokens  = usage.get("input_tokens", 0)
    out_tokens = usage.get("output_tokens", 0)

    # Haiku pricing: $0.80/M input, $4.00/M output
    cost = (in_tokens * 0.0000008) + (out_tokens * 0.000004)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    verdict_line = lines[0].upper() if lines else ""
    reason       = lines[1] if len(lines) > 1 else ""
    term_line    = lines[2] if len(lines) > 2 else ""

    if "YES" in verdict_line:
        verdict = "✅ YES"
    elif "NO" in verdict_line:
        verdict = "❌ NO"
    else:
        verdict = "🤷 UNCLEAR"

    term_str = ""
    if term_line:
        term_clean = term_line.replace("TERM:", "").replace("Line 3:", "").strip()
        if "NOT 2027" in term_clean.upper():
            term_str = "\n⚠️ May not be a 2027 internship"
        else:
            term_str = f"\n📅 {term_clean}"

    text    = f"**{verdict}**\n{reason}{term_str}"
    footer  = f"claude-haiku-4-5 · {in_tokens}in/{out_tokens}out tokens · ~${cost:.5f}"
    return text, footer


def _pi_stats() -> dict:
    """Read Raspberry Pi hardware stats. Returns empty dict if not on a Pi."""
    stats = {}
    try:
        # CPU temperature
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["cpu_temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass
    try:
        # CPU usage
        import psutil
        stats["cpu_pct"]  = psutil.cpu_percent(interval=0.5)
        stats["ram_pct"]  = psutil.virtual_memory().percent
        stats["ram_used"] = round(psutil.virtual_memory().used / 1024**3, 2)
        stats["ram_total"]= round(psutil.virtual_memory().total / 1024**3, 1)
        disk = psutil.disk_usage("/")
        stats["disk_pct"] = disk.percent
        stats["disk_free"]= round(disk.free / 1024**3, 1)
    except Exception:
        pass
    try:
        # Fan speed via raspi-gpio / vcgencmd
        import subprocess
        r = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            stats["gpu_temp"] = r.stdout.strip().replace("temp=", "").replace("'C", "°C")
        r2 = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
        if r2.returncode == 0:
            throttled_hex = r2.stdout.strip().split("=")[-1]
            stats["throttled"] = throttled_hex != "0x0"
    except Exception:
        pass
    try:
        import subprocess, uptime as _up
        secs = _up.uptime()
        h, m = divmod(int(secs) // 60, 60)
        d, h = divmod(h, 24)
        stats["uptime"] = f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
    except Exception:
        try:
            import subprocess
            r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                stats["uptime"] = r.stdout.strip().replace("up ", "")
        except Exception:
            pass
    return stats


@tree.command(name="status", description="Bot health — scan stats, jobs, Pi hardware")
async def slash_status(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return

    await interaction.response.defer(ephemeral=True)

    last_scan  = db.get_bot_state("last_scan_time") or "Never"
    last_count = db.get_bot_state("last_scan_new") or "0"

    import sqlite3 as _sq
    with _sq.connect(db.DB_PATH) as con:
        con.row_factory = _sq.Row
        total_cos   = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        active_cos  = con.execute("SELECT COUNT(*) FROM companies WHERE active=1").fetchone()[0]
        deactivated = total_cos - active_cos
        errored     = con.execute(
            "SELECT name, fail_count FROM companies WHERE fail_count > 0 AND active=1 ORDER BY fail_count DESC LIMIT 5"
        ).fetchall()
        applied   = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='applied'").fetchone()[0]
        interview = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='interview'").fetchone()[0]
        offer     = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='offer'").fetchone()[0]
        snoozed   = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='snoozed'").fetchone()[0]

    total_jobs = db.get_job_count()
    unreviewed = _db_total_unreviewed()
    pi         = _pi_stats()

    # ── Temp colour ───────────────────────────────────────────────────────────
    temp = pi.get("cpu_temp")
    if temp and temp >= 75:
        color = discord.Color.red()
    elif temp and temp >= 60:
        color = discord.Color.orange()
    else:
        color = discord.Color.blurple()

    em = discord.Embed(
        title="⚙️ PerTern Status",
        color=color,
        timestamp=datetime.datetime.now(timezone.utc),
    )

    # ── Scanner ───────────────────────────────────────────────────────────────
    em.add_field(
        name="📡  Scanner",
        value=(
            f"> Every **{SCAN_INTERVAL} min**\n"
            f"> +**{last_count}** new last scan\n"
            f"> Last ran: {last_scan}"
        ),
        inline=False,
    )

    # ── Jobs & Pipeline ───────────────────────────────────────────────────────
    em.add_field(
        name="💼  Jobs",
        value=(
            f"> **{total_jobs:,}** indexed\n"
            f"> **{unreviewed:,}** unreviewed"
        ),
        inline=False,
    )

    em.add_field(
        name="📋  Pipeline",
        value=(
            f"> ✅ Applied — **{applied}**\n"
            f"> 🗣️ Interview — **{interview}**\n"
            f"> 🎉 Offer — **{offer}**\n"
            f"> 💤 Snoozed — **{snoozed}**"
        ),
        inline=False,
    )

    # ── Companies ─────────────────────────────────────────────────────────────
    em.add_field(
        name="🏢  Companies",
        value=(
            f"> **{active_cos}** active\n"
            f"> **{deactivated}** deactivated"
        ),
        inline=False,
    )

    # ── Pi hardware ───────────────────────────────────────────────────────────
    if pi:
        pi_lines = []
        if temp:
            throttle_flag = "  🔴 throttling!" if pi.get("throttled") else ""
            pi_lines.append(f"> 🌡️ Temp — **{temp}°C**{throttle_flag}")
        if pi.get("gpu_temp"):
            pi_lines.append(f"> 🎮 GPU — **{pi['gpu_temp']}**")
        if pi.get("cpu_pct") is not None:
            pi_lines.append(f"> ⚡ CPU — **{pi['cpu_pct']}%**")
        if pi.get("ram_used") is not None:
            pi_lines.append(f"> 🧠 RAM — **{pi['ram_used']}/{pi['ram_total']} GB** ({pi['ram_pct']}%)")
        if pi.get("disk_free") is not None:
            pi_lines.append(f"> 💾 Disk — **{pi['disk_free']} GB free** ({pi['disk_pct']}% used)")
        if pi.get("uptime"):
            pi_lines.append(f"> ⏱️ Uptime — **{pi['uptime']}**")
        if pi_lines:
            em.add_field(name="🍓  Raspberry Pi", value="\n".join(pi_lines), inline=False)

    # ── Erroring companies ────────────────────────────────────────────────────
    if errored:
        err_lines = "\n".join(f"> • {r['name']} ({r['fail_count']}x)" for r in errored)
        em.add_field(name="⚠️  Erroring Companies", value=err_lines, inline=False)

    await interaction.followup.send(embed=em, ephemeral=True)


@tree.command(name="find", description="Search indexed jobs by keyword or company name")
@discord.app_commands.describe(query="Title or company to search for")
async def slash_find(interaction: discord.Interaction, query: str):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    results = db.search_jobs(query, limit=10)
    if not results:
        await interaction.followup.send(f"No jobs found matching **{query}**.", ephemeral=True)
        return
    uid = str(MY_USER_ID)
    lines = []
    for j in results:
        uj     = db.get_user_job(uid, j.get("job_id",""))
        status = (uj or {}).get("status","")
        badge  = {"applied":"✅","skipped":"⏭️","interview":"🗣️","offer":"🎉","snoozed":"💤"}.get(status,"🔵")
        url    = j.get("url","")
        link   = f"[{j.get('title','')}]({url})" if url else j.get("title","")
        lines.append(f"{badge} **{j.get('company','')}** — {link}")
    em = discord.Embed(
        title=f"🔍 Results for \"{query}\"",
        description="\n".join(lines),
        color=discord.Color.from_rgb(88, 101, 242),
    )
    em.set_footer(text=f"{len(results)} result(s)")
    await interaction.followup.send(embed=em, ephemeral=True)


@tree.command(name="export", description="DM you a CSV of all applied/interview/offer jobs")
async def slash_export(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    uid  = str(MY_USER_ID)
    rows = db.get_user_jobs_for_export(uid)
    if not rows:
        await interaction.followup.send("Nothing exported yet — mark some jobs as Applied first.", ephemeral=True)
        return
    import csv, io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["company","title","location","status","url","term","category","first_seen","notes"])
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    fname = f"pertern_export_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
    dm = await _get_dm()
    await dm.send(
        content=f"📎 Your PerTern export — **{len(rows)} jobs**",
        file=discord.File(fp=io.BytesIO(buf.getvalue().encode()), filename=fname),
    )
    await interaction.followup.send("Export sent to your DMs!", ephemeral=True)


@tree.command(name="log", description="Recent bot logs + full company error report as CSV")
async def slash_log(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)

    import csv, io, sqlite3 as _sq

    # ── Recent log lines ──────────────────────────────────────────────────────
    log_snippet = ""
    try:
        with open(_LOG_PATH, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-50:] if len(lines) > 50 else lines
        # keep WARNING+ lines plus the last 20 INFO lines for context
        important = [l for l in tail if "WARNING" in l or "ERROR" in l or "CRITICAL" in l]
        recent    = lines[-20:] if len(lines) >= 20 else lines
        combined  = list(dict.fromkeys(recent + important))  # preserve order, dedupe
        log_snippet = "".join(combined[-50:])
    except FileNotFoundError:
        log_snippet = "(log file not found — bot may not have written any logs yet)\n"

    # ── Company issues CSV ────────────────────────────────────────────────────
    with _sq.connect(db.DB_PATH) as con:
        con.row_factory = _sq.Row
        companies = con.execute(
            "SELECT name, source, url, slug, fail_count, active FROM companies "
            "WHERE active=0 OR fail_count>0 ORDER BY active ASC, fail_count DESC, name ASC"
        ).fetchall()

    csv_buf = io.StringIO()
    writer  = csv.DictWriter(csv_buf, fieldnames=["company", "source", "status", "fail_count", "reason", "url", "slug"])
    writer.writeheader()
    for r in companies:
        active     = r["active"]
        fail_count = r["fail_count"]
        if active == 0 and fail_count >= 3:
            status = "Deactivated"
            reason = f"Auto-deactivated after {fail_count} consecutive scrape failures"
        elif active == 0:
            status = "Deactivated"
            reason = "Manually deactivated or removed from CSV"
        else:
            status = "Erroring"
            reason = f"{fail_count} scrape failure(s) — not yet deactivated"
        writer.writerow({
            "company":    r["name"],
            "source":     r["source"],
            "status":     status,
            "fail_count": fail_count,
            "reason":     reason,
            "url":        r["url"] or "",
            "slug":       r["slug"] or "",
        })

    csv_buf.seek(0)
    today = datetime.datetime.now().strftime("%Y%m%d")

    combined  = "=== RECENT LOGS (last 50 lines) ===\n\n"
    combined += log_snippet or "(no log file found)\n"
    combined += "\n\n=== COMPANY ISSUES ===\n\n"
    combined += csv_buf.getvalue()

    fname = f"pertern_report_{today}.txt"
    file  = discord.File(fp=io.BytesIO(combined.encode()), filename=fname)

    issue_count = len(companies)
    await interaction.followup.send(
        content=f"📋 **{issue_count} companies** with issues",
        file=file,
        ephemeral=True,
    )


@tree.command(name="pipeline", description="See your full application funnel with company names")
async def slash_pipeline(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    uid = str(MY_USER_ID)

    def _jobs_list(status: str, limit: int = 20) -> list[dict]:
        return db.get_user_jobs_by_status(uid, status, limit=limit)

    applied    = _jobs_list("applied")
    interviews = _jobs_list("interview")
    offers     = _jobs_list("offer")
    rejected   = _jobs_list("rejected")

    def _fmt(jobs: list[dict]) -> str:
        if not jobs: return "_None yet_"
        return "\n".join(f"• {j.get('company','')} — {j.get('title','')}" for j in jobs[:10])

    em = discord.Embed(
        title="📊 Your Application Pipeline",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.add_field(name=f"✅ Applied ({len(applied)})",      value=_fmt(applied),    inline=False)
    em.add_field(name=f"🗣️ Interview ({len(interviews)})", value=_fmt(interviews), inline=False)
    em.add_field(name=f"🎉 Offer ({len(offers)})",         value=_fmt(offers),     inline=False)
    em.add_field(name=f"❌ Rejected ({len(rejected)})",    value=_fmt(rejected),   inline=False)

    if offers:
        em.set_footer(text="🎉 You have offers — congrats!")
    elif interviews:
        em.set_footer(text="🗣️ Keep going — you're in interviews!")
    else:
        em.set_footer(text="Keep applying — it's a numbers game!")

    await interaction.followup.send(embed=em, ephemeral=True)


@tree.command(name="clear-dm", description="Delete all bot messages from your DMs (clean slate)")
async def slash_clear_dm(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    dm = await _get_dm()
    deleted = 0
    try:
        async for msg in dm.history(limit=500):
            if msg.author.id == client.user.id:
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.4)  # avoid rate limit
                except Exception:
                    pass
    except Exception as e:
        await interaction.followup.send(f"Error while clearing: {e}", ephemeral=True)
        return
    # Clear stored summary message ID so next scan creates a fresh one
    db.set_bot_state(_SUMMARY_MSG_KEY, "")
    await interaction.followup.send(
        f"🗑️ Deleted **{deleted}** bot messages from your DMs. Summary will be recreated on next scan.",
        ephemeral=True,
    )


# ── on_ready ──────────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    client.launch_time = datetime.datetime.now(timezone.utc)
    log.info("PerTern online as %s", client.user)
    if not MY_USER_ID:
        log.error("MY_DISCORD_USER_ID not set!"); return
    db.init_db()
    from seed_companies import seed
    n = seed()
    log.info("Seeded %d companies from CSV", n)

    try:
        synced = await tree.sync()
        log.info("Slash commands synced: %d", len(synced))
    except Exception as e:
        log.warning("Slash sync failed: %s", e)

    try:
        dm = await _get_dm()

        # Clear all previous bot messages so the DM starts fresh
        deleted = 0
        async for msg in dm.history(limit=500):
            if msg.author.id == client.user.id:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.4)
                    deleted += 1
                except Exception as del_err:
                    log.warning("Failed to delete msg %s: %s", msg.id, del_err)
        log.info("Startup DM clear: deleted %d messages", deleted)
        db.set_bot_state(_SUMMARY_MSG_KEY, "")

        # Post fresh summary only
        await _update_summary()
    except Exception as e:
        log.warning("Startup DM failed: %s", e)

    scan_loop.start()
    daily_digest_loop.start()
    weekly_stats_loop.start()
    snooze_check_loop.start()
    followup_reminder_loop.start()
    status_rotation_loop.start()


_STATUS_ROTATION = [
    ("🔍 Hunting internships...",        discord.ActivityType.watching),
    ("📬 Checking 427+ career pages",    discord.ActivityType.watching),
    ("💼 Finding your next role",        discord.ActivityType.playing),
    ("🚀 Powered by PerTern",            discord.ActivityType.playing),
    ("⚡ Scanning Greenhouse & Workday", discord.ActivityType.watching),
    ("🎯 Matching jobs to your skills",  discord.ActivityType.playing),
    ("☕ Scanning so you don't have to", discord.ActivityType.playing),
    ("🌐 427+ companies tracked",        discord.ActivityType.watching),
    ("🔔 New match? You'll know first",  discord.ActivityType.playing),
    None,  # Pi stats slot — filled dynamically
]
_status_index = 0


def _pi_status_text() -> tuple[str, discord.ActivityType] | None:
    """Return a live Pi stats status string, or None if unavailable."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = round(int(f.read().strip()) / 1000, 1)
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.2)
            return (f"🍓 {temp}°C · CPU {cpu}%", discord.ActivityType.watching)
        except Exception:
            return (f"🍓 Running at {temp}°C", discord.ActivityType.watching)
    except Exception:
        return None


@tasks.loop(seconds=30)
async def status_rotation_loop():
    global _status_index
    slot = _STATUS_ROTATION[_status_index % len(_STATUS_ROTATION)]
    if slot is None:
        slot = _pi_status_text() or ("📡 Live on your Raspberry Pi", discord.ActivityType.watching)
    text, atype = slot
    await client.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=atype, name=text),
    )
    _status_index += 1



# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in .env")
    if not MY_USER_ID:
        raise RuntimeError("MY_DISCORD_USER_ID not set in .env")
    client.run(TOKEN)
