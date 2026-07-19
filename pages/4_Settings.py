import streamlit as st

from db import init_db, get_operation_map, set_operation_category, SITES

st.set_page_config(page_title="Settings", layout="wide")
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

st.title("⚙️ Settings")

st.subheader("Diesel operation-type mapping")
st.caption(
    "Controls which operation types count as 'Haulage' vs 'Non-Haulage' when a "
    "diesel report is uploaded. New/unseen operation types default to a keyword "
    "guess (containing 'haulage', 'trip to', or 'trailer' → Haulage) until you "
    "confirm them on the upload page."
)

site = st.selectbox("Site", SITES)
mapping = get_operation_map(site)

if mapping.empty:
    st.info("No operation types saved yet for this site — upload a diesel report first, or add one manually below.")
else:
    st.dataframe(mapping[["operation_type", "category"]], use_container_width=True, hide_index=True)

st.divider()
st.subheader("Add / update a mapping manually")
c1, c2, c3 = st.columns([3, 2, 1])
with c1:
    op_type = st.text_input("Operation type (exact text as it appears in the report)")
with c2:
    cat = st.selectbox("Category", ["Haulage", "Non-Haulage"])
with c3:
    st.write("")
    st.write("")
    if st.button("Save mapping"):
        if op_type.strip():
            set_operation_category(site, op_type.strip(), cat)
            st.success(f"Saved: {op_type} → {cat}")
            st.rerun()
        else:
            st.warning("Enter an operation type first.")
