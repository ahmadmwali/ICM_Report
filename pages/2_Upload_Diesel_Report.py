from datetime import date, timedelta

import streamlit as st

from db import (
    init_db,
    get_or_create_week,
    upsert_diesel_usage,
    set_operation_category,
    classify_operation,
    SITES,
)
from parsers import parse_diesel_pivot

st.set_page_config(page_title="Upload Diesel Report", layout="wide")
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

st.title("⛽ Upload Weekly Diesel Dispense Report")
st.caption(
    "Reads the diesel dispense pivot summary (operation type + total litres) and "
    "splits it into Haulage vs Non-Haulage using the mapping in Settings. "
    "New operation types default to a keyword guess — correct them below if needed."
)

site = st.selectbox("Site", SITES)

c1, c2 = st.columns(2)
with c1:
    week_start = st.date_input("Week start", value=date.today() - timedelta(days=date.today().weekday()), key="ds_start")
with c2:
    week_end = st.date_input("Week end", value=week_start + timedelta(days=6), key="ds_end")

label = st.text_input(
    "Label for this week (optional)",
    value=f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}",
    key="ds_label",
)

uploaded = st.file_uploader("Diesel dispense report (.xlsx)", type=["xlsx"])

if uploaded is not None:
    try:
        pivot_df = parse_diesel_pivot(uploaded)
    except ValueError as e:
        st.error(str(e))
        pivot_df = None

    if pivot_df is not None:
        st.success(f"Found {len(pivot_df)} operation types. Confirm the Haulage / Non-Haulage split:")

        edited_rows = []
        for _, row in pivot_df.iterrows():
            default_cat = classify_operation(site, row["operation_type"])
            col_a, col_b, col_c = st.columns([3, 2, 2])
            col_a.write(row["operation_type"])
            col_b.write(f"{row['total_litres']:,.0f} L")
            cat = col_c.selectbox(
                "Category",
                ["Haulage", "Non-Haulage"],
                index=0 if default_cat == "Haulage" else 1,
                key=f"cat_{row['operation_type']}",
                label_visibility="collapsed",
            )
            edited_rows.append({"operation_type": row["operation_type"], "total_litres": row["total_litres"], "category": cat})

        haulage_total = sum(r["total_litres"] for r in edited_rows if r["category"] == "Haulage")
        non_haulage_total = sum(r["total_litres"] for r in edited_rows if r["category"] == "Non-Haulage")

        st.divider()
        m1, m2 = st.columns(2)
        m1.metric("Diesel on Haulage activities (L)", f"{haulage_total:,.0f}")
        m2.metric("Diesel without Haulage activities (L)", f"{non_haulage_total:,.0f}")

        remember = st.checkbox(
            "Remember these category choices for next time (updates the mapping in Settings)",
            value=True,
        )

        if st.button("Save to database", type="primary"):
            if week_end < week_start:
                st.error("Week end must be after week start.")
            else:
                week_id = get_or_create_week(site, week_start, week_end, label)
                detail = {r["operation_type"]: r["category"] for r in edited_rows}
                upsert_diesel_usage(week_id, haulage_total, non_haulage_total, detail)
                if remember:
                    for r in edited_rows:
                        set_operation_category(site, r["operation_type"], r["category"])
                st.success(f"Saved diesel usage for {site} — {label}. Go to the Dashboard to see it.")
