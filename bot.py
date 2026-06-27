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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pertern")

TOKEN          = os.getenv("DISCORD_TOKEN", "")
MY_USER_ID     = int(os.getenv("MY_DISCORD_USER_ID", "0"))
SCAN_INTERVAL  = int(os.getenv("SCAN_INTERVAL_MINUTES", "10"))
DIGEST_HOUR    = int(os.getenv("DIGEST_HOUR_UTC", "13"))
REQUIRE_SALARY = os.getenv("REQUIRE_SALARY", "false").lower() == "true"

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
    return bool(re.search(r'\bintern(ship)?\b', title, re.IGNORECASE))


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
    color = {"applied": discord.Color.green(), "skipped": discord.Color.dark_gray()}.get(
        status, discord.Color.from_rgb(88, 101, 242)
    )

    em = discord.Embed(
        title=f"{status_prefix}{title}",
        url=url or None,
        color=color,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.set_author(name=company)

    if location: em.add_field(name="📍 Location", value=location,  inline=True)
    if term:     em.add_field(name="📅 Term",     value=term,       inline=True)
    if salary:   em.add_field(name="💰 Salary",   value=salary,     inline=True)
    if cat:      em.add_field(name="🏷️ Category", value=cat,        inline=True)
    if deadline: em.add_field(name="⏰ Deadline", value=deadline,   inline=True)
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
        await interaction.response.edit_message(embed=em, view=BrowseView(job))


# ── Browse UI ─────────────────────────────────────────────────────────────────

class BrowseView(discord.ui.View):
    """
    Row 0: ◀ Prev | ✅ Applied | ⏭️ Skip | ▶ Next
    Row 1: 🗣️ Interview | 🎉 Offer | 💤 Snooze | 🔗 Link
    """

    def __init__(self, job: dict):
        super().__init__(timeout=None)
        self.job = job

    async def _go(self, interaction: discord.Interaction, new_index: int):
        jobs = _browse["jobs"]
        new_index = max(0, min(len(jobs) - 1, new_index))
        _browse["index"] = new_index
        job    = jobs[new_index]
        uid    = str(MY_USER_ID)
        uj     = db.get_user_job(uid, job.get("job_id", ""))
        status = (uj or {}).get("status", "")
        em     = _make_job_embed(job, index=new_index, total=len(jobs), status=status)
        await interaction.response.edit_message(embed=em, view=BrowseView(job))

    async def _mark_direct(self, interaction: discord.Interaction, status: str):
        jid = self.job.get("job_id", "")
        uid = str(MY_USER_ID)
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, status)
        await _advance_after_mark(interaction, status)

    # ── Row 0 ─────────────────────────────────────────────────────────────────

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, _browse["index"] - 1)

    @discord.ui.button(label="✅ Applied", style=discord.ButtonStyle.success, row=0)
    async def applied_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyNoteModal(self.job))

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.danger, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "skipped")

    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, _browse["index"] + 1)

    # ── Row 1 ─────────────────────────────────────────────────────────────────

    @discord.ui.button(label="🗣️ Interview", style=discord.ButtonStyle.primary, row=1)
    async def interview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "interview")

    @discord.ui.button(label="🎉 Offer", style=discord.ButtonStyle.primary, row=1)
    async def offer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "offer")

    @discord.ui.button(label="💤 Snooze", style=discord.ButtonStyle.secondary, row=1)
    async def snooze_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SnoozeModal(self.job))

    @discord.ui.button(label="🔗 Copy Link", style=discord.ButtonStyle.secondary, row=1)
    async def link_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = self.job.get("url", "")
        if url:
            await interaction.response.send_message(f"🔗 **Apply link** (tap to open or hold to copy):\n{url}", ephemeral=True)
        else:
            await interaction.response.send_message("No URL available for this listing.", ephemeral=True)

    @discord.ui.button(label="❌ Rejected", style=discord.ButtonStyle.danger, row=1)
    async def rejected_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._mark_direct(interaction, "rejected")

    @discord.ui.button(label="⭐ Priority", style=discord.ButtonStyle.secondary, row=2)
    async def priority_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        company = self.job.get("company", "")
        new_val = db.toggle_company_priority(company)
        label = "on" if new_val else "off"
        await interaction.response.send_message(
            f"⭐ **{company}** priority **{label}** — new jobs from this company will {'appear first' if new_val else 'sort normally'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="📄 Details", style=discord.ButtonStyle.secondary, row=2)
    async def details_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_event_loop()
        job  = self.job
        desc = await loop.run_in_executor(None, lambda: fetch_job_description(job))
        if not desc:
            # Fall back to stored description
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
        await interaction.followup.send(embed=em)


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
                "No unreviewed jobs in that category right now!", ephemeral=False
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

        await interaction.response.send_message(embed=em, view=BrowseView(job))


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
        await dm.send(embed=em)
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
    await _send_weekly_stats()
    await interaction.followup.send("Stats sent!", ephemeral=True)


@tree.command(name="summary", description="Refresh the summary message")
async def slash_summary(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    await _update_summary()
    await interaction.followup.send("Summary refreshed!", ephemeral=True)


@tree.command(name="status", description="Bot health — scan stats, jobs, company errors")
async def slash_status(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return

    last_scan  = db.get_bot_state("last_scan_time") or "Never"
    last_count = db.get_bot_state("last_scan_new") or "0"

    import sqlite3 as _sq
    with _sq.connect(db.DB_PATH) as con:
        con.row_factory = _sq.Row
        total_cos    = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        active_cos   = con.execute("SELECT COUNT(*) FROM companies WHERE active=1").fetchone()[0]
        deactivated  = total_cos - active_cos
        errored      = con.execute(
            "SELECT name, fail_count FROM companies WHERE fail_count > 0 AND active=1 ORDER BY fail_count DESC LIMIT 8"
        ).fetchall()
        applied      = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='applied'").fetchone()[0]
        interview    = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='interview'").fetchone()[0]
        offer        = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='offer'").fetchone()[0]
        snoozed      = con.execute("SELECT COUNT(*) FROM user_jobs WHERE status='snoozed'").fetchone()[0]

    total_jobs   = db.get_job_count()
    unreviewed   = _db_total_unreviewed()
    reviewed     = total_jobs - unreviewed

    em = discord.Embed(title="⚙️ PerTern Status", color=discord.Color.blurple(),
                       timestamp=datetime.datetime.now(timezone.utc))

    em.add_field(name="📡 Scanning", value=(
        f"Every **{SCAN_INTERVAL} min**\n"
        f"Last: {last_scan}\n"
        f"+{last_count} new last scan"
    ), inline=True)

    em.add_field(name="📬 Daily Digest", value=(
        f"{DIGEST_HOUR}:00 UTC\n"
        f"~8 AM ET\n"
        f"Weekly stats: Sunday"
    ), inline=True)

    em.add_field(name="​", value="​", inline=True)  # spacer

    em.add_field(name="💼 Jobs", value=(
        f"**{total_jobs:,}** indexed\n"
        f"**{unreviewed:,}** unreviewed\n"
        f"**{reviewed:,}** reviewed"
    ), inline=True)

    em.add_field(name="📋 Pipeline", value=(
        f"Applied: **{applied}**\n"
        f"Interview: **{interview}**\n"
        f"Offer: **{offer}**\n"
        f"Snoozed: **{snoozed}**"
    ), inline=True)

    em.add_field(name="🏢 Companies", value=(
        f"Active: **{active_cos}**\n"
        f"Deactivated: **{deactivated}**"
    ), inline=True)

    if errored:
        err_lines = "\n".join(f"• {r['name']} ({r['fail_count']}x)" for r in errored)
        em.add_field(name="⚠️ Erroring Companies", value=err_lines, inline=False)
    else:
        em.add_field(name="⚠️ Erroring Companies", value="None ✅", inline=False)

    await interaction.response.send_message(embed=em, ephemeral=True)


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


@tree.command(name="deactivated", description="Export deactivated and erroring companies to CSV")
async def slash_deactivated(interaction: discord.Interaction):
    if not _owner_only(interaction):
        await interaction.response.send_message("Personal bot.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)

    import csv, io, sqlite3 as _sq
    with _sq.connect(db.DB_PATH) as con:
        con.row_factory = _sq.Row
        deactivated = con.execute(
            "SELECT name, source, url, slug, fail_count, active FROM companies "
            "WHERE active=0 OR fail_count>0 ORDER BY active ASC, fail_count DESC, name ASC"
        ).fetchall()

    if not deactivated:
        await interaction.followup.send("No deactivated or erroring companies.", ephemeral=True)
        return

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["company", "source", "status", "fail_count", "reason", "url", "slug"])
    writer.writeheader()
    for r in deactivated:
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
            reason = f"{fail_count} consecutive scrape failure(s) — not yet deactivated"
        writer.writerow({
            "company":    r["name"],
            "source":     r["source"],
            "status":     status,
            "fail_count": fail_count,
            "reason":     reason,
            "url":        r["url"] or "",
            "slug":       r["slug"] or "",
        })

    buf.seek(0)
    fname = f"pertern_deactivated_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
    await interaction.followup.send(
        content=f"📎 **{len(deactivated)} companies** with issues",
        file=discord.File(fp=io.BytesIO(buf.getvalue().encode()), filename=fname),
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
    ("🔍 Hunting internships...",       discord.ActivityType.watching),
    ("📬 Checking 400+ career pages",   discord.ActivityType.watching),
    ("💼 Finding your next role",       discord.ActivityType.playing),
    ("🚀 Powered by PerTern",           discord.ActivityType.playing),
    ("⚡ Scanning Greenhouse & Workday", discord.ActivityType.watching),
    ("🎯 Matching jobs to your skills", discord.ActivityType.playing),
    ("📡 Live on your Raspberry Pi",    discord.ActivityType.watching),
    ("☕ Scanning so you don't have to", discord.ActivityType.playing),
    ("🌐 410+ companies tracked",       discord.ActivityType.watching),
    ("🔔 New match? You'll know first", discord.ActivityType.playing),
]
_status_index = 0


@tasks.loop(seconds=30)
async def status_rotation_loop():
    global _status_index
    text, atype = _STATUS_ROTATION[_status_index % len(_STATUS_ROTATION)]
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
