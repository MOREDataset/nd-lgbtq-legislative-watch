"""Reviewer page (password protected): include/exclude bills, set impact, write summaries."""

from __future__ import annotations

import hmac

import streamlit as st

from ndwatch.db.schema import ReviewDecision, Summary
from ndwatch.explain import IMPACT_LABELS
from ndwatch.timeutil import utcnow
from ndwatch.ui import components as C
from ndwatch.ui import data as D
from ndwatch.ui.runtime import cached, clear_cache, db_session, settings


def review() -> None:
    pw = settings().admin_password
    st.markdown("## Reviewer")
    if not pw:
        st.info("Reviewing is turned off. Set NDWATCH_ADMIN_PASSWORD in the app's secrets to enable it.")
        return
    if not st.session_state.get("reviewer_ok"):
        entered = st.text_input("Reviewer password", type="password")
        if entered and hmac.compare_digest(entered, pw):
            st.session_state["reviewer_ok"] = True
            st.rerun()
        elif entered:
            st.error("Incorrect password.")
        return

    st.caption("Decisions are public on each bill page together with your reason. Describe effects, not opinions.")
    who = st.text_input("Your initials or role (shown with decisions)", key="rv_who", max_chars=40)
    suggestions = cached("tracker_suggestions", D.tracker_suggestions)
    if suggestions:
        with st.expander(f"Advocacy trackers name {len(suggestions)} bill(s) we have not listed"):
            st.caption("From the Trans Legislation Tracker and the ACLU legislative tracker. Their lists are not used as "
                       "facts; they only point to bills worth a look. Open the bill, read it, and decide below.")
            for sg in suggestions:
                st.markdown(f"**{sg['name']}** ({sg['uid'].split(':')[0]}) · {', '.join(sg['trackers'])}  \n"
                            f"{sg['summary'] or ''}  \n[Bill page](bills?bill={sg['uid']})")
                with st.form(f"t-{sg['uid']}"):
                    decision = st.radio("Decision", ["include", "exclude"], horizontal=True, key=f"td-{sg['uid']}")
                    reason = st.text_area("Reason (required, shown publicly)", max_chars=600, key=f"tr-{sg['uid']}")
                    if st.form_submit_button("Save decision"):
                        if not reason.strip():
                            st.error("Please give a reason.")
                        else:
                            with db_session() as db:
                                db.add(ReviewDecision(bill_uid=sg["uid"], decision=decision, reason=reason.strip(),
                                                      reviewer=who or None, created_at=utcnow()))
                                db.commit()
                            clear_cache()
                            st.success("Saved.")
    show = st.radio("Show", ["Waiting for review", "All flagged bills"], horizontal=True)
    queue = cached("review_queue", D.review_queue)
    if show == "Waiting for review":
        queue = [q for q in queue if q["status"] == "possible" and not q["decision"]]
    st.caption(f"{len(queue)} bills")
    for q in queue[:60]:
        with st.expander(f"{q['name']} · score {q['score']} · {q['summary'] or ''}"[:140]):
            st.markdown(f"{q['session_name']} · automatic: **{q['status']}** ({q['level'] or '—'}) · topics: {', '.join(q['topics'])}")
            if q["decision"]:
                st.markdown(f"Current decision: **{q['decision']}** — {q['reason']}")
            st.html(C.evidence_quotes(q["evidence"], limit=5))
            st.markdown(f"[Official bill page]({q['url']})")
            with st.form(f"f-{q['uid']}"):
                decision = st.radio("Decision", ["include", "exclude"], horizontal=True)
                impact = st.selectbox("Possible effect (optional)", ["", *IMPACT_LABELS], format_func=lambda k: IMPACT_LABELS.get(k, "— not set —"))
                reason = st.text_area("Reason (required, shown publicly)", max_chars=600)
                about = st.text_area("Plain-language summary (optional, shown as written by a reviewer)", max_chars=1200)
                affected = st.text_area("Who could be affected (optional, only what the text supports)", max_chars=600)
                if st.form_submit_button("Save decision"):
                    if not reason.strip():
                        st.error("Please give a reason.")
                    else:
                        with db_session() as db:
                            db.add(ReviewDecision(bill_uid=q["uid"], decision=decision, impact=impact or None,
                                                  reason=reason.strip(), reviewer=who or None, created_at=utcnow()))
                            if about.strip() or affected.strip():
                                detail = D.bill_detail(db, q["uid"])
                                lc = detail["versions"][-1]["lc"] if detail and detail["versions"] else None
                                db.add(Summary(bill_uid=q["uid"], lc_number=lc, kind="human", about=about.strip() or None,
                                               who_affected=affected.strip() or None, author=who or None, created_at=utcnow()))
                            db.commit()
                        clear_cache()
                        st.success("Saved.")
