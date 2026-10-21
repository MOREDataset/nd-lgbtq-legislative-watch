"""North Dakota LGBTQ+ Legislative Watch — Streamlit entry point.

This file only sets up the page. Data comes from the database that the
scheduled monitor (`python -m ndwatch monitor`) keeps up to date; the app never
scrapes official sites itself.
"""

from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="ND LGBTQ+ Legislative Watch",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from ndwatch.ui import views  # noqa: E402
from ndwatch.ui.review import review  # noqa: E402
from ndwatch.ui.runtime import settings  # noqa: E402
from ndwatch.ui.storage import init_state  # noqa: E402

st.html(f"<style>{(Path(__file__).parent / 'ndwatch' / 'ui' / 'theme.css').read_text()}</style>")
init_state()

pages = {
    "overview": st.Page(views.overview, title="Overview", url_path="overview", default=True),
    "bills": st.Page(views.bills, title="Bills", url_path="bills"),
    "hearings": st.Page(views.hearings, title="Hearings", url_path="hearings"),
    "activity": st.Page(views.activity, title="Recent Activity", url_path="activity"),
    "following": st.Page(views.following, title="Following", url_path="following"),
    "about": st.Page(views.about, title="About & Sources", url_path="about"),
}
if settings().admin_password:
    pages["review"] = st.Page(review, title="Reviewer", url_path="review")
st.session_state["_pages"] = pages

st.navigation(list(pages.values()), position="top").run()
