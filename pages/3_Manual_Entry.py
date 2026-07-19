from datetime import date, timedelta

import streamlit as st

from db import (
    init_db,
    get_or_create_week,
    upsert_manual_metrics,
    get_manual_metrics,
    upsert_stock_in_source,
    get_stock_in_sources,
    list_weeks,
    SITES,
    STOCK_SOURCES,
    IFCM_TRANSFER_SOURCE,
)

st.set_page_config(page_title="Manual Entry", layout="wide")
init_db()

st.markdown(
    "<style>[data-testid='stSidebarNav'] {display: none;}</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Navigate")
    st.page_link("app.py", label="📊 Dashboard")
    st.page_link("pages/1_Upload_Coal_Sales.py", label="📥 Upload Coal Sales Report")
    st.page_link("pages/2_Upload_Diesel_Report.py", label="⛽ Upload Diesel Report")
    st.page_link("pages/3_Manual_Entry.py", label="✍️ Manual Entry (BCM / Coal Mined)")
    st.page_link("pages/4_Settings.py", label="⚙️ Settings")

st.title("✍️ Manual Entry")
st.caption("Coal Mined and BCM Excavated aren't in the coal sales report, so enter them here each week.")

site = st.selectbox("Site", SITES)

existing = list_weeks(site)
mode = st.radio("Week", ["New / update a week", "Pick an existing week"], horizontal=True)

if mode == "Pick an existing week" and not existing.empty:
    options = {f"{r.label or r.week_start} ({r.week_start} to {r.week_end})": r for _, r in existing.iterrows()}
    choice = st.selectbox("Select week", list(options.keys()))
    row = options[choice]
    week_start, week_end, label = row.week_start, row.week_end, row.label
else:
    if mode == "Pick an existing week":
        st.info("No weeks recorded yet for this site — add one below.")
    c1, c2 = st.columns(2)
    with c1:
        week_start = st.date_input("Week start", value=date.today() - timedelta(days=date.today().weekday()))
    with c2:
        week_end = st.date_input("Week end", value=week_start + timedelta(days=6))
    label = st.text_input(
        "Label for this week (optional)",
        value=f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}",
    )

week_id = get_or_create_week(site, week_start, week_end, label)
current = get_manual_metrics(week_id)

st.subheader("Key metrics")
c1, c2 = st.columns(2)
with c1:
    coal_mined = st.number_input(
        "Coal mined (MT)",
        min_value=0.0,
        value=float(current[0]) if current and current[0] is not None else 0.0,
        step=1.0,
        format="%.2f",
    )
with c2:
    bcm_excavated = st.number_input(
        "BCM excavated (BCM)",
        min_value=0.0,
        value=float(current[1]) if current and current[1] is not None else 0.0,
        step=1.0,
        format="%.2f",
    )

if st.button("Save key metrics", type="primary"):
    upsert_manual_metrics(week_id, coal_mined, bcm_excavated)
    st.success(f"Saved for {site} — {label}.")

st.divider()

# TRCM receives coal transferred in from IFCM, so that source only makes
# sense as an input on TRCM's breakdown - IFCM can't receive coal from itself.
sources_for_site = STOCK_SOURCES + ([IFCM_TRANSFER_SOURCE] if site == "TRCM" else [])

with st.expander("Optional: Stock-in variance breakdown (by source)"):
    existing_sources = get_stock_in_sources(week_id)
    source_vals = {}
    cols = st.columns(len(sources_for_site))
    for i, src in enumerate(sources_for_site):
        prior = existing_sources[existing_sources.source == src]
        default = float(prior.iloc[0].qty_mt) if not prior.empty and prior.iloc[0].qty_mt is not None else 0.0
        source_vals[src] = cols[i].number_input(src, min_value=0.0, value=default, step=1.0, key=f"src_{src}")

    st.write(f"**Total: {sum(source_vals.values()):,.2f} MT**")
    if st.button("Save stock-in breakdown"):
        for src, qty in source_vals.items():
            upsert_stock_in_source(week_id, src, qty)
        st.success("Saved stock-in breakdown.")
