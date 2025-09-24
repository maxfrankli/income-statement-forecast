
import streamlit as st

# Example data for a Swedish Resultatrapport (Income Statement) with monthly values and yearly sum
import pandas as pd


# Main accounts
accounts = [
    "Nettoomsättning",
    "Rörelsens kostnader",
    "Rörelseresultat",
    "Finansiella intäkter",
    "Finansiella kostnader",
    "Resultat före skatt",
    "Skatt på årets resultat",
    "Årets resultat"
]

# Subcategories for 'Rörelsens kostnader'
subcategories = [
    "Personalkostnader",
    "Hyra",
    "Förbrukningsmaterial",
    "Övriga kostnader"
]

# Example: random values for each month (replace with real data as needed)
monthly_values = [
    [100000, 110000, 95000, 105000, 98000, 102000, 99000, 101000, 97000, 103000, 100000, 104000],  # Nettoomsättning
    # Rörelsens kostnader will be the sum of subcategories below
    None,
    [40000, 45000, 37000, 43000, 37000, 39000, 39000, 37000, 38000, 41000, 39000, 41000],  # Rörelseresultat
    [800, 900, 850, 950, 900, 950, 900, 950, 900, 950, 900, 950],  # Finansiella intäkter
    [-400, -450, -420, -430, -410, -440, -420, -430, -410, -440, -420, -430],  # Finansiella kostnader
    [40400, 45450, 37430, 43520, 37490, 39510, 39480, 37520, 38490, 41510, 39480, 41520],  # Resultat före skatt
    [-9000, -10000, -8000, -9500, -9000, -9500, -9000, -9500, -9000, -9500, -9000, -9500],  # Skatt på årets resultat
    [31400, 35450, 29430, 34020, 28490, 30010, 30480, 28020, 29490, 32010, 30480, 32020]  # Årets resultat
]

# Example subcategory values (should sum to the value for 'Rörelsens kostnader')
subcat_values = [
    [-30000, -32000, -29000, -31000, -30500, -31500, -30000, -32000, -29500, -31000, -30500, -31500],  # Personalkostnader
    [-15000, -16000, -14000, -15500, -15000, -15500, -15000, -16000, -14500, -15500, -15000, -15500],  # Hyra
    [-8000, -9000, -7000, -8500, -8000, -8500, -8000, -9000, -7500, -8500, -8000, -8500],  # Förbrukningsmaterial
    [-7000, -8000, -8000, -8000, -8000, -8500, -7000, -7000, -7500, -8000, -7500, -8000],  # Övriga kostnader
]

# Calculate total for 'Rörelsens kostnader' as sum of subcategories
rk_total = [sum(x) for x in zip(*subcat_values)]
monthly_values[1] = rk_total

months = [
    "Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"
]



# Use st-aggrid for interactive table
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# Main DataFrame
df = pd.DataFrame(monthly_values, columns=months, index=accounts)
df["Summa"] = df.sum(axis=1)
df.reset_index(inplace=True)
df.rename(columns={"index": "Konto"}, inplace=True)

st.subheader("Resultatrapport (Income Statement)")


# Checkbox for expanding/collapsing subcategories
expand_subcats = st.checkbox("Visa underkategorier för Rörelsens kostnader", value=False)


# Build the display DataFrame
display_rows = []
for i, row in df.iterrows():
    display_rows.append(row)
    if row["Konto"] == "Rörelsens kostnader" and expand_subcats:
        subcat_df = pd.DataFrame(subcat_values, columns=months, index=subcategories)
        subcat_df["Summa"] = subcat_df.sum(axis=1)
        subcat_df.reset_index(inplace=True)
        subcat_df.rename(columns={"index": "Konto"}, inplace=True)
        subcat_df["Konto"] = "   └ " + subcat_df["Konto"]
        for _, subcat_row in subcat_df.iterrows():
            display_rows.append(subcat_row)

display_df = pd.DataFrame(display_rows, columns=df.columns)
numeric_cols = display_df.select_dtypes(include='number').columns
for col in numeric_cols:
    display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}" if pd.notnull(x) else "")

st.dataframe(display_df, height=500)
