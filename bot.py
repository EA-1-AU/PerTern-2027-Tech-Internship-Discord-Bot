"""
personal_bot.py — DisTern Personal Edition
Runs on a Raspberry Pi and DMs matching internships directly to you.
No server setup, no channels, no slash commands needed.

Set these in your .env:
  DISCORD_TOKEN=...
  MY_DISCORD_USER_ID=...   (your Discord user ID — right-click yourself → Copy User ID)
  SCAN_INTERVAL_MINUTES=20 (optional, default 20)
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

import discord
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
log = logging.getLogger("personal")

TOKEN            = os.getenv("DISCORD_TOKEN", "")
MY_USER_ID       = int(os.getenv("MY_DISCORD_USER_ID", "0"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MINUTES", "10"))

# ── Your personal preferences (auto-tuned from your resume) ──────────────────
# Cybersecurity BS @ Anderson University | Python | GCP | Data Analytics | Linux

MY_CATEGORIES = {
    "🔒 Cybersecurity",
    "☁️ DevOps & Cloud",
    "💻 Software Engineering",
    "📊 Data Science",
    "🔩 Data Engineering",
    "📈 Data Analytics",
    "🤖 AI & Machine Learning",
    "⚙️ Operations & HR",       # IT Support / Systems Admin roles
}

# Any of these keywords in title/description → always include regardless of category
MY_KEYWORDS = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "network security", "security analyst", "security engineer", "soc",
    "incident response", "vulnerability", "penetration", "pen test",
    "risk management", "compliance", "grc",
    "cloud", "gcp", "google cloud", "aws", "azure",
    "data analyst", "data analytics", "business intelligence", "bi",
    "power bi", "looker", "tableau", "data science",
    "python", "sql", "linux", "sysadmin", "system admin",
    "it support", "technical support", "network",
]

# Prefer US roles + remote
MY_PREFERRED_LOCATIONS = ["united states", "us", "usa", "remote", "north carolina", "nc"]

# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client  = discord.Client(intents=intents)

_seen_job_ids: set[str] = set()   # in-memory dedup across scans this session


def _matches_me(job: dict) -> bool:
    """Return True if this job is relevant to Ethan's background."""
    title = job.get("title", "").lower()
    desc  = job.get("description", "").lower()
    cat   = job.get("category", "") or ""
    text  = f"{title} {desc}"

    # Category match
    if cat in MY_CATEGORIES:
        return True

    # Keyword match in title or description
    if any(kw in text for kw in MY_KEYWORDS):
        return True

    return False


def _is_internship(title: str) -> bool:
    return bool(re.search(r'\bintern(ship)?\b', title, re.IGNORECASE))


def _2027_filter(job: dict) -> bool:
    """Only allow 2027 jobs (or undated non-Simplify). Reject anything 2026."""
    raw = f"{job.get('title','')} {job.get('description','')}".lower()
    if "2026" in raw:
        return False
    term = job.get("term") or ""
    yr   = re.search(r'(20\d{2})', term)
    if yr:
        return yr.group(1) == "2027"
    # Undated Simplify = 2026 repo default → reject
    if job.get("source", "").lower() == "simplify":
        return False
    return True


def _make_embed(job: dict) -> discord.Embed:
    title    = job.get("title", "No Title")
    company  = job.get("company", "Unknown")
    location = job.get("location", "")
    url      = job.get("url", "")
    term     = job.get("term", "")
    salary   = job.get("salary", "")
    cat      = job.get("category", "")
    sub      = job.get("subcategory", "")

    em = discord.Embed(
        title=f"{title}",
        url=url or None,
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.now(timezone.utc),
    )
    em.set_author(name=company)

    if location:
        em.add_field(name="📍 Location", value=location, inline=True)
    if term:
        em.add_field(name="📅 Term",     value=term,     inline=True)
    if salary:
        em.add_field(name="💰 Salary",   value=salary,   inline=True)
    if cat:
        label = f"{cat}"
        if sub:
            label += f" › {sub}"
        em.add_field(name="🏷️ Category", value=label, inline=False)
    if url:
        em.add_field(name="🔗 Apply", value=f"[Open listing]({url})", inline=False)

    em.set_footer(text=f"DisTern Personal · ID: {job.get('job_id','')}")
    return em


async def _dm_me(embed: discord.Embed):
    try:
        user = await client.fetch_user(MY_USER_ID)
        dm   = await user.create_dm()
        await dm.send(embed=embed)
    except Exception as e:
        log.warning("DM failed: %s", e)


async def _run_scan():
    log.info("Scan starting...")
    loop       = asyncio.get_event_loop()
    new_jobs: list[dict] = []
    queue: asyncio.Queue = asyncio.Queue()

    def _on_batch(company: str, raw_jobs: list[dict]):
        for job in raw_jobs:
            if not _is_internship(job.get("title", "")):
                continue
            tag_job(job)
            # 2027 filter disabled for testing
            if not _matches_me(job):
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
            new_jobs.append(job)
            loop.call_soon_threadsafe(queue.put_nowait, job)

    # Run scraper in thread pool
    await loop.run_in_executor(None, lambda: run_all_scrapers(on_batch=_on_batch))
    queue.put_nowait(None)  # sentinel

    # Drain queue and DM each match
    count = 0
    while True:
        job = await queue.get()
        if job is None:
            break
        await _dm_me(_make_embed(job))
        count += 1

    log.info("Scan done — %d new matches DMed to you", count)
    return count


@client.event
async def on_ready():
    log.info("DisTern Personal online as %s", client.user)
    if not MY_USER_ID:
        log.error("MY_DISCORD_USER_ID not set in .env — can't DM you!")
        return
    db.init_db()

    # Send a startup ping so you know it's running
    try:
        user = await client.fetch_user(MY_USER_ID)
        dm   = await user.create_dm()
        await dm.send(embed=discord.Embed(
            title="✅ DisTern Personal Online",
            description=(
                f"Running on your Raspberry Pi and scanning every **{SCAN_INTERVAL} minutes**.\n"
                f"Filtering for: Cybersecurity · Cloud · Data Analytics · Python · Linux · GCP\n\n"
                f"**{db.get_job_count():,}** internships already indexed.\n"
                "New 2027 matches will arrive here automatically."
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        ))
    except Exception as e:
        log.warning("Startup DM failed: %s", e)

    scan_loop.start()


@discord.ext.tasks.loop(minutes=SCAN_INTERVAL)
async def scan_loop():
    try:
        await _run_scan()
    except Exception:
        log.exception("Scan loop error")


@scan_loop.before_loop
async def before_scan():
    await client.wait_until_ready()
    # Small delay so startup DM arrives before first scan results
    await asyncio.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in .env")
    if not MY_USER_ID:
        raise RuntimeError("MY_DISCORD_USER_ID not set in .env")
    client.run(TOKEN)
