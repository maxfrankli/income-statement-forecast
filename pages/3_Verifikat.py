# 3_Verifikat.py
from typing import Tuple
import streamlit as st
import pandas as pd

from tools.sie4_parser import SIE4Parser

st.set_page_config(page_title="SIE4 – Verifikat", layout="wide")
st.title("SIE4 – Verifikatvy")

st.markdown(
    "Ladda upp en **SIE4-fil** så visas alla verifikat i tabellen nedan. "
    "Parser: `tools/sie4_parser.py`."
)

@st.cache_data(show_spinner=True)
def parse_sie_bytes(file_bytes: bytes) -> Tuple[object, pd.DataFrame, pd.DataFrame]:
    """
    Cachead parsning. Tar bytes -> Company + två DataFrames (verifikat & transaktioner).
    """
    parser = SIE4Parser(infer_account_hierarchy=True)
    company = parser.parse_bytes(file_bytes, encoding_candidates=("cp865",))

    df_vouchers = company.to_pandas_vouchers()
    df_tx = company.to_pandas_transactions()

    # Snygga kolumnnamn
    if not df_vouchers.empty:
        df_vouchers = df_vouchers.rename(
            columns={
                "series": "Serie",
                "number": "Nr",
                "date": "Datum",
                "text": "Text",
                "reg_date": "Registreringsdatum",
                "n_transactions": "Antal transaktioner",
            }
        ).sort_values(["Datum", "Serie", "Nr"])

    if not df_tx.empty:
        df_tx = df_tx.rename(
            columns={
                "series": "Serie",
                "number": "Nr",
                "voucher_date": "Datum",
                "voucher_text": "Verifikattext",
                "tx_index": "Rad",
                "account": "Konto",
                "amount": "Belopp",
                "dim": "Dimensioner",
                "text": "Transaktionstext",
                "month": "Månad",
            }
        ).sort_values(["Datum", "Serie", "Nr", "Rad"])

    return company, df_vouchers, df_tx


uploaded = st.file_uploader("Ladda upp SIE4-fil", type=["se","sie", "SIE", "txt"])
if not uploaded:
    st.info("🛈 Välj en SIE4-fil för att börja.")
    st.stop()

try:
    file_bytes = uploaded.getvalue()  # stabilt för caching
    company, df_vouchers, df_tx = parse_sie_bytes(file_bytes)
    st.caption(f"Filkodning: {company.source_encoding or 'okänd'}")
except Exception as e:
    st.error(f"Kunde inte läsa SIE-filen: {e}")
    st.stop()

# Topprad med företagsinfo
with st.container():
    cols = st.columns(4)
    cols[0].metric("Företag", company.name or "Okänt")
    cols[1].metric("Org.nr", company.orgnr or "—")
    cols[2].metric("Antal verifikat", len(df_vouchers) if df_vouchers is not None else 0)
    cols[3].metric("Antal transaktioner", len(df_tx) if df_tx is not None else 0)

st.divider()

# --- Verifikatlista + filter ---
if df_vouchers.empty:
    st.warning("Inga verifikat hittades i filen.")
    st.stop()

min_date = pd.to_datetime(df_vouchers["Datum"]).min().date()
max_date = pd.to_datetime(df_vouchers["Datum"]).max().date()
all_series = sorted([s for s in df_vouchers["Serie"].dropna().unique()])

c1, c2, c3 = st.columns([1.2, 1.2, 2.2])
date_range = c1.date_input("Datumintervall", (min_date, max_date))
selected_series = c2.multiselect("Serier", all_series, default=all_series)
search_text = c3.text_input("Fritext (matchar Text)", "")

dfv = df_vouchers.copy()
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
    dfv = dfv[(pd.to_datetime(dfv["Datum"]) >= start) & (pd.to_datetime(dfv["Datum"]) <= end)]
if selected_series:
    dfv = dfv[dfv["Serie"].isin(selected_series)]
if search_text.strip():
    dfv = dfv[dfv["Text"].str.contains(search_text, case=False, na=False)]

st.subheader("Verifikat")
st.dataframe(dfv, hide_index=True, width='stretch')

csv_v = dfv.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Ladda ner verifikat (CSV)",
    data=csv_v,
    file_name="verifikat.csv",
    mime="text/csv",
    width='stretch',
)

st.divider()

# --- Transaktioner (drill-down, följer verifikatfilter) ---
st.subheader("Transaktioner (matchar filtren ovan)")
if df_tx is None or df_tx.empty:
    st.info("Inga transaktioner att visa.")
else:
    dft = df_tx.copy()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        dft = dft[(pd.to_datetime(dft["Datum"]) >= start) & (pd.to_datetime(dft["Datum"]) <= end)]
    if selected_series:
        dft = dft[dft["Serie"].isin(selected_series)]
    if search_text.strip():
        dft = dft[dft["Verifikattext"].str.contains(search_text, case=False, na=False)]

    # Valbar begränsning till specifika verifikat
    dft["Verifikat-ID"] = (
        dft["Serie"].astype(str) + "-" + dft["Nr"].astype(str) + " (" + pd.to_datetime(dft["Datum"]).dt.date.astype(str) + ")"
    )
    unique_vouchers = dft[["Serie", "Nr", "Datum", "Verifikat-ID"]].drop_duplicates().sort_values(["Datum", "Serie", "Nr"])
    selected_ids = st.multiselect(
        "Välj specifika verifikat (tomt = alla som matchar filtren)",
        unique_vouchers["Verifikat-ID"].tolist(),
    )
    if selected_ids:
        dft = dft[dft["Verifikat-ID"].isin(selected_ids)]

    st.dataframe(
        dft[["Datum", "Serie", "Nr", "Rad", "Konto", "Belopp", "Transaktionstext", "Dimensioner"]],
        hide_index=True,
        width='stretch',
    )

    csv_t = dft.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Ladda ner transaktioner (CSV)",
        data=csv_t,
        file_name="transaktioner.csv",
        mime="text/csv",
        width='stretch',
    )

st.caption("Kör med: `streamlit run app.py`. Parsern finns i `tools/sie4_parser.py`.")
