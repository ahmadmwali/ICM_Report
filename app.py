import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from db import init_db, latest_two_weeks, get_full_week_report, COAL_TYPES, SITES, IFCM_TRANSFER_SOURCE

st.set_page_config(page_title="ICM Weekly Report Dashboard", layout="wide")
init_db()

# Hide Streamlit's auto-generated page list at the top of the sidebar -
# we render our own labeled "Navigate" list below instead, so having both
# just duplicates the same links.
st.markdown(
    "<style>[data-testid='stSidebarNav'] {display: none;}</style>",
    unsafe_allow_html=True,
)

st.title("ICM Weekly Report Dashboard")
st.caption("Automated weekly ICM reports for IFCM and TRCM — this week vs last week.")

with st.sidebar:
    st.header("Navigate")
    st.page_link("app.py", label="📊 Dashboard")
    st.page_link("pages/1_Upload_Coal_Sales.py", label="📥 Upload Coal Sales Report")
    st.page_link("pages/2_Upload_Diesel_Report.py", label="⛽ Upload Diesel Report")
    st.page_link("pages/3_Manual_Entry.py", label="✍️ Manual Entry (BCM / Coal Mined)")
    st.page_link("pages/4_Settings.py", label="⚙️ Settings")

KPI_METRICS = [
    ("Coal mined (MT)", "MT"),
    ("Bcm excavated (BCM)", "BCM"),
    ("Diesel on Haulage activities (Litres)", "L"),
    ("Diesel without Haulage Activities (Litres)", "L"),
]

STOCK_MEASURES = ["Opening Stock", "Stock In", "Stock Out", "Stock Balance"]

# Higher-contrast pair: deep blue (this week) vs amber (last week) - distinct
# in hue as well as lightness, so the two weeks stay easy to tell apart.
BAR_THIS_WEEK = "#1d4ed8"   # deep blue
BAR_LAST_WEEK = "#f59e0b"   # amber


def render_kpi_cards(this_vals: dict, last_vals: dict, metrics: list = None):
    metrics = metrics if metrics is not None else KPI_METRICS
    cols = st.columns(len(metrics))
    for col, (metric, unit) in zip(cols, metrics):
        tv, lv = this_vals.get(metric), last_vals.get(metric)
        if tv is None and lv is None:
            col.metric(metric.split(" (")[0], "no data")
            continue
        delta = None
        if tv is not None and lv is not None:
            delta = tv - lv
        col.metric(
            metric.split(" (")[0],
            f"{tv:,.1f} {unit}" if tv is not None else "—",
            delta=f"{delta:+,.1f} {unit}" if delta is not None else None,
        )


def render_coal_stock_chart(this_vals: dict, last_vals: dict, this_label: str, last_label: str):
    fig = make_subplots(rows=1, cols=3, subplot_titles=COAL_TYPES, shared_yaxes=False)
    has_any_data = False
    for i, ct in enumerate(COAL_TYPES, start=1):
        this_row = [this_vals.get(f"{ct} - {m}") for m in STOCK_MEASURES]
        last_row = [last_vals.get(f"{ct} - {m}") for m in STOCK_MEASURES]
        if any(v is not None for v in this_row + last_row):
            has_any_data = True
        fig.add_trace(
            go.Bar(
                x=STOCK_MEASURES, y=last_row, name=last_label,
                marker_color=BAR_LAST_WEEK, legendgroup="last",
                showlegend=(i == 1),
            ),
            row=1, col=i,
        )
        fig.add_trace(
            go.Bar(
                x=STOCK_MEASURES, y=this_row, name=this_label,
                marker_color=BAR_THIS_WEEK, legendgroup="this",
                showlegend=(i == 1),
                text=[
                    (f"{v-l:+,.1f}" if v is not None and l is not None else "")
                    for v, l in zip(this_row, last_row)
                ],
                textposition="outside",
            ),
            row=1, col=i,
        )

    if not has_any_data:
        return None

    fig.update_layout(
        barmode="group",
        height=360,
        margin=dict(t=50, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.08, xanchor="center", x=0.5),
        template="plotly_white",
    )
    return fig


def render_site(site: str):
    st.subheader(site)
    weeks = latest_two_weeks(site)

    if len(weeks) == 0:
        st.info(f"No weeks recorded yet for {site}. Upload a coal sales report or add a manual entry.")
        return
    if len(weeks) == 1:
        st.info(
            f"Only one week on file for {site} "
            f"({weeks.iloc[0].label or weeks.iloc[0].week_start}). "
            "Add a second week to see a comparison."
        )
        return

    this_week, last_week = weeks.iloc[0], weeks.iloc[1]
    this_label = str(this_week.label or this_week.week_start)
    last_label = str(last_week.label or last_week.week_start)
    st.caption(f"**This week:** {this_label}  ·  **Last week:** {last_label}")

    this_vals = get_full_week_report(int(this_week.id))
    last_vals = get_full_week_report(int(last_week.id))

    site_metrics = list(KPI_METRICS)
    if site == "TRCM":
        site_metrics = site_metrics + [(IFCM_TRANSFER_SOURCE, "MT")]

    render_kpi_cards(this_vals, last_vals, site_metrics)

    fig = render_coal_stock_chart(this_vals, last_vals, this_label, last_label)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, key=f"stock_chart_{site}")
    else:
        st.caption("No coal stock data uploaded yet for these two weeks.")


col1, col2 = st.columns(2)
with col1:
    render_site("IFCM")
with col2:
    render_site("TRCM")

st.divider()
st.caption(
    "Bars show Opening/In/Out/Balance stock by coal type (light = last week, "
    "dark = this week); labels above the dark bars are the variance. "
    "KPI cards show this week's value with the change vs last week."
)
