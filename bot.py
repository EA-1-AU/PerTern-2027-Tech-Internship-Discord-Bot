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
from datetime import timezone

import discord
from discord.ext import tasks
from dotenv import load_dotenv

import db
from scraper import run_all_scrapers
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
DIGEST_HOUR    = int(os.getenv("DIGEST_HOUR_UTC", "13"))       # 13 UTC = ~8am ET
REQUIRE_SALARY = os.getenv("REQUIRE_SALARY", "false").lower() == "true"

# ── Personal filter ───────────────────────────────────────────────────────────
# Ethan Austin — Cybersecurity BS + Business Minor @ Anderson University (SC)
# Certs: Google Cybersecurity, Google IT Support, Python for Everybody,
#        Google AI Essentials, Google Cloud Fundamentals, Microsoft Excel
# Tools: Python, SQL, Linux, GCP, Power BI, Looker Studio, Excel, Tableau
# Exp  : Lowe's data/reporting intern (Power BI, GCP, Looker), Code Ninjas
#        (Python, Lua, C#, JS), AU Makerspace (tech support, 3D printing)

MY_CATEGORIES = {
    "🔒 Cybersecurity",       # Primary degree
    "☁️ DevOps & Cloud",      # GCP cert + Lowe's GCP experience
    "📈 Data Analytics",      # Lowe's: Power BI, Looker, Excel reporting
    "📊 Data Science",        # Python cert + data analysis skills
}

# Matched against job TITLE only (descriptions are too noisy)
MY_TITLE_KEYWORDS = [
    # Cybersecurity — core degree
    "cybersecurity", "cyber security", "information security", "infosec",
    "network security", "security analyst", "security engineer",
    "security operations", "soc analyst", "incident response",
    "vulnerability", "penetration", "pen test", "risk analyst",
    "compliance analyst", "grc", "identity", "iam",
    # Cloud — GCP cert + Lowe's
    "cloud security", "cloud engineer", "cloud analyst", "cloud operations",
    "gcp", "google cloud", "cloud infrastructure",
    # Data — Lowe's tools
    "data analyst", "data analytics", "business intelligence",
    "power bi", "looker", "reporting analyst", "operations analyst",
    "bi analyst", "bi developer",
    # IT / Systems — Google IT Support cert
    "it support", "systems administrator", "system administrator",
    "network administrator", "help desk", "technical analyst",
    "it analyst", "systems analyst",
    # Python / SQL
    "python developer", "python engineer", "sql analyst",
]

# These companies ALWAYS pass through regardless of title or category
# (Fortune 500 + companies highly relevant to your background)
FORTUNE_500_WATCHLIST = {
    # Big Tech
    "apple", "microsoft", "google", "alphabet", "amazon", "meta", "nvidia",
    "intel", "ibm", "oracle", "salesforce", "adobe", "cisco", "qualcomm",
    "texas instruments", "broadcom", "hp", "dell", "hewlett packard",
    "accenture", "cognizant",
    # Cybersecurity companies
    "crowdstrike", "palo alto networks", "fortinet", "sentinelone",
    "cyberark", "tenable", "rapid7", "splunk", "darktrace", "zscaler",
    "cloudflare", "okta", "sailpoint",
    # Finance / Banking (big employers for data/security roles)
    "jpmorgan", "jp morgan", "bank of america", "wells fargo", "citigroup",
    "citibank", "goldman sachs", "morgan stanley", "american express",
    "visa", "mastercard", "capital one", "charles schwab", "fidelity",
    "blackrock", "deloitte", "pwc", "kpmg", "ernst & young", "ey",
    # Defense / Gov contractors (cybersecurity heavy)
    "lockheed martin", "boeing", "raytheon", "northrop grumman",
    "general dynamics", "l3harris", "leidos", "booz allen", "saic",
    "mantech", "peraton",
    # Telecom
    "at&t", "verizon", "t-mobile", "comcast",
    # Retail / Consumer (Lowe's competitor set + big employers)
    "walmart", "target", "home depot", "lowe's", "lowes", "costco",
    "amazon", "fedex", "ups",
    # Healthcare / Pharma (growing cybersecurity/data need)
    "unitedhealth", "cvs health", "anthem", "humana", "cigna",
    "johnson & johnson", "pfizer", "abbvie",
    # Other Fortune 500
    "procter & gamble", "general electric", "honeywell", "3m",
    "exxon", "chevron", "general motors", "ford",
    "pepsico", "coca-cola",
}

# Personal company watchlist — always included no matter what
MY_COMPANY_WATCHLIST = {
    "crowdstrike",
    "palo alto networks",
    "google", "alphabet",
    "microsoft",
    "amazon",
    "deloitte",
    "booz allen",
    "leidos",
}

# US location indicators — jobs with blank location still pass (remote/undisclosed)
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
_scan_batches: dict[int, list[dict]] = {}
_scan_counter = 0


# ── Filter logic ──────────────────────────────────────────────────────────────

def _is_us_location(location: str) -> bool:
    if not location or location.strip() == "":
        return True  # blank = remote / undisclosed, allow
    loc = f" {location.lower()} "
    return any(ind in loc for ind in _US_INDICATORS)


def _matches_me(job: dict) -> tuple[bool, str]:
    """
    Returns (match: bool, reason: str).
    reason is shown on the job card so you know why it was sent.
    """
    title    = job.get("title", "").lower()
    cat      = job.get("category", "") or ""
    company  = job.get("company", "").lower()
    location = job.get("location", "") or ""
    salary   = job.get("salary", "") or ""

    # Hard filter: US only
    if not _is_us_location(location):
        return False, ""

    # Salary filter (optional — set REQUIRE_SALARY=true in .env)
    if REQUIRE_SALARY and not salary:
        return False, ""

    # Personal watchlist — always include
    if any(w in company for w in MY_COMPANY_WATCHLIST):
        return True, f"Watchlist: {job.get('company','')}"

    # Fortune 500 — always include
    if any(f in company for f in FORTUNE_500_WATCHLIST):
        return True, f"Fortune 500: {job.get('company','')}"

    # Category match
    if cat in MY_CATEGORIES:
        return True, f"Category: {cat}"

    # Title keyword match
    for kw in MY_TITLE_KEYWORDS:
        if kw in title:
            return True, f"Keyword: {kw}"

    return False, ""


def _is_internship(title: str) -> bool:
    return bool(re.search(r'\bintern(ship)?\b', title, re.IGNORECASE))


def _2027_filter(job: dict) -> bool:
    raw = f"{job.get('title','')} {job.get('description','')}".lower()
    if "2026" in raw:
        return False
    term = job.get("term") or ""
    yr   = re.search(r'(20\d{2})', term)
    if yr:
        return yr.group(1) == "2027"
    if job.get("source", "").lower() == "simplify":
        return False
    return True


# ── Embeds ────────────────────────────────────────────────────────────────────

def _make_embed(job: dict, reason: str = "", applied: bool = False) -> discord.Embed:
    title    = job.get("title", "No Title")
    company  = job.get("company", "Unknown")
    location = job.get("location", "")
    url      = job.get("url", "")
    term     = job.get("term", "")
    salary   = job.get("salary", "")
    cat      = job.get("category", "")
    deadline = job.get("deadline", "")

    color = discord.Color.green() if applied else discord.Color.from_rgb(88, 101, 242)
    em = discord.Embed(
        title=f"{'✅ ' if applied else ''}{title}",
        url=url or None,
        color=color,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.set_author(name=company)

    if location:
        em.add_field(name="📍 Location", value=location,  inline=True)
    if term:
        em.add_field(name="📅 Term",     value=term,      inline=True)
    if salary:
        em.add_field(name="💰 Salary",   value=salary,    inline=True)
    if cat:
        em.add_field(name="🏷️ Category", value=cat,       inline=True)
    if deadline:
        em.add_field(name="⏰ Deadline", value=deadline,  inline=True)
    if reason:
        em.add_field(name="🎯 Why sent", value=reason,    inline=False)
    if url:
        em.add_field(name="🔗 Apply",    value=f"[Open listing]({url})", inline=False)
    if applied:
        em.add_field(name="📝 Status", value="✅ Marked as Applied", inline=False)

    em.set_footer(text=f"PerTern · ID: {job.get('job_id','')}")
    return em


# ── Apply tracker button ──────────────────────────────────────────────────────

class JobCardView(discord.ui.View):
    def __init__(self, job: dict, reason: str):
        super().__init__(timeout=None)
        self.job    = job
        self.reason = reason

    @discord.ui.button(label="✅ Mark Applied", style=discord.ButtonStyle.success)
    async def mark_applied(self, interaction: discord.Interaction, button: discord.ui.Button):
        jid = self.job.get("job_id", "")
        uid = str(MY_USER_ID)
        db.ensure_user_job(uid, jid)
        db.set_user_status(uid, jid, "applied")
        button.label    = "✅ Applied"
        button.disabled = True
        await interaction.response.edit_message(
            embed=_make_embed(self.job, self.reason, applied=True),
            view=self,
        )
        log.info("Marked applied: %s @ %s", self.job.get("title"), self.job.get("company"))


# ── Scan result view (summary + pagination) ───────────────────────────────────

class ScanResultView(discord.ui.View):
    def __init__(self, scan_id: int):
        super().__init__(timeout=None)
        self.scan_id   = scan_id
        self.page      = 0
        self.PAGE_SIZE = 5

    def _jobs(self) -> list[dict]:
        return _scan_batches.get(self.scan_id, [])

    @discord.ui.button(label="📋 Show Jobs", style=discord.ButtonStyle.primary)
    async def show_jobs(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        await interaction.response.defer()
        await self._send_page(interaction)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.defer()
        await self._send_page(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_page = max(0, (len(self._jobs()) - 1) // self.PAGE_SIZE)
        self.page = min(max_page, self.page + 1)
        await interaction.response.defer()
        await self._send_page(interaction)

    async def _send_page(self, interaction: discord.Interaction):
        jobs  = self._jobs()
        start = self.page * self.PAGE_SIZE
        batch = jobs[start : start + self.PAGE_SIZE]
        total_pages = max(1, -(-len(jobs) // self.PAGE_SIZE))

        for entry in batch:
            job    = entry["job"]
            reason = entry["reason"]
            jid    = job.get("job_id", "")
            uid    = str(MY_USER_ID)
            applied = False
            try:
                uj = db.get_user_job(uid, jid)
                applied = (uj or {}).get("status") == "applied"
            except Exception:
                pass
            try:
                await interaction.followup.send(
                    embed=_make_embed(job, reason, applied),
                    view=JobCardView(job, reason),
                )
            except Exception as e:
                log.warning("Job send error: %s", e)

        await interaction.followup.send(
            f"Page {self.page + 1}/{total_pages} · {len(jobs)} total matches this scan"
        )


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _get_dm() -> discord.DMChannel:
    user = await client.fetch_user(MY_USER_ID)
    return await user.create_dm()


async def _run_scan(label: str = "") -> list[dict]:
    global _scan_counter
    log.info("Scan starting%s...", f" ({label})" if label else "")
    loop     = asyncio.get_event_loop()
    new_jobs: list[dict] = []   # list of {"job": ..., "reason": ...}

    def _on_batch(company: str, raw_jobs: list[dict]):
        for job in raw_jobs:
            if not _is_internship(job.get("title", "")):
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
            new_jobs.append({"job": job, "reason": reason})

    await loop.run_in_executor(None, lambda: run_all_scrapers(on_batch=_on_batch))

    count = len(new_jobs)
    log.info("Scan done — %d new matches", count)

    if count == 0:
        return []

    # Store batch
    _scan_counter += 1
    scan_id = _scan_counter
    _scan_batches[scan_id] = new_jobs

    # Category breakdown for summary
    cats: dict[str, int] = {}
    f500_count = 0
    for entry in new_jobs:
        r = entry["reason"]
        c = entry["job"].get("category") or "Other"
        if r.startswith("Fortune 500") or r.startswith("Watchlist"):
            f500_count += 1
        cats[c] = cats.get(c, 0) + 1

    lines = [f"• {c} — **{n}**" for c, n in sorted(cats.items(), key=lambda x: -x[1])]
    if f500_count:
        lines.append(f"• ⭐ Fortune 500 / Watchlist — **{f500_count}**")

    em = discord.Embed(
        title=f"🔍 {count} new internship{'s' if count != 1 else ''} found",
        description="\n".join(lines) + "\n\nClick **Show Jobs** to browse them.",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.datetime.now(timezone.utc),
    )
    em.set_footer(text=f"PerTern · Scan #{scan_id} · {db.get_job_count():,} total indexed")

    try:
        dm = await _get_dm()
        await dm.send(embed=em, view=ScanResultView(scan_id))
    except Exception as e:
        log.warning("Summary DM failed: %s", e)

    # Check for upcoming deadlines and send reminders
    await _check_deadlines()

    return new_jobs


# ── Deadline reminders ────────────────────────────────────────────────────────

async def _check_deadlines():
    """DM about jobs with deadlines in the next 3 days."""
    try:
        uid  = str(MY_USER_ID)
        jobs = db.get_all_jobs() if hasattr(db, "get_all_jobs") else []
        now  = datetime.datetime.now(timezone.utc)
        for job in jobs:
            deadline_str = job.get("deadline", "")
            if not deadline_str:
                continue
            # Try common date formats
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
                try:
                    dl = datetime.datetime.strptime(deadline_str.strip(), fmt).replace(tzinfo=timezone.utc)
                    days_left = (dl - now).days
                    if 0 <= days_left <= 3:
                        jid = job.get("job_id", "")
                        state_key = f"reminded_{jid}"
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
        applied    = len(db.get_user_jobs_by_status(uid, "applied"))   if hasattr(db, "get_user_jobs_by_status") else "?"
        interviews = len(db.get_user_jobs_by_status(uid, "interview")) if hasattr(db, "get_user_jobs_by_status") else "?"
        offers     = len(db.get_user_jobs_by_status(uid, "offer"))     if hasattr(db, "get_user_jobs_by_status") else "?"

        em = discord.Embed(
            title="📊 Your Weekly PerTern Report",
            description=(
                f"**{total_jobs:,}** total internships indexed\n\n"
                f"**Your pipeline this week:**\n"
                f"• ✅ Applied — **{applied}**\n"
                f"• 🗣️ Interview — **{interviews}**\n"
                f"• 🎉 Offer — **{offers}**\n\n"
                f"Keep pushing — you've got this! 🚀"
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


@tasks.loop(
    time=datetime.time(hour=DIGEST_HOUR, minute=0, tzinfo=timezone.utc)
)
async def daily_digest_loop():
    """Every day at DIGEST_HOUR UTC — send everything found in the last 24h."""
    try:
        since = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=24)
        jobs  = db.get_jobs_since(since.isoformat()) if hasattr(db, "get_jobs_since") else []
        if not jobs:
            return
        _scan_counter_local = max(_scan_batches.keys(), default=0) + 1
        entries = [{"job": j, "reason": "Daily digest"} for j in jobs]
        _scan_batches[_scan_counter_local] = entries

        em = discord.Embed(
            title=f"☀️ Good morning! {len(jobs)} internships from the last 24h",
            description="Click **Show Jobs** to review everything found overnight.",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(timezone.utc),
        )
        em.set_footer(text=f"PerTern Daily Digest · {db.get_job_count():,} total indexed")
        dm = await _get_dm()
        await dm.send(embed=em, view=ScanResultView(_scan_counter_local))
    except Exception:
        log.exception("Daily digest error")


@tasks.loop(
    time=datetime.time(hour=14, minute=0, tzinfo=timezone.utc)   # Sunday 9am ET
)
async def weekly_stats_loop():
    if datetime.datetime.now(timezone.utc).weekday() == 6:  # Sunday
        await _send_weekly_stats()


@scan_loop.before_loop
@daily_digest_loop.before_loop
@weekly_stats_loop.before_loop
async def before_loops():
    await client.wait_until_ready()


# ── Slash commands ────────────────────────────────────────────────────────────

@tree.command(name="check", description="Trigger a manual scan right now")
async def slash_check(interaction: discord.Interaction):
    if interaction.user.id != MY_USER_ID:
        await interaction.response.send_message("This is a personal bot.", ephemeral=True)
        return
    await interaction.response.send_message("🔍 Scanning now...", ephemeral=True)
    results = await _run_scan(label="manual")
    if not results:
        await interaction.followup.send("No new matches found this scan.", ephemeral=True)


@tree.command(name="stats", description="Your application stats")
async def slash_stats(interaction: discord.Interaction):
    if interaction.user.id != MY_USER_ID:
        await interaction.response.send_message("This is a personal bot.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await _send_weekly_stats()
    await interaction.followup.send("Stats sent to your DMs!", ephemeral=True)


@tree.command(name="applied", description="List all jobs you've marked as applied")
async def slash_applied(interaction: discord.Interaction):
    if interaction.user.id != MY_USER_ID:
        await interaction.response.send_message("This is a personal bot.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    uid  = str(MY_USER_ID)
    jobs = db.get_user_jobs_by_status(uid, "applied") if hasattr(db, "get_user_jobs_by_status") else []
    if not jobs:
        await interaction.followup.send("No jobs marked as applied yet.", ephemeral=True)
        return
    dm = await _get_dm()
    await dm.send(f"📋 **{len(jobs)} jobs marked as applied:**")
    for j in jobs[:10]:
        full = db.get_job(j["job_id"])
        if full:
            await dm.send(embed=_make_embed(full, applied=True))
    await interaction.followup.send(f"Sent {min(len(jobs),10)} applied jobs to your DMs.", ephemeral=True)


@tree.command(name="status", description="Bot status — uptime, jobs indexed, next scan")
async def slash_status(interaction: discord.Interaction):
    if interaction.user.id != MY_USER_ID:
        await interaction.response.send_message("This is a personal bot.", ephemeral=True)
        return
    em = discord.Embed(
        title="⚙️ PerTern Status",
        description=(
            f"**Jobs indexed:** {db.get_job_count():,}\n"
            f"**Scan interval:** every {SCAN_INTERVAL} minutes\n"
            f"**Daily digest:** {DIGEST_HOUR}:00 UTC (~8am ET)\n"
            f"**Salary filter:** {'On' if REQUIRE_SALARY else 'Off'}\n"
            f"**Scans this session:** {_scan_counter}\n"
        ),
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(timezone.utc),
    )
    await interaction.response.send_message(embed=em, ephemeral=True)


# ── on_ready ──────────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    log.info("PerTern online as %s", client.user)
    if not MY_USER_ID:
        log.error("MY_DISCORD_USER_ID not set — can't DM you!")
        return
    db.init_db()

    try:
        synced = await tree.sync()
        log.info("Slash commands synced: %d", len(synced))
    except Exception as e:
        log.warning("Slash sync failed: %s", e)

    try:
        dm = await _get_dm()
        await dm.send(embed=discord.Embed(
            title="✅ PerTern Online",
            description=(
                f"Scanning every **{SCAN_INTERVAL} minutes**.\n"
                f"Daily digest at **{DIGEST_HOUR}:00 UTC** (~8am ET).\n"
                f"Weekly stats every **Sunday**.\n\n"
                f"**Filters:** Cybersecurity · Cloud/GCP · Data Analytics · US only\n"
                f"**Fortune 500 watchlist:** always included\n"
                f"**Salary filter:** {'On' if REQUIRE_SALARY else 'Off'}\n\n"
                f"**{db.get_job_count():,}** internships already indexed.\n\n"
                f"Commands: `/check` `/stats` `/applied` `/status`"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(timezone.utc),
        ))
    except Exception as e:
        log.warning("Startup DM failed: %s", e)

    scan_loop.start()
    daily_digest_loop.start()
    weekly_stats_loop.start()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in .env")
    if not MY_USER_ID:
        raise RuntimeError("MY_DISCORD_USER_ID not set in .env")
    client.run(TOKEN)
