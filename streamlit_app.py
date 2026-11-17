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
    "signals": st.Page(views.early_signals, title="Early Signals", url_path="signals"),
    "activity": st.Page(views.activity, title="Recent Activity", url_path="activity"),
    "following": st.Page(views.following, title="Following", url_path="following"),
    "about": st.Page(views.about, title="About & Sources", url_path="about"),
}
if settings().admin_password:
    pages["review"] = st.Page(review, title="Reviewer", url_path="review")
st.session_state["_pages"] = pages

from sqlalchemy.exc import DBAPIError  # noqa: E402


def _database_unavailable() -> None:
    # Kept in this file (not in ndwatch/) so it works even if Streamlit Cloud is
    # still running an older copy of the other modules right after an update.
    st.markdown("## North Dakota LGBTQ+ Legislative Watch")
    st.warning(
        "**This dashboard's stored information is temporarily unavailable.** "
        "The database it reads from could not be reached just now. Nothing here is lost; "
        "please try again later."
    )
    st.markdown(
        "In the meantime, the official source for every bill, hearing and vote is the "
        "North Dakota Legislative Branch website: [ndlegis.gov](https://ndlegis.gov)."
    )


try:
    st.navigation(list(pages.values()), position="top").run()
except DBAPIError:
    # The database could not be reached (for example, the free hosting plan paused it).
    # Show a plain explanation instead of a technical error page.
    _database_unavailable()

