# ICM Weekly Report Dashboard (IFCM & TRCM)

A Streamlit app that automates your weekly ICM report for both sites, backed
by a Neon (serverless Postgres) database. It reads your existing Weekly Coal
Sales Report and Diesel Dispense Report workbooks, combines them with two
manually entered figures (Coal Mined and BCM Excavated — not present in
those reports), and shows a **variance-only dashboard**: this week vs last
week, for each site.

## What it does

- **Upload Coal Sales Report** — reads the "Stock Inventory" sheet (Opening
  Stock / Stock In / Stock Out / Stock Balance for Crushed Coal, Uncrushed
  Coal, Coal Dust) and saves it against a week you pick.
- **Upload Diesel Report** — reads the pivot summary (operation type + total
  litres) from a diesel dispense workbook and splits it into "Diesel on
  Haulage activities" vs "Diesel without Haulage Activities", using an
  editable per-site mapping (Settings page). You confirm the split before
  saving, and can save your choices so next week's report auto-classifies.
- **Manual Entry** — enter Coal Mined (MT) and BCM Excavated (BCM) for a
  site/week (these aren't in the coal sales or diesel reports). Optional
  section for the Stock-In source breakdown (Pit / Local Miners / Manejo /
  Ogboyaga / High Wall Mining) if you want to track that too.
- **Dashboard** — for each site, compares the two most recent weeks on file
  and shows only the variance (this week − last week) and % change, for
  every metric: Coal Mined, BCM Excavated, Diesel (Haulage / Non-Haulage),
  and Opening/In/Out/Balance for each coal type.

## Setup

1. **Create a Neon project** at https://neon.tech (free tier is enough to
   start) and copy its connection string.
2. **Configure the connection string.** Either:
   - Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and
     paste your connection string in, or
   - Set an environment variable `DATABASE_URL` before running the app.
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run it:**
   ```bash
   streamlit run app.py
   ```

Tables are created automatically on first run — there's no separate
migration step.

## Notes on the automated parsing

- The Coal Sales Report parser expects the "Stock Inventory" sheet with
  Crushed Coal / Uncrushed Coal / Coal Dust in rows 7–9 (Opening Stock in
  column E, Stock In in H, Stock Out in J, Balance in L) — this matches
  the layout of the files you shared. If a supplier changes that layout,
  the parser will raise a clear error rather than save wrong numbers.
- The Diesel Report parser looks for any sheet with a "Row Labels" pivot
  table and reads the row totals (it handles both the single-total-column
  layout used by TRCM and the per-day-columns-plus-Grand-Total layout used
  in the IFCM template).
- Every upload shows you a preview before it's saved — nothing is written
  to the database silently.

## Extending it

- `db.py` has all the schema and query logic in one place.
- `parsers.py` has the two Excel parsers. If a report layout changes,
  update it there.
- To add a new metric to the variance dashboard, add it to
  `get_full_week_report()` in `db.py` — it will automatically show up in
  `build_variance_table()` and on the dashboard.
