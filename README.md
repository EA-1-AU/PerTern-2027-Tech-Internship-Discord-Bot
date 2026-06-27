<!-- Add your banner image to the repo root as Banner.png, then replace the line below -->
<!-- <div align="center">
  <img src="https://raw.githubusercontent.com/EA-1-AU/PerTern/master/Banner.png" alt="PerTern Banner" width="100%"/>
</div> -->

<br/>

<div align="center">

# PerTern

**Your personal internship feed — delivered straight to your Discord DMs.**

PerTern scrapes **310+ company career pages** every 10 minutes, filters for internships that match your background, and sends each new match directly to you via Discord DM. No server. No channels. Just you.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=flat&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

## What PerTern does

- **310+ companies scraped** every 10 minutes across Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Oracle, custom career pages, and the SimplifyJobs GitHub feed
- **Personalized matching** — filters for roles aligned to your skills: Cybersecurity, Cloud/GCP, Data Analytics, Python, SQL, Linux, Network Security, IT Support, AI/ML
- **Discord DMs only** — no server required, matches land directly in your inbox
- **Startup confirmation** — bot DMs you when it comes online so you know it's running
- **Deduplication** — never sends the same listing twice

---

## Matched categories

PerTern looks for roles in these areas based on your background:

| Category | Why |
|---|---|
| 🔒 Cybersecurity | BS in Cybersecurity + Google Cybersecurity cert |
| ☁️ DevOps & Cloud | Google Cloud cert + GCP experience at Lowe's |
| 📈 Data Analytics | Power BI, Looker Studio, Excel at Lowe's internship |
| 📊 Data Science | Python for Everybody cert + data analysis background |
| 🔩 Data Engineering | SQL + data pipeline experience |
| 💻 Software Engineering | Python, JavaScript, C# from Code Ninjas |
| 🤖 AI & Machine Learning | Google AI Essentials cert |
| ⚙️ Operations & HR | IT Support cert + system administration skills |

Plus keyword matching for: `cybersecurity`, `network security`, `cloud`, `gcp`, `python`, `sql`, `linux`, `data analyst`, `power bi`, `looker`, `it support`, `incident response`, `vulnerability`, and more.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/EA-1-AU/PerTern.git
cd PerTern
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
python seed_companies.py   # load all 310+ companies into the database
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
├── bot.py              # Main bot — scraper loop + DM delivery
├── db.py               # SQLite database layer
├── filters.py          # Preference matching helpers
├── tagging.py          # Auto-tags jobs: category, subcategory, term, salary
├── scraper/
│   ├── __init__.py     # run_all_scrapers() entry point
│   └── ats.py          # Fetchers: Greenhouse, Lever, Ashby, Workday, etc.
├── seed_companies.py   # One-time import of companies.csv → DB
├── companies.csv       # 310+ companies to track
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

<div align="center">

Made with ☕ · [Report an issue](https://github.com/EA-1-AU/PerTern/issues)

</div>
