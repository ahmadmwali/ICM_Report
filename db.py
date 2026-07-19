"""
Database layer for the ICM Weekly Report Dashboard.

Backend: Neon (serverless Postgres). Connection string is read from
Streamlit secrets (`DATABASE_URL`) or the `DATABASE_URL` environment
variable, so the same code works locally and when deployed.

All tables are created automatically on first run (CREATE TABLE IF NOT
EXISTS), so there is no separate migration step to run by hand.
"""

import os
from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SITES = ["IFCM", "TRCM"]
COAL_TYPES = ["Crushed Coal", "Uncrushed Coal", "Coal Dust"]
STOCK_SOURCES = [
    "Coal from Pit",
    "Coal from Local Miners",
    "Coal from Manejo",
    "Coal from Ogboyaga",
    "Coal from High Wall Mining",
]
# TRCM-only source: coal transferred in from IFCM. Kept out of STOCK_SOURCES
# so it never shows up as an input/KPI for IFCM (which can't receive coal
# from itself); TRCM-specific screens add it in explicitly.
IFCM_TRANSFER_SOURCE = "Coal from IFCM"

# Default keyword-based classification for diesel operation types.
# Anything containing one of these substrings (case-insensitive) is treated
# as a "Haulage" activity. Editable per-site in the Settings page, which
# overrides / extends this default.
DEFAULT_HAULAGE_KEYWORDS = ["haulage", "trip to", "trailer"]


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    conn_str = None
    try:
        conn_str = st.secrets["DATABASE_URL"]
    except Exception:
        conn_str = os.environ.get("DATABASE_URL")

    if not conn_str:
        st.error(
            "No database connection configured. Add DATABASE_URL to "
            "`.streamlit/secrets.toml` (or as an environment variable) "
            "with your Neon connection string, e.g.\n\n"
            "postgresql://user:password@ep-xxxx.neon.tech/dbname?sslmode=require"
        )
        st.stop()

    # Neon sometimes hands out "postgres://" URLs; SQLAlchemy wants "postgresql://"
    if conn_str.startswith("postgres://"):
        conn_str = conn_str.replace("postgres://", "postgresql://", 1)

    engine = create_engine(conn_str, pool_pre_ping=True, pool_recycle=300)
    return engine


DDL = """
CREATE TABLE IF NOT EXISTS weeks (
    id SERIAL PRIMARY KEY,
    site TEXT NOT NULL,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    label TEXT,
    UNIQUE (site, week_start)
);

CREATE TABLE IF NOT EXISTS manual_metrics (
    week_id INTEGER PRIMARY KEY REFERENCES weeks(id) ON DELETE CASCADE,
    site TEXT,
    coal_mined_mt NUMERIC,
    bcm_excavated NUMERIC,
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coal_stock (
    week_id INTEGER REFERENCES weeks(id) ON DELETE CASCADE,
    site TEXT,
    coal_type TEXT NOT NULL,
    opening_stock NUMERIC,
    stock_in NUMERIC,
    stock_out NUMERIC,
    stock_balance NUMERIC,
    PRIMARY KEY (week_id, coal_type)
);

CREATE TABLE IF NOT EXISTS diesel_usage (
    week_id INTEGER PRIMARY KEY REFERENCES weeks(id) ON DELETE CASCADE,
    site TEXT,
    diesel_haulage NUMERIC,
    diesel_non_haulage NUMERIC,
    source_detail JSONB
);

CREATE TABLE IF NOT EXISTS stock_in_sources (
    week_id INTEGER REFERENCES weeks(id) ON DELETE CASCADE,
    site TEXT,
    source TEXT NOT NULL,
    qty_mt NUMERIC,
    PRIMARY KEY (week_id, source)
);

CREATE TABLE IF NOT EXISTS operation_type_map (
    site TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('Haulage', 'Non-Haulage')),
    PRIMARY KEY (site, operation_type)
);
"""

# Run against databases created before the `site` columns existed on the
# child tables (safe / idempotent - adds the column and backfills it from
# `weeks` if it's missing, does nothing otherwise).
MIGRATIONS = """
ALTER TABLE manual_metrics ADD COLUMN IF NOT EXISTS site TEXT;
ALTER TABLE coal_stock ADD COLUMN IF NOT EXISTS site TEXT;
ALTER TABLE diesel_usage ADD COLUMN IF NOT EXISTS site TEXT;
ALTER TABLE stock_in_sources ADD COLUMN IF NOT EXISTS site TEXT;

UPDATE manual_metrics m SET site = w.site FROM weeks w WHERE m.week_id = w.id AND m.site IS NULL;
UPDATE coal_stock c SET site = w.site FROM weeks w WHERE c.week_id = w.id AND c.site IS NULL;
UPDATE diesel_usage d SET site = w.site FROM weeks w WHERE d.week_id = w.id AND d.site IS NULL;
UPDATE stock_in_sources s SET site = w.site FROM weeks w WHERE s.week_id = w.id AND s.site IS NULL;
"""


def init_db():
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";\n\n"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt + ";"))
        for stmt in MIGRATIONS.strip().splitlines():
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))


def get_week_site(week_id: int) -> str:
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("SELECT site FROM weeks WHERE id = :wid"), {"wid": week_id}).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Weeks
# ---------------------------------------------------------------------------

def get_or_create_week(site: str, week_start: date, week_end: date, label: str = None) -> int:
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM weeks WHERE site = :site AND week_start = :ws"),
            {"site": site, "ws": week_start},
        ).fetchone()
        if row:
            if label:
                conn.execute(
                    text("UPDATE weeks SET label = :label, week_end = :we WHERE id = :id"),
                    {"label": label, "we": week_end, "id": row[0]},
                )
            return row[0]
        result = conn.execute(
            text(
                "INSERT INTO weeks (site, week_start, week_end, label) "
                "VALUES (:site, :ws, :we, :label) RETURNING id"
            ),
            {"site": site, "ws": week_start, "we": week_end, "label": label},
        )
        return result.fetchone()[0]


def list_weeks(site: str) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        text("SELECT * FROM weeks WHERE site = :site ORDER BY week_start"),
        engine,
        params={"site": site},
    )


def latest_two_weeks(site: str) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        text(
            "SELECT * FROM weeks WHERE site = :site "
            "ORDER BY week_start DESC LIMIT 2"
        ),
        engine,
        params={"site": site},
    )


# ---------------------------------------------------------------------------
# Manual metrics (coal mined, BCM excavated)
# ---------------------------------------------------------------------------

def upsert_manual_metrics(week_id: int, coal_mined_mt: float, bcm_excavated: float):
    engine = get_engine()
    site = get_week_site(week_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO manual_metrics (week_id, site, coal_mined_mt, bcm_excavated, updated_at)
                VALUES (:wid, :site, :cm, :bcm, now())
                ON CONFLICT (week_id) DO UPDATE
                SET site = EXCLUDED.site,
                    coal_mined_mt = EXCLUDED.coal_mined_mt,
                    bcm_excavated = EXCLUDED.bcm_excavated,
                    updated_at = now()
                """
            ),
            {"wid": week_id, "site": site, "cm": coal_mined_mt, "bcm": bcm_excavated},
        )


def get_manual_metrics(week_id: int):
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT coal_mined_mt, bcm_excavated FROM manual_metrics WHERE week_id = :wid"),
            {"wid": week_id},
        ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Coal stock (from coal sales report upload)
# ---------------------------------------------------------------------------

def upsert_coal_stock(week_id: int, coal_type: str, opening: float, stock_in: float,
                       stock_out: float, balance: float):
    engine = get_engine()
    site = get_week_site(week_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO coal_stock (week_id, site, coal_type, opening_stock, stock_in, stock_out, stock_balance)
                VALUES (:wid, :site, :ct, :op, :si, :so, :bal)
                ON CONFLICT (week_id, coal_type) DO UPDATE
                SET site = EXCLUDED.site,
                    opening_stock = EXCLUDED.opening_stock,
                    stock_in = EXCLUDED.stock_in,
                    stock_out = EXCLUDED.stock_out,
                    stock_balance = EXCLUDED.stock_balance
                """
            ),
            {"wid": week_id, "site": site, "ct": coal_type, "op": opening, "si": stock_in, "so": stock_out, "bal": balance},
        )


def get_coal_stock(week_id: int) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        text("SELECT * FROM coal_stock WHERE week_id = :wid"),
        engine,
        params={"wid": week_id},
    )


# ---------------------------------------------------------------------------
# Diesel usage (from diesel dispense report upload)
# ---------------------------------------------------------------------------

def upsert_diesel_usage(week_id: int, haulage: float, non_haulage: float, source_detail: dict):
    import json
    engine = get_engine()
    site = get_week_site(week_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO diesel_usage (week_id, site, diesel_haulage, diesel_non_haulage, source_detail)
                VALUES (:wid, :site, :h, :nh, :detail)
                ON CONFLICT (week_id) DO UPDATE
                SET site = EXCLUDED.site,
                    diesel_haulage = EXCLUDED.diesel_haulage,
                    diesel_non_haulage = EXCLUDED.diesel_non_haulage,
                    source_detail = EXCLUDED.source_detail
                """
            ),
            {"wid": week_id, "site": site, "h": haulage, "nh": non_haulage, "detail": json.dumps(source_detail)},
        )


def get_diesel_usage(week_id: int):
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT diesel_haulage, diesel_non_haulage FROM diesel_usage WHERE week_id = :wid"),
            {"wid": week_id},
        ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Stock-in sources (optional manual breakdown: Pit / Local Miners / etc.)
# ---------------------------------------------------------------------------

def upsert_stock_in_source(week_id: int, source: str, qty_mt: float):
    engine = get_engine()
    site = get_week_site(week_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO stock_in_sources (week_id, site, source, qty_mt)
                VALUES (:wid, :site, :src, :qty)
                ON CONFLICT (week_id, source) DO UPDATE
                SET site = EXCLUDED.site, qty_mt = EXCLUDED.qty_mt
                """
            ),
            {"wid": week_id, "site": site, "src": source, "qty": qty_mt},
        )


def get_stock_in_sources(week_id: int) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        text("SELECT * FROM stock_in_sources WHERE week_id = :wid"),
        engine,
        params={"wid": week_id},
    )


# ---------------------------------------------------------------------------
# Operation type -> Haulage / Non-Haulage mapping (per site, editable)
# ---------------------------------------------------------------------------

def get_operation_map(site: str) -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        text("SELECT * FROM operation_type_map WHERE site = :site ORDER BY operation_type"),
        engine,
        params={"site": site},
    )


def set_operation_category(site: str, operation_type: str, category: str):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO operation_type_map (site, operation_type, category)
                VALUES (:site, :op, :cat)
                ON CONFLICT (site, operation_type) DO UPDATE SET category = EXCLUDED.category
                """
            ),
            {"site": site, "op": operation_type, "cat": category},
        )


def classify_operation(site: str, operation_type: str) -> str:
    """Look up a saved mapping; fall back to keyword heuristics; default Non-Haulage."""
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT category FROM operation_type_map WHERE site = :site AND operation_type = :op"
            ),
            {"site": site, "op": operation_type},
        ).fetchone()
    if row:
        return row[0]
    low = (operation_type or "").lower()
    if any(k in low for k in DEFAULT_HAULAGE_KEYWORDS):
        return "Haulage"
    return "Non-Haulage"


# ---------------------------------------------------------------------------
# Full weekly report (assembled) + variance
# ---------------------------------------------------------------------------

def get_full_week_report(week_id: int) -> dict:
    """Bundle manual metrics + diesel + coal stock for one week into a flat dict
    of metric -> value, matching the layout of the original spreadsheets."""
    out = {}
    mm = get_manual_metrics(week_id)
    out["Coal mined (MT)"] = float(mm[0]) if mm and mm[0] is not None else None
    out["Bcm excavated (BCM)"] = float(mm[1]) if mm and mm[1] is not None else None

    du = get_diesel_usage(week_id)
    out["Diesel on Haulage activities (Litres)"] = float(du[0]) if du and du[0] is not None else None
    out["Diesel without Haulage Activities (Litres)"] = float(du[1]) if du and du[1] is not None else None

    stock = get_coal_stock(week_id)
    for ct in COAL_TYPES:
        r = stock[stock.coal_type == ct]
        if not r.empty:
            row = r.iloc[0]
            out[f"{ct} - Opening Stock"] = float(row.opening_stock) if row.opening_stock is not None else None
            out[f"{ct} - Stock In"] = float(row.stock_in) if row.stock_in is not None else None
            out[f"{ct} - Stock Out"] = float(row.stock_out) if row.stock_out is not None else None
            out[f"{ct} - Stock Balance"] = float(row.stock_balance) if row.stock_balance is not None else None
        else:
            for suffix in ["Opening Stock", "Stock In", "Stock Out", "Stock Balance"]:
                out[f"{ct} - {suffix}"] = None

    src = get_stock_in_sources(week_id)
    for s in STOCK_SOURCES + [IFCM_TRANSFER_SOURCE]:
        r = src[src.source == s]
        out[s] = float(r.iloc[0].qty_mt) if not r.empty and r.iloc[0].qty_mt is not None else None

    return out


def build_variance_table(site: str) -> pd.DataFrame:
    """Return a DataFrame: metric | this_week | last_week | variance | pct_change
    comparing the two most recent weeks on file for a site."""
    weeks = latest_two_weeks(site)
    if len(weeks) < 2:
        return pd.DataFrame(), weeks

    this_week = weeks.iloc[0]
    last_week = weeks.iloc[1]

    this_vals = get_full_week_report(int(this_week.id))
    last_vals = get_full_week_report(int(last_week.id))

    rows = []
    for metric in this_vals:
        tv = this_vals.get(metric)
        lv = last_vals.get(metric)
        if tv is None and lv is None:
            continue
        variance = None
        pct = None
        if tv is not None and lv is not None:
            variance = tv - lv
            pct = (variance / lv * 100) if lv not in (0, None) else None
        rows.append(
            {
                "Metric": metric,
                f"This Week ({this_week.label or this_week.week_start})": tv,
                f"Last Week ({last_week.label or last_week.week_start})": lv,
                "Variance": variance,
                "% Change": pct,
            }
        )
    return pd.DataFrame(rows), weeks
