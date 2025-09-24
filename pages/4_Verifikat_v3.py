# app.py
import pandas as pd
import streamlit as st
from tools.sie4_parser import SIE4Parser

st.set_page_config(page_title="SIE4 – Verifikat (1 tabell, expandera rad)", layout="wide")
st.title("SIE4 – Verifikat (1 tabell)")

uploaded = st.file_uploader("Ladda upp SIE4-fil", type=["sie","SIE","txt","se","SE"])
if not uploaded:
    st.info("Välj en SIE4-fil för att börja.")
    st.stop()

# --- Parse SIE ---
file_bytes = uploaded.getvalue()
parser = SIE4Parser(infer_account_hierarchy=True)
company = parser.parse_bytes(file_bytes, encoding_candidates=("utf-8","cp865","cp1252","latin1"))
st.caption(f"Filkodning: {company.source_encoding or 'okänd'}")

df_v = company.to_pandas_vouchers().rename(columns={
    "series":"Serie","number":"Nr","date":"Datum","text":"Text",
    "reg_date":"Registreringsdatum","n_transactions":"Antal transaktioner"
}).sort_values(["Datum","Serie","Nr"]).reset_index(drop=True)

df_t = company.to_pandas_transactions().rename(columns={
    "series":"Serie","number":"Nr","voucher_date":"Datum","voucher_text":"Verifikattext",
    "tx_index":"Rad","account":"Konto","amount":"Belopp","dim":"Dimensioner","text":"Transaktionstext",
}).sort_values(["Datum","Serie","Nr","Rad"]).reset_index(drop=True)

if df_v.empty:
    st.warning("Inga verifikat hittades i filen.")
    st.stop()

# Unik nyckel per verifikat (för att injicera transaktionerna på rätt ställe)
def voucher_key(serie, nr, datum) -> str:
    return f"{serie}|{nr}|{pd.to_datetime(datum).date()}"

df_v = df_v.assign(Key=[voucher_key(r.Serie, r.Nr, r.Datum) for _, r in df_v.iterrows()])

# Håll reda på vilken rad som är expanderad
if "expanded_key" not in st.session_state:
    st.session_state.expanded_key = None

def build_display_df(expanded_key: str | None) -> pd.DataFrame:
    rows = []
    for _, v in df_v.iterrows():
        # Verifikatrad
        rows.append({
            "Expandera": bool(expanded_key == v.Key),
            "Typ": "Verifikat",
            "Datum": pd.to_datetime(v["Datum"]).date(),
            "Serie": v["Serie"],
            "Nr": v["Nr"],
            "Text": v.get("Text",""),
            "Konto": None, "Rad": None, "Belopp": None,
            "Transaktionstext": None, "Dimensioner": None,
            "Antal transaktioner": int(v.get("Antal transaktioner", 0)),
            "Key": v.Key,          # dold kolumn
            "_is_child": False,    # dold, för eget bruk
        })

        # Om denna är expanderad: injicera transaktionerna som rader direkt under
        if expanded_key == v.Key and not df_t.empty:
            mask = (
                (df_t["Serie"] == v["Serie"]) &
                (df_t["Nr"] == v["Nr"]) &
                (pd.to_datetime(df_t["Datum"]).dt.date == pd.to_datetime(v["Datum"]).date())
            )
            tx = df_t.loc[mask, ["Datum","Serie","Nr","Rad","Konto","Belopp","Transaktionstext","Dimensioner"]]
            for _, t in tx.iterrows():
                rows.append({
                    "Expandera": False,      # ignoreras för child-rader
                    "Typ": "   └─ Transaktion",
                    "Datum": pd.to_datetime(t["Datum"]).date() if pd.notna(t["Datum"]) else None,
                    "Serie": t["Serie"],
                    "Nr": t["Nr"],
                    "Text": "",
                    "Konto": t.get("Konto"),
                    "Rad": int(t["Rad"]) if pd.notna(t["Rad"]) else None,
                    "Belopp": float(t["Belopp"]) if pd.notna(t["Belopp"]) else None,
                    "Transaktionstext": t.get("Transaktionstext"),
                    "Dimensioner": None if t.get("Dimensioner") is None else str(t.get("Dimensioner")),
                    "Antal transaktioner": None,
                    "Key": None,            # child har ingen key
                    "_is_child": True,
                })
    return pd.DataFrame(rows)

# 1) Bygg tabellen utifrån nuvarande expanded_key
df_display = build_display_df(st.session_state.expanded_key)

# 2) Visa ENDA tabellen (data_editor) — använd checkbox-kolumnen för att "klicka"
edited = st.data_editor(
    df_display,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Expandera": st.column_config.CheckboxColumn(
            "Expandera", help="Bocka i för att visa transaktioner under verifikatet"
        ),
        "Datum": st.column_config.DatetimeColumn("Datum", format="YYYY-MM-DD"),
        "Belopp": st.column_config.NumberColumn("Belopp", help="Debet (+) / Kredit (−)"),
    },
    disabled=[  # gör tabellen read-only förutom Expandera
        "Typ","Datum","Serie","Nr","Text","Konto","Rad","Belopp",
        "Transaktionstext","Dimensioner","Antal transaktioner","Key","_is_child"
    ],
    key="verifikat_single_table",
)

# 3) Tolkning av klick: hitta första parent-rad med Expandera=True
#    (Ignorera child-rader eftersom deras Key är None)
try:
    expanded_keys = edited.loc[(edited["Expandera"] == True) & (edited["Key"].notna()), "Key"].tolist()
except Exception:
    expanded_keys = []

new_key = expanded_keys[0] if expanded_keys else None

# Om valet ändrats: uppdatera session_state och rerun så tabellen injiceras rätt
if new_key != st.session_state.expanded_key:
    st.session_state.expanded_key = new_key
    st.rerun()
