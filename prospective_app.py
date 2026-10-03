"""Independent read-only prospective operational page. No performance imports."""
from pathlib import Path
import streamlit as st
from btc5_v3.prospective.store import Study
from btc5_v3.prospective.collector import utc_ms

st.set_page_config(page_title='Prospective collection health',layout='wide')
st.title('Prospective collection health')
st.caption('Operational status only. No performance analysis. No study controls.')
name=st.text_input('Study ID')
if name:
    try:
        status=Study(Path(__file__).parent,name).status(utc_ms())
        st.json(status)
    except Exception:
        st.error('Study unavailable or invalid. No data were modified.')
