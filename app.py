"""
SeaTrace (Survey Detector): finds ships surveying the seabed (lawnmower patterns) and ships holding one
spot over deep water in AIS tracks, ranks what it finds and explains why.

The main page is the SeaTrace console (views/console.py, files in views/seatrace/), fed by the live
Survey Detector pipeline (webapp/). The Analyst pages are ordinary Streamlit pages in the same look.
Pages live in views/ (not "pages/": Streamlit would also serve that folder as old-style pages).
Run locally:  streamlit run app.py
"""
import streamlit as st

from webapp import ui

st.set_page_config(page_title="SeaTrace", page_icon=":ocean:", layout="wide")

P = st.Page
page = st.navigation({
    "": [P("views/console.py", title="SeaTrace", icon=":material/radar:", url_path="console", default=True)],
    "Analyst": [
        P("views/analyst_upload.py", title="Upload your own track", icon=":material/upload_file:"),
        P("views/analyst_settings.py", title="Detection settings", icon=":material/tune:"),
        P("views/analyst_compare.py", title="Compare models", icon=":material/rule:"),
        P("views/analyst_data.py", title="Data & downloads", icon=":material/download:"),
    ],
}, position="top")
if page.title != "SeaTrace":          # the console brings its own look and header
    ui.inject_css()
page.run()
