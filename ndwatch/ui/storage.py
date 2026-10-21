"""Per-browser memory (followed bills, last visit) without accounts.

Stored only in the viewer's own browser (localStorage). If the browser blocks
storage, the app still works; following then lasts for the current visit and
can be kept with the shareable link (?follow=HB1144,...).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_component = components.declare_component(
    "ndwatch_storage", path=str(Path(__file__).parent / "storage_component")
)


def sync(write: dict | None = None) -> dict | None:
    """Returns the stored dict (None until the browser has answered once)."""
    return _component(write=write, default=None, key="ndwatch_storage")


def init_state() -> None:
    ss = st.session_state
    stored = sync(ss.get("_pending_write"))
    ss["_pending_write"] = None
    if "follow" not in ss:
        ss["follow"] = set()
        ss["follow_loaded"] = False
    if stored is not None and not ss.get("follow_loaded"):
        ss["follow"] = set(stored.get("follow") or []) | ss["follow"]
        ss["follow_loaded"] = True
        if "previous_visit" not in ss:
            prev = stored.get("last_visit")
            try:
                ss["previous_visit"] = datetime.fromisoformat(prev) if prev else None
            except ValueError:
                ss["previous_visit"] = None
            ss["_pending_write"] = {"last_visit": datetime.utcnow().isoformat(timespec="seconds")}
    # Also accept ?follow=uid1,uid2 from a shared link.
    q = st.query_params.get("follow")
    if q and not ss.get("follow_from_link"):
        ss["follow"] |= {x for x in q.split(",") if x}
        ss["follow_from_link"] = True


def toggle_follow(uid: str) -> None:
    ss = st.session_state
    follow = set(ss.get("follow", set()))
    follow.symmetric_difference_update({uid})
    ss["follow"] = follow
    ss["_pending_write"] = {"follow": sorted(follow)}


def previous_visit() -> datetime | None:
    return st.session_state.get("previous_visit")
