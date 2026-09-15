# AI Spending Detective

An autonomous AI agent that reads a bank statement, categorizes and audits every transaction, and shows the results on a live dashboard with an interactive spending map — no manual transaction entry required.

Built to practice AI agent design (tool-use / structured LLM output), Python, and database-backed data pipelines, with a live Streamlit dashboard and geospatial visualization on top.

## What it does

1. **Import** — upload a bank statement (CSV, or PDF), or generate a realistic month of synthetic data with one click. Either way, transactions land in the database raw and uncategorized, exactly like a real statement import.
2. **Audit** — an AI agent (Claude, via structured tool-use) reads every transaction in the month at once, assigns a spending category, and flags genuine anomalies: subscription creep (3+ overlapping recurring services), same-day duplicate charges, and unusually large one-off spends. Every decision is logged with the agent's reasoning, not just the result.
3. **Visualize** — a live dashboard shows cash flow over time, spending by category, budget health against limits you set, the flagged anomalies, and an interactive map of where the money went.

## Screenshots

Run it yourself with `streamlit run app.py` — see **Quickstart** below. (Demo data included, no real bank account needed.)

## Why these design decisions

- **The agent processes a full month in a single call**, not small batches. An earlier version batched 20 transactions at a time and missed real subscription creep because the overlapping subscriptions landed in different batches — the agent literally couldn't see them together. Full-month context fixed it.
- **The anomaly-detection prompt is deliberately conservative.** An early version flagged 32% of transactions as "anomalies" simply because repeat visits to the same grocery store or shop are normal, not suspicious. Tightening the criteria (same-day duplicates, 3+ overlapping subscriptions, 3x+ outlier spends only) brought that down to ~1% — a believable rate.
- **Categorization happens with zero manual data entry.** The only human input is uploading a statement file (or, optionally, a receipt photo for cash purchases) — not typing in every transaction by hand.
- **SQLite + SQLAlchemy, not a hosted database.** Zero setup for anyone cloning the repo, while the ORM layer means the schema/queries would carry over to Postgres largely unchanged if this ever needed to scale.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python |
| Database | SQLite via SQLAlchemy ORM |
| AI agent | Anthropic Claude API (tool-use for structured output) |
| Dashboard | Streamlit |
| Charts | Plotly |
| Map | Streamlit's native `st.map` (Carto basemap) |
| Statement parsing | pandas (CSV), pdfplumber (PDF) |

## Project structure

```
ai-spending-detective/
├── app.py                  # Streamlit dashboard (entry point)
├── src/
│   ├── models.py            # SQLAlchemy schema: categories, transactions, budgets, agent_actions
│   ├── db.py                 # Database engine/session setup
│   ├── synthetic_data.py     # Realistic demo data generator
│   ├── agent.py               # The AI categorization/anomaly-detection agent
│   └── ingest.py               # Bank statement (CSV/PDF) import pipeline
├── data/                    # SQLite database lives here (gitignored)
├── requirements.txt
└── .env.example             # Copy to .env and add your Anthropic API key
```

## Quickstart

```bash
git clone <this-repo-url>
cd ai-spending-detective
python -m venv venv
venv\Scripts\activate        # Windows — use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env       # then add your Anthropic API key (console.anthropic.com)
streamlit run app.py
```

Then in the browser: click **"Generate demo month (synthetic)"** in the sidebar, then **"Run AI agent"** — the whole pipeline runs against realistic fake data in seconds. To use real data instead, upload a bank CSV export.

## Known limitations / future work

- **PDF import is implemented but not verified against a real bank statement.** Bank PDF layouts vary a lot; the column-matching logic in `src/ingest.py` may need adjusting for a specific bank's format.
- **No live bank account sync** (Plaid-style open banking) — needs commercial API access not realistic for a personal project. Manual statement export/upload is the supported path.
- **Single currency (SGD)** assumed throughout.
- Receipt-photo OCR for cash transactions is a natural next feature, reusing computer-vision experience from other projects in this portfolio.

## Build log

- **Stage 1 — Project setup:** folder structure, dependencies, git.
- **Stage 2 — Database schema:** `categories`, `transactions`, `budgets`, `agent_actions` tables via SQLAlchemy (`src/models.py`, `src/db.py`).
- **Stage 3 — Synthetic data generator:** `src/synthetic_data.py` produces a realistic month of Singapore transactions (real merchant names, locations, a salary deposit, injected subscription-creep anomalies) for demoing without real bank data. Recurring merchants (subscriptions/bills) are added once a month rather than drawn daily, so patterns stay realistic.
- **Stage 4 — AI categorization agent:** `src/agent.py` uses Claude (tool-use for structured output) to categorize every transaction and flag genuine anomalies, logging its reasoning to `agent_actions`. Processes a full month in one call so it can compare transactions against each other (needed to catch things like subscription creep). Tuned down from an initial 32% false-positive anomaly rate to ~1% by tightening the anomaly criteria in the prompt.
- **Stage 5 — Statement import:** `src/ingest.py` recognizes common bank CSV column layouts (signed Amount, or separate Debit/Credit) and produces raw uncategorized transactions, same shape as the synthetic data. Verified against two realistic CSV formats. PDF import (`import_pdf`) is implemented via `pdfplumber` table extraction but not yet verified against a real bank statement — needs testing once a real PDF is available.
- **Stage 6 — Live dashboard:** `app.py` (Streamlit) — KPI tiles, cash-flow chart, category breakdown, budget gauges (with an in-app budget-setting form), a flagged-anomalies table, and the agent's activity feed. Sidebar drives everything: upload a statement, generate demo data, or run the AI agent. Verified running live in browser at `localhost:8501`. Fixed a `DetachedInstanceError` from closing the DB session before reading transaction categories.
- **Stage 7 — Spending map:** transactions plotted on a real Singapore map via `st.map`, color-coded by category with a legend, dot size scaled by amount. Initially tried `pydeck` directly but its basemap silently failed to load inside Streamlit's iframe (no tile requests fired at all — not a network issue, an integration one); switched to Streamlit's native `st.map`, which renders the basemap reliably.
- **Stage 8 — Polish:** portfolio-ready README, verified `requirements.txt` covers every import, documented known limitations honestly rather than glossing over them.
- **Post-launch refinements (from user feedback after a walkthrough):** added a "Daily net cash flow" bar chart with plain-language captions on every chart explaining what it shows; switched the map from `st.map` to `px.scatter_mapbox` (still free/tokenless, via `mapbox_style="open-street-map"`) so it supports proper hover tooltips (merchant, amount, category, location) instead of just colored dots.
- **Stage 9 — AI budget recommendation:** `recommend_budgets()` in `src/agent.py` analyzes one month's actual income and per-category spending, then acts like a financial advisor to recommend next month's budget — keeping essential categories (groceries, utilities, transport) close to actual, trimming discretionary ones (shopping, dining) when spending outpaced income. Saves straight into the `budgets` table and displays an actual-vs-recommended comparison table and chart. Hit and fixed a real bug: Streamlit's markdown renderer treats text between two `$` signs as LaTeX math, so a reasoning string with two dollar amounts (e.g. "$3,899.63 ... $2,200") rendered as garbled math notation instead of plain text — fixed with a `md_safe()` helper that escapes `$` before display, applied everywhere AI-generated reasoning is shown.
