"""
Database layer for PerTern — worldwide internship Discord bot.

Single SQLite file, no ORM. Schema is migration-safe via ALTER TABLE.
"""

import json
import sqlite3
import datetime
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "pertern.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL,
    source TEXT NOT NULL,
    slug   TEXT,
    url    TEXT,
    active INTEGER DEFAULT 1,
    UNIQUE(name, source)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    company     TEXT NOT NULL,
    source      TEXT NOT NULL,
    title       TEXT,
    location    TEXT,
    description TEXT,
    url         TEXT,
    category    TEXT,
    subcategory TEXT,
    term        TEXT,
    salary      TEXT,
    deadline    TEXT,
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id       TEXT PRIMARY KEY,
    countries     TEXT DEFAULT '[]',
    cities        TEXT DEFAULT '[]',
    fields        TEXT DEFAULT '[]',
    subcategories TEXT DEFAULT '[]',
    terms         TEXT DEFAULT '[]',
    remote_pref   TEXT DEFAULT 'any',
    keywords      TEXT DEFAULT '',
    setup_done    INTEGER DEFAULT 0,
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS server_channels (
    guild_id      TEXT NOT NULL,
    channel_name  TEXT NOT NULL,
    channel_id    TEXT NOT NULL,
    channel_type  TEXT,
    PRIMARY KEY (guild_id, channel_name)
);

CREATE TABLE IF NOT EXISTS referral_offers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    company    TEXT NOT NULL,
    notes      TEXT,
    created_at TEXT,
    UNIQUE(user_id, company)
);

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    job_id     TEXT NOT NULL,
    remind_at  TEXT NOT NULL,
    message    TEXT,
    sent       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_ratings (
    user_id    TEXT NOT NULL,
    job_id     TEXT NOT NULL,
    rating     INTEGER NOT NULL,
    created_at TEXT,
    PRIMARY KEY (user_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_at, sent);

CREATE TABLE IF NOT EXISTS user_goals (
    user_id       TEXT PRIMARY KEY,
    weekly_target INTEGER DEFAULT 5,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS reported_jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    job_id     TEXT NOT NULL,
    reason     TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    job_id            TEXT NOT NULL,
    status            TEXT DEFAULT 'new',
    priority          INTEGER DEFAULT 0,
    referral          INTEGER DEFAULT 0,
    notes             TEXT,
    status_updated_at TEXT,
    UNIQUE(user_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_first_seen  ON jobs(first_seen DESC);
CREATE INDEX IF NOT EXISTS idx_history_job      ON job_history(job_id);
CREATE INDEX IF NOT EXISTS idx_user_jobs_user   ON user_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_user_jobs_status ON user_jobs(status);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor(commit=False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_db():
    with db_cursor(commit=True) as cur:
        cur.executescript(SCHEMA)
        for stmt in [
            "ALTER TABLE companies ADD COLUMN fail_count INTEGER DEFAULT 0",
            "ALTER TABLE companies ADD COLUMN priority INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN subcategory TEXT",
            "ALTER TABLE user_prefs ADD COLUMN cities TEXT DEFAULT '[]'",
            "ALTER TABLE user_prefs ADD COLUMN subcategories TEXT DEFAULT '[]'",
            "CREATE TABLE IF NOT EXISTS referral_offers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, company TEXT NOT NULL, notes TEXT, created_at TEXT, UNIQUE(user_id, company))",
            "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)",
            "CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, job_id TEXT NOT NULL, remind_at TEXT NOT NULL, message TEXT, sent INTEGER DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS job_ratings (user_id TEXT NOT NULL, job_id TEXT NOT NULL, rating INTEGER NOT NULL, created_at TEXT, PRIMARY KEY (user_id, job_id))",
            "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_at, sent)",
            "CREATE TABLE IF NOT EXISTS user_goals (user_id TEXT PRIMARY KEY, weekly_target INTEGER DEFAULT 5, created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS reported_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, job_id TEXT NOT NULL, reason TEXT, created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS company_notes (user_id TEXT NOT NULL, company TEXT NOT NULL, note TEXT NOT NULL, updated_at TEXT, PRIMARY KEY (user_id, company))",
        ]:
            try:
                cur.execute(stmt)
            except Exception:
                pass


# ── Companies ─────────────────────────────────────────────────────────────────

def upsert_company(name, source, slug=None, url=None, priority=0):
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO companies (name, source, slug, url, active, priority) VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT(name, source) DO UPDATE SET
               slug=excluded.slug, url=excluded.url, active=1, priority=excluded.priority""",
            (name, source, slug, url, priority),
        )


def get_all_active_companies():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM companies WHERE active=1 ORDER BY priority DESC, name ASC")
        return [dict(r) for r in cur.fetchall()]


def toggle_company_priority(company_name: str) -> int:
    """Toggle priority for a company by name. Returns new priority value (0 or 1)."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT priority FROM companies WHERE LOWER(name)=LOWER(?)", (company_name,))
        row = cur.fetchone()
        new = 0 if (row and row[0]) else 1
        cur.execute("UPDATE companies SET priority=? WHERE LOWER(name)=LOWER(?)", (new, company_name))
        return new


def record_company_failure(name, source):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE companies SET fail_count=fail_count+1 WHERE name=? AND source=?",
            (name, source),
        )
        cur.execute("SELECT fail_count FROM companies WHERE name=? AND source=?", (name, source))
        row = cur.fetchone()
        count = row[0] if row else 0
        if count >= 3:
            cur.execute("UPDATE companies SET active=0 WHERE name=? AND source=?", (name, source))
            return count, True
        return count, False


def reset_company_failures(name, source):
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE companies SET fail_count=0 WHERE name=? AND source=?", (name, source))


def deactivate_company_by_name(name):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE companies SET active=0 WHERE LOWER(name) LIKE LOWER(?)", (f"%{name}%",)
        )
        return cur.rowcount


def reactivate_company_by_name(name):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE companies SET active=1, fail_count=0 WHERE LOWER(name) LIKE LOWER(?)",
            (f"%{name}%",),
        )
        return cur.rowcount


def get_broken_companies():
    with db_cursor() as cur:
        cur.execute(
            "SELECT name, source, fail_count FROM companies "
            "WHERE fail_count>0 AND active=1 ORDER BY fail_count DESC"
        )
        return [dict(r) for r in cur.fetchall()]


# ── Jobs ──────────────────────────────────────────────────────────────────────

def job_exists(job_id):
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,))
        return cur.fetchone() is not None


def job_exists_by_url(company, url):
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM jobs WHERE company=? AND url=?", (company, url))
        return cur.fetchone() is not None


def insert_job(job_id, company, source, title, location, url,
               description="", category=None, subcategory=None,
               term=None, deadline=None, salary=None):
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT OR IGNORE INTO jobs
               (job_id, company, source, title, location, url,
                description, category, subcategory, term, deadline, salary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, company, source, title, location, url,
             description, category, subcategory, term, deadline, salary),
        )


def get_job(job_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        r = cur.fetchone()
        return dict(r) if r else None


def get_job_by_url(url):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE url=?", (url,))
        r = cur.fetchone()
        return dict(r) if r else None


def get_job_count():
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs")
        return cur.fetchone()[0]


def get_recent_jobs(since_iso: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE first_seen >= ? ORDER BY first_seen DESC",
            (since_iso,),
        )
        return [dict(r) for r in cur.fetchall()]


def search_jobs(keyword, limit=10):
    pattern = f"%{keyword}%"
    with db_cursor() as cur:
        cur.execute(
            """SELECT * FROM jobs WHERE title LIKE ? OR company LIKE ? OR description LIKE ?
               ORDER BY first_seen DESC LIMIT ?""",
            (pattern, pattern, pattern, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_jobs_by_company(name, limit=20):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE company LIKE ? ORDER BY first_seen DESC LIMIT ?",
            (f"%{name}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]


def find_duplicate_jobs(limit=20):
    with db_cursor() as cur:
        cur.execute(
            """SELECT company, LOWER(TRIM(title)) as norm_title, COUNT(*) as n,
                      GROUP_CONCAT(job_id, '|||') as ids
               FROM jobs GROUP BY company, LOWER(TRIM(title))
               HAVING n > 1 ORDER BY n DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_hot_companies(limit=10):
    with db_cursor() as cur:
        cur.execute(
            "SELECT company, COUNT(*) as n FROM jobs GROUP BY company ORDER BY n DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Per-user job state ────────────────────────────────────────────────────────

def get_user_job(user_id: str, job_id: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id)
        )
        r = cur.fetchone()
        return dict(r) if r else None


def ensure_user_job(user_id: str, job_id: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT OR IGNORE INTO user_jobs (user_id, job_id) VALUES (?, ?)",
            (user_id, job_id),
        )


def set_user_status(user_id: str, job_id: str, status: str):
    ensure_user_job(user_id, job_id)
    now = datetime.datetime.now().isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id)
        )
        row = cur.fetchone()
        old = row[0] if row else None
        cur.execute(
            "UPDATE user_jobs SET status=?, status_updated_at=? WHERE user_id=? AND job_id=?",
            (status, now, user_id, job_id),
        )
        cur.execute(
            "INSERT INTO job_history (job_id, user_id, old_status, new_status, changed_at) "
            "VALUES (?,?,?,?,?)",
            (job_id, user_id, old, status, now),
        )


def toggle_user_priority(user_id: str, job_id: str) -> int:
    ensure_user_job(user_id, job_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE user_jobs SET priority=1-priority WHERE user_id=? AND job_id=?",
            (user_id, job_id),
        )
        cur.execute(
            "SELECT priority FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id)
        )
        return cur.fetchone()[0]


def toggle_user_referral(user_id: str, job_id: str) -> int:
    ensure_user_job(user_id, job_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE user_jobs SET referral=1-referral WHERE user_id=? AND job_id=?",
            (user_id, job_id),
        )
        cur.execute(
            "SELECT referral FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id)
        )
        return cur.fetchone()[0]


def add_user_note(user_id: str, job_id: str, note: str):
    ensure_user_job(user_id, job_id)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT notes FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id)
        )
        row = cur.fetchone()
        existing = (row[0] or "") if row else ""
        new_notes = (existing + "\n" if existing else "") + f"[{ts}] {note}"
        cur.execute(
            "UPDATE user_jobs SET notes=? WHERE user_id=? AND job_id=?",
            (new_notes, user_id, job_id),
        )


def get_user_jobs_by_status(user_id: str, status: str, limit=20) -> list:
    with db_cursor() as cur:
        cur.execute(
            """SELECT j.*, uj.status as user_status, uj.priority, uj.referral, uj.notes
               FROM user_jobs uj JOIN jobs j ON uj.job_id=j.job_id
               WHERE uj.user_id=? AND uj.status=?
               ORDER BY uj.priority DESC, j.first_seen DESC LIMIT ?""",
            (user_id, status, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_user_status_counts(user_id: str) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) as n FROM user_jobs WHERE user_id=? GROUP BY status",
            (user_id,),
        )
        return {r["status"]: r["n"] for r in cur.fetchall()}


def get_stale_user_applied_jobs(user_id: str, days=14) -> list:
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            """SELECT j.* FROM user_jobs uj JOIN jobs j ON uj.job_id=j.job_id
               WHERE uj.user_id=? AND uj.status='applied'
               AND uj.status_updated_at IS NOT NULL AND uj.status_updated_at < ?""",
            (user_id, cutoff),
        )
        return [dict(r) for r in cur.fetchall()]


def get_user_jobs_for_export(user_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            """SELECT j.company, j.title, j.location, uj.status, j.url,
                      j.term, j.category, j.first_seen, uj.notes
               FROM user_jobs uj JOIN jobs j ON uj.job_id=j.job_id
               WHERE uj.user_id=? AND uj.status IN ('applied','interview','offer')
               ORDER BY uj.status, j.company""",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_status_history(job_id: str, user_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM job_history WHERE job_id=? AND user_id=? ORDER BY changed_at",
            (job_id, user_id),
        )
        return [dict(r) for r in cur.fetchall()]


def skip_all_new_for_user(user_id: str) -> int:
    now = datetime.datetime.now().isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE user_jobs SET status='skip', status_updated_at=? "
            "WHERE user_id=? AND status='new'",
            (now, user_id),
        )
        return cur.rowcount


# ── User preferences ──────────────────────────────────────────────────────────

def get_user_prefs(user_id: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM user_prefs WHERE user_id=?", (str(user_id),))
        r = cur.fetchone()
        return dict(r) if r else None


def set_user_prefs(user_id: str, prefs: dict):
    now = datetime.datetime.now().isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO user_prefs
               (user_id, countries, cities, fields, subcategories, terms,
                remote_pref, keywords, setup_done, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   countries=excluded.countries, cities=excluded.cities,
                   fields=excluded.fields, subcategories=excluded.subcategories,
                   terms=excluded.terms, remote_pref=excluded.remote_pref,
                   keywords=excluded.keywords, setup_done=1,
                   updated_at=excluded.updated_at""",
            (
                str(user_id),
                json.dumps(prefs.get("countries", [])),
                json.dumps(prefs.get("cities", [])),
                json.dumps(prefs.get("fields", [])),
                json.dumps(prefs.get("subcategories", [])),
                json.dumps(prefs.get("terms", [])),
                prefs.get("remote_pref", "any"),
                prefs.get("keywords", ""),
                now, now,
            ),
        )


def get_all_setup_users() -> list:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM user_prefs WHERE setup_done=1")
        return [dict(r) for r in cur.fetchall()]


def delete_user_prefs(user_id: str):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM user_prefs WHERE user_id=?", (str(user_id),))


# ── Server channel registry ───────────────────────────────────────────────────

def set_server_channel(guild_id: str, channel_name: str, channel_id: str, channel_type: str = None):
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO server_channels (guild_id, channel_name, channel_id, channel_type)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, channel_name) DO UPDATE SET
               channel_id=excluded.channel_id, channel_type=excluded.channel_type""",
            (guild_id, channel_name, channel_id, channel_type),
        )


def get_server_channel(guild_id: str, channel_name: str) -> str | None:
    with db_cursor() as cur:
        cur.execute(
            "SELECT channel_id FROM server_channels WHERE guild_id=? AND channel_name=?",
            (guild_id, channel_name),
        )
        r = cur.fetchone()
        return r[0] if r else None


def get_all_server_channels(guild_id: str) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT channel_name, channel_id, channel_type FROM server_channels WHERE guild_id=?",
            (guild_id,),
        )
        return {r["channel_name"]: {"id": r["channel_id"], "type": r["channel_type"]}
                for r in cur.fetchall()}


def clear_server_channels(guild_id: str):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM server_channels WHERE guild_id=?", (guild_id,))


def get_all_setup_guilds() -> list[str]:
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT guild_id FROM server_channels")
        return [r[0] for r in cur.fetchall()]


# ── Referral offers ───────────────────────────────────────────────────────────

def add_referral_offer(user_id: str, company: str, notes: str = ""):
    now = datetime.datetime.now().isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO referral_offers (user_id, company, notes, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, company) DO UPDATE SET notes=excluded.notes""",
            (str(user_id), company, notes, now),
        )


def remove_referral_offer(user_id: str, company: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM referral_offers WHERE user_id=? AND LOWER(company)=LOWER(?)",
            (str(user_id), company),
        )


def get_user_referral_offers(user_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT company, notes, created_at FROM referral_offers WHERE user_id=? ORDER BY company",
            (str(user_id),),
        )
        return [dict(r) for r in cur.fetchall()]


def get_referrers_for_company(company: str) -> list:
    """Return list of user_ids who have a referral for this company (case-insensitive)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT user_id, notes FROM referral_offers WHERE LOWER(company)=LOWER(?)",
            (company,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Deadline queries ───────────────────────────────────────────────────────────

def get_user_jobs_with_deadlines(user_id: str, days: int = 14) -> list:
    """Return user's saved/applied jobs that have a deadline within `days` days."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT j.*, uj.status, uj.priority
               FROM user_jobs uj JOIN jobs j ON uj.job_id=j.job_id
               WHERE uj.user_id=? AND uj.status NOT IN ('rejected','skip')
               AND j.deadline IS NOT NULL AND j.deadline != ''
               ORDER BY j.deadline ASC""",
            (str(user_id),),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Bot state (milestone tracking, etc.) ──────────────────────────────────────

def clear_all_jobs():
    """Delete every job from the jobs table (used for full deep-rescan resets)."""
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM jobs")


def get_bot_state(key: str) -> str | None:
    with db_cursor() as cur:
        cur.execute("SELECT value FROM bot_state WHERE key=?", (key,))
        r = cur.fetchone()
        return r[0] if r else None


def set_bot_state(key: str, value: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ── Reminders ─────────────────────────────────────────────────────────────────

def add_reminder(user_id: str, job_id: str, remind_at: str, message: str = ""):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO reminders (user_id, job_id, remind_at, message) VALUES (?,?,?,?)",
            (str(user_id), job_id, remind_at, message),
        )


def get_due_reminders() -> list:
    now = datetime.datetime.now().isoformat()
    with db_cursor() as cur:
        cur.execute(
            "SELECT r.*, j.title, j.company, j.url FROM reminders r "
            "LEFT JOIN jobs j ON r.job_id=j.job_id "
            "WHERE r.sent=0 AND r.remind_at <= ? LIMIT 50",
            (now,),
        )
        return [dict(r) for r in cur.fetchall()]


def mark_reminder_sent(reminder_id: int):
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE reminders SET sent=1 WHERE id=?", (reminder_id,))


def get_user_reminders(user_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT r.*, j.title, j.company FROM reminders r "
            "LEFT JOIN jobs j ON r.job_id=j.job_id "
            "WHERE r.user_id=? AND r.sent=0 ORDER BY r.remind_at ASC",
            (str(user_id),),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Job ratings ────────────────────────────────────────────────────────────────

def rate_job(user_id: str, job_id: str, rating: int):
    now = datetime.datetime.now().isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO job_ratings (user_id, job_id, rating, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id, job_id) DO UPDATE SET rating=excluded.rating",
            (str(user_id), job_id, rating, now),
        )


def get_job_avg_rating(job_id: str) -> tuple[float, int]:
    with db_cursor() as cur:
        cur.execute("SELECT AVG(rating), COUNT(*) FROM job_ratings WHERE job_id=?", (job_id,))
        r = cur.fetchone()
        return (round(r[0] or 0, 1), r[1] or 0)


def get_top_rated_jobs(limit: int = 10) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT j.*, AVG(jr.rating) as avg_r, COUNT(jr.rating) as votes "
            "FROM job_ratings jr JOIN jobs j ON jr.job_id=j.job_id "
            "GROUP BY jr.job_id HAVING votes >= 2 ORDER BY avg_r DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Leaderboard ────────────────────────────────────────────────────────────────

def get_leaderboard(limit: int = 10) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT user_id, COUNT(*) as total, "
            "SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied, "
            "SUM(CASE WHEN status='interview' THEN 1 ELSE 0 END) as interviews, "
            "SUM(CASE WHEN status='offer' THEN 1 ELSE 0 END) as offers "
            "FROM user_jobs WHERE status != 'skip' "
            "GROUP BY user_id ORDER BY applied DESC, interviews DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_random_job() -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM jobs ORDER BY RANDOM() LIMIT 1")
        r = cur.fetchone()
        return dict(r) if r else None


def get_salary_insights() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT salary FROM jobs WHERE salary IS NOT NULL AND salary != '' LIMIT 500")
        salaries = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT category, COUNT(*) as n FROM jobs WHERE salary IS NOT NULL GROUP BY category ORDER BY n DESC LIMIT 5")
        by_cat = [dict(r) for r in cur.fetchall()]
    return {"samples": salaries[:50], "count": len(salaries), "by_category": by_cat}


def get_status_history(job_id: str, user_id: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM job_history WHERE job_id=? AND user_id=? ORDER BY changed_at",
            (job_id, user_id),
        )
        return [dict(r) for r in cur.fetchall()]


def get_notes(user_id: str, job_id: str) -> str | None:
    with db_cursor() as cur:
        cur.execute("SELECT notes FROM user_jobs WHERE user_id=? AND job_id=?", (user_id, job_id))
        r = cur.fetchone()
        return r[0] if r else None


def get_jobs_by_location(location_keyword: str, limit: int = 10) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE LOWER(location) LIKE ? ORDER BY first_seen DESC LIMIT ?",
            (f"%{location_keyword.lower()}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_jobs_by_category(category: str, limit: int = 10) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE category=? ORDER BY first_seen DESC LIMIT ?",
            (category, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def count_jobs_by_category(category: str) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs WHERE category=?", (category,))
        return cur.fetchone()[0]


def count_jobs_by_location(keyword: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM jobs WHERE LOWER(location) LIKE ?",
            (f"%{keyword.lower()}%",),
        )
        return cur.fetchone()[0]


def get_featured_job() -> dict | None:
    """Pick today's featured job — highest salary or most recent with a salary."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE salary IS NOT NULL AND salary != '' "
            "ORDER BY first_seen DESC LIMIT 20"
        )
        rows = cur.fetchall()
        if rows:
            import random
            return dict(random.choice(rows))
        cur.execute("SELECT * FROM jobs ORDER BY first_seen DESC LIMIT 1")
        r = cur.fetchone()
        return dict(r) if r else None


# ── Stats & misc ──────────────────────────────────────────────────────────────

def get_weekly_stats(user_id: str) -> dict:
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs WHERE first_seen >= ?", (cutoff,))
        new_this_week = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM user_jobs "
            "WHERE user_id=? AND status='applied' AND status_updated_at >= ?",
            (user_id, cutoff),
        )
        applied_this_week = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id=? AND status IN ('interview','offer')",
            (user_id,),
        )
        interviews = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM user_jobs "
            "WHERE user_id=? AND status IN ('applied','interview','offer','rejected')",
            (user_id,),
        )
        total_applied = cur.fetchone()[0]
    return {
        "new_this_week":     new_this_week,
        "applied_this_week": applied_this_week,
        "interviews":        interviews,
        "total_applied":     total_applied,
        "response_rate":     round(interviews / total_applied * 100) if total_applied else 0,
    }


# ── Goals ─────────────────────────────────────────────────────────────────────

def set_user_goal(user_id: str, weekly_target: int):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO user_goals (user_id, weekly_target, created_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET weekly_target=excluded.weekly_target",
            (str(user_id), weekly_target, datetime.datetime.utcnow().isoformat()),
        )


def get_user_goal(user_id: str) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT weekly_target FROM user_goals WHERE user_id=?", (str(user_id),))
        r = cur.fetchone()
        return r[0] if r else 5


def get_all_user_goals() -> list:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM user_goals")
        return [dict(r) for r in cur.fetchall()]


def get_apps_this_week(user_id: str) -> int:
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id=? AND status='applied' AND status_updated_at>=?",
            (str(user_id), cutoff),
        )
        return cur.fetchone()[0]


# ── Feedback & reports ─────────────────────────────────────────────────────────

def add_feedback(user_id: str, message: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO feedback (user_id, message, created_at) VALUES (?,?,?)",
            (str(user_id), message, datetime.datetime.utcnow().isoformat()),
        )


def report_job(user_id: str, job_id: str, reason: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO reported_jobs (user_id, job_id, reason, created_at) VALUES (?,?,?,?)",
            (str(user_id), job_id, reason, datetime.datetime.utcnow().isoformat()),
        )


def get_report_count(job_id: str) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM reported_jobs WHERE job_id=?", (job_id,))
        return cur.fetchone()[0]


def flag_job_inactive(job_id: str):
    """Mark a job that was reported too many times as no longer active."""
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))


# ── Company notes ──────────────────────────────────────────────────────────────

def get_company_note(user_id: str, company: str) -> str | None:
    with db_cursor() as cur:
        cur.execute(
            "SELECT note FROM company_notes WHERE user_id=? AND LOWER(company)=LOWER(?)",
            (str(user_id), company),
        )
        r = cur.fetchone()
        return r[0] if r else None


def set_company_note(user_id: str, company: str, note: str):
    now = datetime.datetime.utcnow().isoformat()
    with db_cursor(commit=True) as cur:
        if note.strip():
            cur.execute(
                """INSERT INTO company_notes (user_id, company, note, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(user_id, company) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at""",
                (str(user_id), company, note.strip(), now),
            )
        else:
            cur.execute(
                "DELETE FROM company_notes WHERE user_id=? AND LOWER(company)=LOWER(?)",
                (str(user_id), company),
            )
