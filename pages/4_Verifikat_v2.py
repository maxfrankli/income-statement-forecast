# app.py
import streamlit as st
import pandas as pd
from tools.sie4_parser import SIE4Parser

st.set_page_config(page_title="SIE4 – Verifikat (enkel)", layout="wide")
st.title("SIE4 – Verifikat (enkel vy)")

uploaded = st.file_uploader("Ladda upp SIE4-fil", type=["se","sie", "SIE", "txt"])
if not uploaded:
    st.info("Välj en SIE4-fil för att börja.")
    st.stop()

# Läs bytes (viktigt för korrekt decoding) och parsa med cp865 prioriterad
file_bytes = uploaded.getvalue()
parser = SIE4Parser(infer_account_hierarchy=True)
company = parser.parse_bytes(file_bytes, encoding_candidates=("utf-8", "cp865", "cp1252", "latin1"))

st.caption(f"Filkodning: {company.source_encoding or 'okänd'}")

# DataFrames
df_v = company.to_pandas_vouchers().rename(columns={
    "series": "Serie",
    "number": "Nr",
    "date": "Datum",
    "text": "Text",
    "reg_date": "Registreringsdatum",
    "n_transactions": "Antal transaktioner",
}).sort_values(["Datum", "Serie", "Nr"])

df_t = company.to_pandas_transactions().rename(columns={
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
}).sort_values(["Datum", "Serie", "Nr", "Rad"])

if df_v.empty:
    st.warning("Inga verifikat hittades i filen.")
    st.stop()

# Lägg till en "Visa"-kolumn för enkel klick/val (enkel-selektion)
df_v = df_v.copy()
df_v.insert(0, "Visa", False)

st.subheader("Verifikat")
edited = st.data_editor(
    df_v,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Visa": st.column_config.CheckboxColumn("Visa", help="Markera ett verifikat för att se transaktioner nedan"),
        "Datum": st.column_config.DatetimeColumn("Datum", format="YYYY-MM-DD"),
    },
    disabled=["Datum", "Serie", "Nr", "Text", "Registreringsdatum", "Antal transaktioner"],
    key="verifikat_editor",
)

# Tillåt max ett valt verifikat – om flera bockas i, ta den första
selected_rows = edited.index[edited["Visa"] == True].tolist()
if not selected_rows:
    st.info("Markera ett verifikat i tabellen ovan för att visa dess transaktioner.")
    st.stop()

row = selected_rows[0]
selected = edited.loc[row]

# Filtrera transaktioner för valt verifikat
mask = (
    (df_t["Serie"] == selected["Serie"]) &
    (df_t["Nr"] == selected["Nr"]) &
    (pd.to_datetime(df_t["Datum"]).dt.date == pd.to_datetime(selected["Datum"]).date())
)
tx_for_voucher = df_t.loc[mask, ["Datum", "Serie", "Nr", "Rad", "Konto", "Belopp", "Transaktionstext", "Dimensioner"]]

st.subheader(f"Transaktioner för {selected['Serie']}-{selected['Nr']} ({pd.to_datetime(selected['Datum']).date()})")
if tx_for_voucher.empty:
    st.info("Inga transaktioner hittades för det valda verifikatet.")
else:
    st.dataframe(tx_for_voucher, hide_index=True, use_container_width=True)
