# 🏍️ Moto Guzzi V7 II — Marketplace Monitor

A **serverless, API-key-free** monitor that watches German marketplaces
(**Kleinanzeigen.de** and **mobile.de**) for **Moto Guzzi V7 II** listings,
intelligently verifies that each advert is *genuinely* a V7 II, and publishes a
clean, mobile-responsive dashboard to **GitHub Pages** — updated automatically
twice a day by **GitHub Actions**.

No Telegram, no WhatsApp, no server to maintain. Just a static page that always
shows the latest finds.

👉 **Live dashboard:** `https://<your-username>.github.io/<your-repo>/`

---

## ✨ What it does

- **Scrapes** Kleinanzeigen and mobile.de for "Moto Guzzi V7" (broad on purpose).
- **Verifies the model.** Instead of trusting the title, a classifier reads each
  listing's **first-registration year, power (PS/kW), displacement, gearbox and
  equipment** and decides whether it is a real **V7 II** — filtering out the
  Mk1 (5-speed, pre-2015), the V7 III (52 PS, 2017+) and the V7 850 (65 PS).
  Every card shows a **Confirmed / Likely / Uncertain** verdict with the reasons.
- **Tracks history** in a plain `listings.json` file (the repo *is* the database).
- **Generates** a Tailwind-styled `index.html` with cards, price/mileage/EZ/PS,
  a pulsing **NEW** badge for finds in the last 48 h, filters and search.
- **Deploys** itself: commits the updated data + dashboard back to the repo and
  publishes to GitHub Pages — on a cron schedule, hands-free.

---

## 📁 Project structure

```
.
├── scraper.py                     # Main orchestrator / entry point
├── config.py                      # All tunable settings in one place
├── requirements.txt               # requests, beautifulsoup4, lxml, tzdata
├── listings.json                  # The "database" (starts as [])
├── index.html                     # Generated dashboard (auto-updated)
├── src/
│   ├── models.py                  # Listing + Classification dataclasses
│   ├── http_client.py             # Retries, browser headers, optional proxy
│   ├── parsing.py                 # Price / km / year / power parsers (DE format)
│   ├── classifier.py              # ★ The V7 II detection logic
│   ├── storage.py                 # Load / merge / save listings.json
│   ├── dashboard.py               # HTML dashboard generator (Tailwind)
│   └── scrapers/
│       ├── base.py                # Shared scraper scaffolding
│       ├── kleinanzeigen.py       # Kleinanzeigen.de scraper
│       └── mobile_de.py           # mobile.de scraper
└── .github/workflows/
    └── scrape_and_deploy.yml      # The twice-daily automation
```

---

## 🚀 Setup — step by step

### 1. Create the repository

```bash
# In this project folder:
git init
git add .
git commit -m "Initial commit: Moto Guzzi V7 II monitor"

# Create an empty repo on GitHub first, then:
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

> The repo can be **public** (required for free GitHub Pages) or private (Pages
> on private repos needs a paid plan).

### 2. Enable the correct workflow permissions ⚙️

The workflow needs to **push** the updated `listings.json` / `index.html` back
to the repo, so give Actions write access:

1. Go to your repo → **Settings → Actions → General**.
2. Scroll to **Workflow permissions**.
3. Select **“Read and write permissions”**.
4. Click **Save**.

*(This is the single most common reason the auto-commit step fails — don't skip
it.)*

### 3. Enable GitHub Pages 🌍

1. Go to **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **“GitHub Actions”**.
3. That's it — the `deploy-pages` step in the workflow publishes the site. Your
   dashboard will be live at `https://<your-username>.github.io/<your-repo>/`.

### 4. (Recommended) Add a scraping proxy secret 🔐

Both marketplaces frequently **block GitHub Actions' datacenter IPs**. To scrape
reliably, route requests through a German exit IP:

1. Get a free API key from **[scraperapi.com](https://www.scraperapi.com/)**
   (the free tier is enough for two runs a day).
2. In your repo → **Settings → Secrets and variables → Actions → New repository
   secret**.
3. Name it **`SCRAPER_API_KEY`** and paste your key.

The code auto-detects the secret and uses it. **If you leave it unset, the
scraper still runs** — it just falls back to direct requests, which may return
fewer or no results when the sites are blocking.

> Prefer a plain proxy? Set a `PROXY_URL` secret
> (`http://user:pass@host:port`) instead — it's used when `SCRAPER_API_KEY` is
> empty.

### 5. Run it

- **Automatically:** the workflow runs on its cron schedule (see below).
- **Manually now:** go to **Actions → “Scrape & Deploy Dashboard” → Run
  workflow**. After it finishes, open your Pages URL.

---

## ⏰ Schedule (and the timezone gotcha)

The workflow runs twice daily:

```yaml
schedule:
  - cron: "0 6 * * *"    # 06:00 UTC
  - cron: "0 18 * * *"   # 18:00 UTC
```

**GitHub Actions cron is always UTC.** Germany is UTC+2 in summer (CEST) and
UTC+1 in winter (CET), so those runs land at roughly **08:00 & 20:00** in summer
and **07:00 & 19:00** in winter. Edit the cron lines in
`.github/workflows/scrape_and_deploy.yml` if you want different times.

---

## 💻 Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: use the proxy locally too
export SCRAPER_API_KEY="your-key"

python scraper.py                  # full run: scrape + rebuild dashboard
python scraper.py --no-scrape      # only rebuild index.html from listings.json
python scraper.py --verbose        # debug logging

# Then just open index.html in your browser.
```

---

## 🔧 Customising

Everything lives in **`config.py`**:

| Setting | Purpose |
|---|---|
| `SEARCH_TERM` | What to search for (kept broad; the classifier narrows it). |
| `MIN_PRICE_EUR` / `MAX_PRICE_EUR` | Optional price window. |
| `MIN_YEAR` / `MAX_YEAR` | Optional first-registration window. |
| `POSTAL_CODE` / `RADIUS_KM` | Location filter (applied on mobile.de). |
| `MIN_STORE_CONFIDENCE` | How sure the classifier must be to keep a listing. |
| `CONFIRMED_CONFIDENCE` | Threshold for the green “Confirmed” badge. |
| `NEW_LISTING_HOURS` | Age window for the “NEW” badge (default 48 h). |
| `MAX_SEARCH_PAGES` / `MAX_DETAIL_FETCHES_PER_SITE` | Scraping breadth / politeness. |
| `ENABLE_KLEINANZEIGEN` / `ENABLE_MOBILE_DE` | Turn a site on/off. |

### How the V7 II classifier decides

See `src/classifier.py`. In short, it scores evidence:

| Signal | Effect |
|---|---|
| Explicit “V7 II” / “V7 2” in the text | strong **+** |
| First registration 2015–2016 | **+** (2017 is ambiguous with the III) |
| First registration ≤ 2014 or ≥ 2018 | **−** (Mk1 / III / 850) |
| 48 PS (35 kW) or 34 PS (A2) | **+** · 52 PS or ≥ 60 PS | **−** |
| 6-speed gearbox / ABS / traction control | **+** · 5-speed | **−** |
| Says “V7 III”, “V7 850” / “853 ccm” | **hard reject** |

---

## ⚠️ Notes & maintenance

- **Marketplace HTML changes.** Scrapers depend on site structure; if results
  dry up, the CSS selectors in `src/scrapers/*.py` may need a refresh. Every
  lookup is written defensively, so a layout change degrades gracefully (fewer
  results) rather than crashing.
- **Graceful degradation.** If a site blocks a run entirely, the dashboard is
  still rebuilt from the existing database — it never goes blank.
- **Be a good citizen.** This is intended for **personal, low-frequency** use
  (twice a day). Respect each site's Terms of Service and `robots.txt`, and
  don't crank up the request rate.
- **Accuracy.** The classifier is a strong heuristic, not an oracle. Always
  confirm the exact model and condition with the seller before acting.

---

## 🧱 Architecture at a glance

```
GitHub Actions (cron 2×/day)
        │
        ▼
   scraper.py ──► scrapers/ ──► http_client (optional ScraperAPI proxy)
        │              │
        │              ▼
        │         classifier.py  (is it really a V7 II?)
        ▼
   storage.py  ──►  listings.json   (append new, keep newest-first)
        │
        ▼
   dashboard.py ──►  index.html      (Tailwind, responsive)
        │
        ▼
   commit + push  ──►  deploy-pages  ──►  🌍 GitHub Pages
```

No servers. No databases. No API keys required (proxy optional). Just a repo that
updates itself.
