<div align="center">
  <img src="https://raw.githubusercontent.com/EA-1-AU/PerTern-2027-Tech-Internship-Discord-Bot/master/Banner.png" alt="PerTern Banner" width="100%"/>
</div>

<br/>

<div align="center">

# PerTern

**Your personal internship feed — delivered straight to your Discord DMs.**

PerTern scrapes **427+ company career pages** every 10 minutes, filters for internships that match your background, and sends each new match directly to you via Discord DM. No server. No channels. Just you.

[![Version](https://img.shields.io/badge/version-1.0-blueviolet?style=flat)](https://github.com/EA-1-AU/PerTern-2027-Tech-Internship-Discord-Bot)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=flat&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

## What PerTern does

- **427+ companies scraped** every 10 minutes across Greenhouse, Lever, Ashby, SmartRecruiters, Workday, iCIMS, Oracle, ADP, custom career pages, and the SimplifyJobs GitHub feed
- **Personalized matching** — filters for roles aligned to your skills: Cybersecurity, Cloud/GCP, Data Analytics, Python, SQL, Linux, Network Security, IT Support, AI/ML
- **Discord DMs only** — no server required, matches land directly in your inbox
- **Deduplication** — never sends the same listing twice
- **2027 filter** — only surfaces Spring, Summer, and Fall 2027 internships; drops 2026 and undated listings
- **Auto-deadline detection** — scans job descriptions for deadline phrases and flags them with ⏰; embed turns orange (⚠️) if ≤7 days away, red (🚨) if ≤3 days
- **Smart location** — if the scraper returns a generic location, the title is parsed to extract the real city/state or Remote/Hybrid status
- **Rotating bot status** — cycling presence messages including live Raspberry Pi temperature and CPU usage
- **Startup confirmation** — DMs you when the bot comes online

---

## Browse & track

When a match arrives you get a job embed with a compact action bar:

```
◀ Prev  |  ✅ Applied  |  ⏭️ Skip  |  ▶ Next  |  ••• More
```

Tap **••• More** to expand:

```
🗣️ Interview  |  🎉 Offer  |  ❌ Rejected  |  💤 Snooze  |  ← Back
🔗 Copy Link  |  ⭐ Priority  |  📄 Details
```

The browse session **auto-deletes after 3 minutes** of inactivity to keep your DMs clean. The summary embed **updates automatically** after every job you review so your counts stay current.

### Commands

| Command | What it does |
|---|---|
| `/summary` | Summary of all unreviewed internships by category with a browse dropdown |
| `/pipeline` | Full application funnel with company names — applied, interviews, offers |
| `/stats` | Application pipeline stats — counts by status and response rate |
| `/find <query>` | Search indexed jobs by keyword or company name |
| `/export` | DM a CSV of all applied, interview, and offer jobs |
| `/check` | Trigger a manual scan immediately |
| `/status` | Bot health — scan stats, job counts, company error report, and live Pi hardware stats (CPU temp, RAM, disk, uptime) |
| `/deactivated` | Export a CSV of deactivated and erroring companies |
| `/clear-dm` | Delete all bot messages from your DMs for a clean slate |

---

## Matched categories

PerTern filters across these categories by default. Edit `MY_CATEGORIES` and `MY_KEYWORDS` in `bot.py` to match your own background.

| Category | Subcategories |
|---|---|
| 🔒 Cybersecurity | Security Engineering, Network Security, Cloud Security, Pen Testing, SOC & Threat Intel, Incident Response, GRC, Cryptography |
| ☁️ DevOps & Cloud | DevOps & CI/CD, Cloud Engineering, Site Reliability, IT & Sysadmin, Automation & Scripting |
| 💻 Software Engineering | General, Frontend, Backend, Mobile, Game Dev, QA & Test Engineering |
| 📈 Data Analytics | Data Analyst, BI, Tableau, Power BI, Reporting |
| 📊 Data Science | Data Scientist, Research Analyst, Applied Scientist |
| 🔩 Data Engineering | Data Pipeline, ETL, Spark, Airflow, Database Administration |
| 🤖 AI & Machine Learning | ML Engineering, Computer Vision, NLP & Language AI |
| 💼 Business & Finance | Investment Banking, Consulting, Product Management, Finance, Sales |
| 🎨 Creative & Design | UI/UX, Graphic Design, Video & Animation, Content |
| 🔬 Science & Research | Biology, Chemistry, Physics, Aerospace, Climate |
| 🏥 Healthcare & Medicine | Clinical Research, Biotech, Public Health, Healthcare IT |
| ⚖️ Law & Policy | Legal, Public Policy, Compliance, IP Law |
| 📰 Media & Communications | Journalism, PR, Marketing, Social Media |
| 🏛️ Government & Defense | Intelligence, Defense Tech, Civil Service |
| 🎓 Education & Non-profit | Teaching, EdTech, Social Work, Non-profit |
| ⚙️ Operations & HR | Supply Chain, Project Management, HR, Customer Success |
| 🔧 Hardware & Embedded | Embedded Systems, Hardware Engineering, Robotics |
| ⛓️ Blockchain & Web3 | Smart Contracts, DeFi, Web3 Engineering |

Keyword matching includes: `cybersecurity`, `network security`, `cloud security`, `cloud`, `python`, `sql`, `linux`, `data analyst`, `power bi`, `it support`, `incident response`, `vulnerability`, `siem`, `zero trust`, and more.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/EA-1-AU/PerTern-2027-Tech-Internship-Discord-Bot.git
cd PerTern-2027-Tech-Internship-Discord-Bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

```env
DISCORD_TOKEN=your-bot-token-here
MY_DISCORD_USER_ID=your-discord-user-id-here
SCAN_INTERVAL_MINUTES=10
```

> **Get your user ID:** Discord → Settings → Advanced → enable Developer Mode → right-click your name → Copy User ID.

> **Bot token:** [discord.com/developers](https://discord.com/developers/applications) → your app → Bot → Reset Token. Enable **Message Content Intent**.

### 3. Seed companies and start

```bash
python seed_companies.py   # load all 427+ companies into the database
python bot.py              # start the bot
```

You'll receive a DM confirmation when the bot is online.

### 4. Run as a systemd service (auto-start on boot)

```bash
sed -i 's/YOUR_USERNAME/your-actual-username/g' pertern.service

sudo cp pertern.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pertern
sudo systemctl start pertern

# Check status / live logs
sudo systemctl status pertern
journalctl -u pertern -f
```

### Updating

```bash
git pull
pip install -r requirements.txt
sudo systemctl restart pertern
```

---

## Customizing your filters

Open `bot.py` and edit the `MY_CATEGORIES` and `MY_KEYWORDS` sets near the top to adjust what roles get sent to you.

---

## Project structure

```
PerTern/
├── bot.py              # Main bot — scraper loop, DM delivery, slash commands
├── db.py               # SQLite database layer
├── filters.py          # Preference matching helpers
├── tagging.py          # Auto-tags jobs: category, term, salary, deadline, location
├── scraper/
│   ├── __init__.py     # run_all_scrapers() entry point
│   └── ats.py          # Fetchers: Greenhouse, Lever, Ashby, Workday, iCIMS, etc.
├── seed_companies.py   # Upserts companies.csv → DB on every startup
├── companies.csv       # 427+ companies to track
├── pertern.service     # systemd service file for Raspberry Pi
├── requirements.txt
└── .env.example
```

---

## Tech stack

| Layer | Tech |
|---|---|
| Bot framework | discord.py 2.x |
| Language | Python 3.11+ |
| Database | SQLite |
| HTTP scraping | requests + BeautifulSoup |
| Concurrency | asyncio + ThreadPoolExecutor |
| Deployment | systemd on Raspberry Pi |

---

---

## Keywords

<!-- searchability -->
2027 internships · summer 2027 internships · fall 2027 internships · spring 2027 internships · tech internships 2027 · software engineering internship 2027 · cybersecurity internship 2027 · data science internship 2027 · cloud engineering internship 2027 · AI internship 2027 · Discord internship bot · internship tracker Discord · automated internship finder · Greenhouse scraper · Workday internship scraper · Lever internship · Ashby jobs · SimplifyJobs · internship alert bot · Discord DM bot · Raspberry Pi Discord bot · Python Discord bot · internship aggregator · job board scraper · 2027 SWE intern · 2027 tech recruit

---

<div align="center">

Made with ☕ · [Report an issue](https://github.com/EA-1-AU/PerTern-2027-Tech-Internship-Discord-Bot/issues)

</div>
