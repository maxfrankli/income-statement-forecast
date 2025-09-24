import streamlit as st
import pandas as pd
from io import StringIO

st.set_page_config(page_title="SIE4 Viewer", page_icon="📈")

st.markdown("# SIE4 Viewer")
st.sidebar.header("PSIE4 Viewer")
st.write(
    """This shows a placeholder for the SIE4 Viewer page."""
)



uploaded_file = st.file_uploader("Choose a file")
if uploaded_file is not None:
    # To read file as bytes:
    bytes_data = uploaded_file.getvalue()
    st.write(bytes_data)

    # To convert to a string based IO:
    stringio = StringIO(uploaded_file.getvalue().decode("cp865"))
    st.write(stringio)

    # To read file as string:
    string_data = stringio.read()
