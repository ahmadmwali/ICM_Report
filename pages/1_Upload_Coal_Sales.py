from datetime import date, timedelta

import streamlit as st

from db import init_db, get_or_create_week, upsert_coal_stock, SITES, COAL_TYPES
from parsers import parse_coal_stock_report

st.set_page_config(page_title="Upload Coal Sales Report", layout="wide")
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

st.title("📥 Upload Weekly Coal Sales Report")
st.caption(
    "Reads the 'Stock Inventory' sheet (Opening Stock, Stock In, Stock Out, "
    "Stock Balance for Crushed Coal / Uncrushed Coal / Coal Dust) and saves it "
    "against the week you specify."
)

site = st.selectbox("Site", SITES)

c1, c2 = st.columns(2)
with c1:
    week_start = st.date_input("Week start", value=date.today() - timedelta(days=date.today().weekday()))
with c2:
    week_end = st.date_input("Week end", value=week_start + timedelta(days=6))

label = st.text_input(
    "Label for this week (optional, shown on the dashboard)",
    value=f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}",
)

uploaded = st.file_uploader("Coal sales report (.xlsx)", type=["xlsx"])

if uploaded is not None:
    try:
        parsed = parse_coal_stock_report(uploaded)
    except ValueError as e:
        st.error(str(e))
        parsed = None

    if parsed:
        st.success("Parsed successfully. Review before saving:")
        st.table(
            [
                {
                    "Coal Type": ct,
                    "Opening Stock": parsed[ct]["opening"],
                    "Stock In": parsed[ct]["stock_in"],
                    "Stock Out": parsed[ct]["stock_out"],
                    "Stock Balance": parsed[ct]["balance"],
                }
                for ct in COAL_TYPES
            ]
        )

        if st.button("Save to database", type="primary"):
            if week_end < week_start:
                st.error("Week end must be after week start.")
            else:
                week_id = get_or_create_week(site, week_start, week_end, label)
                for ct in COAL_TYPES:
                    row = parsed[ct]
                    upsert_coal_stock(
                        week_id, ct, row["opening"], row["stock_in"], row["stock_out"], row["balance"]
                    )
                st.success(f"Saved coal stock for {site} — {label}. Go to the Dashboard to see it.")
