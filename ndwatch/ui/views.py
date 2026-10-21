"""The dashboard pages: Overview, Bills (+ bill detail), Hearings, Recent activity, Following, About."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import streamlit as st

from ndwatch.explain import (
    GLOSSARY,
    IMPACT_LABELS,
    about_line,
    century_code_links,
    explain_status,
    kind_name,
    what_would_change,
)
from ndwatch.relevance.detector import default_rules
from ndwatch.timeutil import fmt_date, fmt_relative, local_date, utc_to_local, utcnow
from ndwatch.ui import components as C
from ndwatch.ui import data as D
from ndwatch.ui.runtime import cached, settings
from ndwatch.ui.storage import previous_visit, toggle_follow


def html(s: str) -> None:
    st.html(s)


# ------------------------------------------------------------------ shared


def header() -> dict:
    h = cached("health", lambda db: D.health(db, settings()))
    html(C.masthead())
    html(C.freshness(h))
    return h


def footer() -> None:
    html(
        '<div class="nw-foot">All bill information comes from the North Dakota Legislative Branch '
        '(<a href="https://ndlegis.gov" target="_blank" rel="noopener">ndlegis.gov</a>). '
        "This site is an independent, nonpartisan monitor; it is not an official government site and does not give legal advice. "
        "Descriptions marked automatic or AI are interpretations, not official statements. "
        'Source code: <a href="https://github.com/MOREDataset/nd-lgbtq-legislative-watch" target="_blank" rel="noopener">GitHub</a>.</div>'
    )


def follow_button(uid: str, name: str) -> None:
    following = uid in st.session_state.get("follow", set())
    label = f"★ Following {name}" if following else f"☆ Follow {name}"
    help_ = "Saved only in this browser. No account needed."
    st.button(label, key=f"follow-{uid}", on_click=toggle_follow, args=(uid,), help=help_)


def _cards():
    return cached("cards", lambda db: D.bill_cards(db))


def _possible_cards():
    return cached("cards_possible", lambda db: D.bill_cards(db, include_possible=True))


# ------------------------------------------------------------------ overview


def overview() -> None:
    header()
    cards = _cards()
    uids = {c["uid"] for c in cards}
    now = utcnow()
    hearings = cached("hearings_tracked", lambda db: D.upcoming_hearings(db, uids, days=60))
    events = cached("feed_tracked", lambda db: D.feed(db, uids, limit=400))
    recent_important = [
        e for e in events
        if e["importance"] >= 3 and (e["event_date"] or e["detected_at"]) >= now - timedelta(days=14)
    ]
    week = [h for h in hearings if h["public"] and h["when"] < now + timedelta(days=7)]
    awaiting_gov = [c for c in cards if c["stage"] == "governor" and not c["outcome"]]
    attention = len(week) + len(awaiting_gov)
    live = [c for c in cards if c["live"]]
    html(C.stats([
        ("Bills tracked", len(cards), f"{len(live)} still active" if cards else "none found yet", False),
        ("Upcoming hearings", len(hearings), "next 60 days, officially listed", False),
        ("Important changes", len(recent_important), "in the last 14 days", bool(recent_important)),
        ("Needs attention", attention, "hearings this week & bills with the Governor", attention > 0),
    ]))

    if not live:
        sess = cached("sessions", D.sessions)
        upcoming = [s for s in sess if s["start"] and s["start"] > now.date()]
        msg = "<b>The Legislature is not currently considering any tracked bills.</b> "
        if upcoming:
            s = upcoming[-1]
            msg += f"The next session listed in the official data is the {C.e(s['name'])}, starting {C.e(s['start'].strftime('%B'))} {s['start'].day}, {s['start'].year}. "
        else:
            msg += "No future session has been published in the official data yet. "
        msg += "Bills from past sessions are shown below for reference and are clearly marked."
        html(f'<div class="nw-note">{msg}</div>')

    if hearings:
        html('<div class="nw-kicker">Coming up</div>')
        html(C.hearing_rows(hearings[:5]))
        if len(hearings) > 5:
            st.page_link(st.session_state["_pages"]["hearings"], label=f"See all {len(hearings)} hearings →")

    html('<div class="nw-kicker">What’s happening</div>')
    choice = st.segmented_control(
        "Show", ["All bills", "Active", "Completed", "Bills I follow"], default="All bills",
        key="ov_filter", label_visibility="collapsed",
    )
    rules = default_rules()
    topic = st.selectbox(
        "Topic", ["All topics"] + list(rules.topics.values()), key="ov_topic", label_visibility="collapsed"
    )
    show = cards
    if choice == "Active":
        show = [c for c in cards if not c["outcome"]]
    elif choice == "Completed":
        show = [c for c in cards if c["outcome"]]
    elif choice == "Bills I follow":
        show = [c for c in cards if c["uid"] in st.session_state.get("follow", set())]
    if topic != "All topics":
        show = [c for c in show if topic in c["topic_labels"]]
    allowed = {c["uid"] for c in show}
    items = [e for e in events if e["uid"] in allowed]
    pinned = [e for e in items if e in recent_important]
    if pinned:
        html('<div class="nw-kicker">Important in the last two weeks</div>')
        html(C.feed_rows(pinned, previous_visit()))
        html('<div class="nw-kicker">Everything, newest first</div>')
    if not show:
        if choice == "Bills I follow":
            html('<div class="nw-note">You are not following any bills yet. Open a bill and press <b>Follow</b>. It is saved only in this browser.</div>')
        else:
            html('<div class="nw-note">No bills match this filter.</div>')
    else:
        html(C.feed_rows([e for e in items if e not in pinned][:40], previous_visit()))
    footer()


# ------------------------------------------------------------------ bills


def bills() -> None:
    uid = st.query_params.get("bill")
    if uid:
        bill_page(uid)
        return
    header()
    st.markdown("## Bills")
    st.caption("Bills that may affect LGBTQ+ people, found by checking official titles and the full bill text. "
               "Open a bill for a plain-English explanation.")
    include_possible = st.toggle(
        "Also show bills that might be related but have not been reviewed", key="bills_possible",
        help="These matched weaker signals. A reviewer decides whether they belong on the list.",
    )
    cards = _possible_cards() if include_possible else _cards()
    sessions = sorted({c["session_name"] for c in cards if c["session_name"]}, reverse=True)
    rules = default_rules()
    c1, c2, c3 = st.columns([1.2, 1.2, 1])
    status = c1.selectbox("Status", ["All bills", "Active", "Completed", "Upcoming events", "Recently updated", "Bills I follow"])
    topic = c2.selectbox("Topic", ["All topics"] + list(rules.topics.values()))
    session = c3.selectbox("Session", ["All sessions"] + sessions)
    q = st.text_input("Search by bill number or words", placeholder="e.g. HB 1144, school, birth certificate")
    show = cards
    now = utcnow()
    if status == "Active":
        show = [c for c in show if not c["outcome"]]
    elif status == "Completed":
        show = [c for c in show if c["outcome"]]
    elif status == "Upcoming events":
        show = [c for c in show if c["next_hearing"]]
    elif status == "Recently updated":
        show = [c for c in show if c["last_action_date"] and c["last_action_date"] > now - timedelta(days=14)]
    elif status == "Bills I follow":
        show = [c for c in show if c["uid"] in st.session_state.get("follow", set())]
    if topic != "All topics":
        show = [c for c in show if topic in c["topic_labels"]]
    if session != "All sessions":
        show = [c for c in show if c["session_name"] == session]
    if q.strip():
        needle = q.strip().lower().replace(" ", "")
        show = [c for c in show if needle in (c["name"].lower().replace(" ", "")) or q.strip().lower() in ((c["summary"] or "") + " " + (c["title"] or "")).lower()]
    st.caption(f"{len(show)} of {len(cards)} bills")
    follow = st.session_state.get("follow", set())
    pv = previous_visit()
    for c in show[:150]:
        new = bool(pv and c["last_action_date"] and c["last_action_date"] > pv)
        html(C.bill_card(c, followed=c["uid"] in follow, new=new))
    if not cards:
        html('<div class="nw-note">No bills are listed yet. When the Legislature publishes bills and the monitor finds related ones, they appear here automatically.</div>')
    footer()


def bill_page(uid: str) -> None:
    d = cached(f"bill:{uid}", lambda db: D.bill_detail(db, uid))
    header()
    if d is None:
        st.warning("That bill was not found. It may have been mistyped, or it is not in the monitored data.")
        st.page_link(st.session_state["_pages"]["bills"], label="← All bills")
        return
    facts = cached("facts", D.facts)
    st.page_link(st.session_state["_pages"]["bills"], label="← All bills")
    pills = []
    if d["outcome"] == "became_law":
        pills.append('<span class="nw-pill law">Became law</span>')
    elif d["outcome"] in ("failed", "vetoed", "withdrawn"):
        pills.append(f'<span class="nw-pill fail">{C.e(d["path"].stage_label)}</span>')
    elif d["session_current"]:
        pills.append('<span class="nw-pill live">Active</span>')
    if not d["session_current"]:
        pills.append(f'<span class="nw-pill">Historical &middot; {C.e(d["session_name"])}</span>')
    html(
        f'<div style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-top:.4rem">'
        f'<span class="nw-tag" style="font-size:1rem">{C.e(d["name"])}</span>{"".join(pills)}'
        f'<span style="color:var(--muted);font-size:.85rem">{C.e(kind_name(d["kind"]))} &middot; {C.e(d["session_name"])}</span></div>'
    )
    st.markdown(f"# {d['summary'] or d['name']}")
    follow_button(uid, d["name"])

    # --- the five answers
    changes = what_would_change(d["title"])
    links = century_code_links(d["title"])
    change_html = "".join(f"<div>• {C.e(x)}</div>" for x in changes) or "The official title does not describe the changes in a way we can summarize."
    if links:
        change_html += '<div style="margin-top:.3rem"><small>Current law named in the title: ' + ", ".join(
            C.link(u, lab) for lab, u in links) + "</small></div>"
    human = next((s for s in d["summaries"] if s["kind"] == "human"), None)
    ai = next((s for s in d["summaries"] if s["kind"] == "ai"), None)
    about = C.e(about_line(d["summary"], d["title"]))
    if human and human.get("about"):
        about += f'<div class="nw-quote">{C.e(human["about"])}<span class="w">Written by a reviewer{" for version " + C.e(human["lc"]) if human.get("lc") else ""}'
        about += " &middot; written for an earlier version; may be out of date" if human["needs_review"] else ""
        about += "</span></div>"
    elif ai and ai.get("about"):
        about += f'<div class="nw-quote">{C.e(ai["about"])}<span class="w"><span class="nw-pill ai">AI-generated</span> Not an official statement. Based on version {C.e(ai["lc"])}.</span></div>'

    rel = d["relevance"]
    if human and human.get("who_affected"):
        who = C.e(human["who_affected"]) + '<br><small>Written by a reviewer.</small>'
    elif rel and rel["topics"]:
        who = ("The official text touches on: <b>" + C.e(", ".join(rel["topics"][:4])) +
               "</b>.<br><small>Found automatically from the bill's wording, not a judgment about its effects. "
               "See “Why this bill is listed” below.</small>")
    else:
        who = "Not yet described. Read the bill text linked below."

    path = d["path"]
    status_html = (
        f'<b>{C.e(path.stage_label)}</b><br>{C.e(explain_status(d["status"]))}'
        f'<br><small>Official status: “{C.e(d["status"] or "not listed")}”. Last official action: “{C.e(d["last_action"] or "none")}”.</small>'
    )
    upcoming = [h for h in d["hearings"] if h["upcoming"] and not h["removed"]]
    if upcoming:
        h = upcoming[0]
        kind = "Public hearing" if h["public"] else f"{h['type']} (not a public hearing)"
        nxt = (f"<b>{C.e(kind)}</b>: {C.e(fmt_date(h['when']))}"
               + (f", {C.e(h['committee'])}" if h["committee"] else "")
               + (f", Room {C.e(h['room'])}, State Capitol, Bismarck" if h["room"] else "")
               + f"<br><small>{C.link(d['hearing_url'], 'Official hearing page')}. A hearing is not a vote; no vote date is announced in advance.</small>")
        if h["public"] and facts.get("testimony_deadline_rule"):
            f = facts["testimony_deadline_rule"]
            nxt += (f"<br><small>Testimony: {C.e(f['value'])} "
                    f"(as stated on the {C.link(f['url'], 'official schedule page')}, checked {C.e(fmt_relative(f['checked_at']))}).</small>")
    elif d["outcome"]:
        nxt = f"Nothing further: the process has ended ({C.e(path.stage_label.lower())})."
        if d["outcome"] == "became_law":
            title = (d["title"] or "").lower()
            nxt += "<br><small>When it takes effect: "
            if "declare an emergency" in title:
                nxt += "the title says it declares an emergency, which can make it take effect sooner. "
            if "effective date" in title:
                nxt += "the title says it sets its own effective date. "
            nxt += "Confirm the exact date in the official " + C.link("https://ndlegis.gov/research-center/session-laws", "session laws") + ".</small>"
    else:
        nxt = ("No upcoming event has been officially announced. "
               "<small>Hearings are sometimes scheduled with short notice. Follow this bill to see it here as soon as one is listed.</small>")

    html(C.answers([
        ("What is this about?", about, False),
        ("Current status", status_html, False),
        ("What would change?", change_html, False),
        ("What happens next?", nxt, False),
        ("Who could be affected?", who, True),
    ]))
    if d["decision"] and d["decision"].get("impact"):
        html(f'<div class="nw-note"><b>Reviewer assessment:</b> {C.e(IMPACT_LABELS.get(d["decision"]["impact"], d["decision"]["impact"]))}. '
             f'{C.e(d["decision"]["reason"])} <small>(a description of possible effects, not an endorsement)</small></div>')

    html('<div class="nw-kicker">Where it is in the process</div>')
    html(C.path_html(path))
    notes = []
    if path.amended:
        notes.append("This bill was amended (its wording was changed) along the way.")
    if path.conference:
        notes.append("A conference committee was involved to reconcile House and Senate versions.")
    notes += path.notes
    if notes:
        st.caption(" ".join(notes))

    # --- details
    with st.expander(f"Sponsors ({len(d['sponsors'])})"):
        rows = []
        for s in d["sponsors"]:
            bits = [s.get("full_name") or s["name"]]
            if s["type"] and s["type"].lower() == "committee":
                bits.append("(committee)")
            meta = " · ".join(x for x in [s.get("chamber"), f"District {s['district']}" if s.get("district") else None, s.get("party")] if x)
            label = "**Primary sponsor** — " if s["primary"] else ""
            prof = f" — [official profile]({s['url']})" if s.get("url") else ""
            rows.append(f"- {label}{' '.join(bits)}{' (' + meta + ')' if meta else ''}{prof}")
        st.markdown("\n".join(rows) or "No sponsors listed in the official record.")
        st.caption("Sponsoring a bill is not a vote. See Votes for how each legislator voted.")

    with st.expander(f"Legislative timeline ({len(d['actions'])} official actions)"):
        for a in reversed(d["actions"]):
            when = fmt_date(a["date"], date_only=a["date_only"], with_weekday=False)
            st.markdown(f"**{when}** · {a['chamber'] or ''}  \n{a['description']}")
        st.markdown(f"[Official actions page]({d['actions_url'] or d['url']})")

    with st.expander(f"Hearings ({len(d['hearings'])})"):
        if not d["hearings"]:
            st.write("No hearings are listed in the official record. That does not mean none will be scheduled.")
        for h in sorted(d["hearings"], key=lambda h: h["when"] or utcnow(), reverse=True):
            kind = "Public hearing" if h["public"] else f"{h['type']} — not a public hearing"
            flag = " · ⚠ no longer on the official list" if h["removed"] else (" · upcoming" if h["upcoming"] else "")
            st.markdown(f"**{fmt_date(h['when'])}** — {kind}{flag}  \n{h['committee'] or ''}{', Room ' + h['room'] if h['room'] else ''}")
        st.markdown(f"[Official hearings page]({d['hearing_url'] or d['url']})")
        st.caption("All times are Central Time (CT), the time zone of the State Capitol in Bismarck.")

    with st.expander(f"Testimony ({len(d['testimony'])} documents)"):
        _testimony_section(d, facts)

    with st.expander(f"Votes ({len(d['votes'])} recorded roll calls)"):
        _votes_section(d)

    with st.expander(f"Amendments and bill versions ({len(d['versions'])})"):
        for v in d["versions"]:
            st.markdown(f"- [{v['description'] or v['lc']}]({v['url']}) — LC {v['lc']}")
        st.caption("“Engrossed” versions include adopted amendments. An amendment listed here may have been proposed but not adopted; the timeline shows what was adopted.")

    with st.expander("Why this bill is listed"):
        if d["decision"]:
            dec = d["decision"]
            st.markdown(f"**Reviewer decision: {dec['decision']}** — {dec['reason']}")
        if rel:
            lvl = {"direct": "directly mentions", "indirect": "indirectly relates to", "uncertain": "may relate to"}.get(rel["level"], "may relate to")
            st.markdown(f"Automatic check: the bill **{lvl}** these topics: {', '.join(rel['topics']) or '—'}.")
            html(C.evidence_quotes(rel["evidence"], limit=6))
            st.caption(f"Checked {fmt_relative(rel['computed_at'])} using the title, summary and {len(rel['texts_used'])} bill text version(s). "
                       "Automatic matches show where words appear; they do not judge whether the bill helps or harms anyone.")
        else:
            st.write("This bill has not been checked yet.")

    with st.expander("Official documents and sources"):
        st.markdown("\n".join(f"- [{label}]({url})" for label, url in [
            ("Bill overview", d["url"]), ("Versions (bill text)", d["versions_url"]), ("Actions", d["actions_url"]),
            ("Hearings", d["hearing_url"]), ("Testimony", d["testimony_url"]), ("Video", d["video_url"]),
        ] if url))
        st.caption(f"First seen by this monitor {fmt_date(d['first_seen_at'])}; last changed {fmt_relative(d['last_changed_at'])}.")

    if d["events"]:
        html('<div class="nw-kicker">Changes recorded by this monitor</div>')
        html(C.feed_rows(d["events"][:30], previous_visit(), show_bill=False))
    footer()


def _testimony_section(d: dict, facts: dict) -> None:
    tc = d["testimony_checked"]
    if tc:
        st.caption(f"Official testimony page checked {fmt_relative(tc['at'])}. "
                   "The Legislature notes that its testimony list is updated periodically and may not be a complete record.")
    else:
        st.caption("The testimony page for this bill has not been checked yet.")
    if d["testimony"]:
        counts = Counter((t["position"] or "Not stated") for t in d["testimony"])
        st.markdown(" · ".join(f"**{v}** {k}" for k, v in counts.most_common()) + "  \n*Positions are as officially recorded by the submitter.*")
        rows = [{"Hearing": f"{t['date'] or ''} {t['time'] or ''}".strip(), "Committee": t["committee"], "Name": t["name"],
                 "Organization": t["organization"], "Position (official)": t["position"], "Document": t["url"]}
                for t in sorted(d["testimony"], key=lambda t: (t["date"] or "", t["name"] or ""))]
        st.dataframe(rows, hide_index=True, use_container_width=True,
                     column_config={"Document": st.column_config.LinkColumn("Document", display_text="Open")})
    else:
        st.write("No testimony documents are listed on the official page yet.")
    how = facts.get("how_to_submit_testimony_url")
    rule = facts.get("testimony_deadline_rule")
    lines = ["**How to submit testimony:** testimony is submitted through the Legislature's website for each scheduled public hearing."]
    if how:
        lines.append(f"[Official guide: how to submit testimony]({how['value']})")
    if rule:
        lines.append(f"Deadline, as stated on the official schedule page: *{rule['value']}*")
    st.markdown("  \n".join(lines))


def _votes_section(d: dict) -> None:
    if not d["votes"]:
        st.write("No recorded floor votes are listed in the official data for this bill.")
    for v in d["votes"]:
        result = "Passed" if v["passed"] else ("Failed" if v["passed"] is False else "Result not stated")
        st.markdown(
            f"**{fmt_date(v['date'])} — {v['chamber']}: {v['description'] or 'Recorded vote'}** · {result}  \n"
            f"{v['yeas']} yes · {v['nays']} no · {v['absent']} absent or excused"
        )
        if v["members"]:
            cols = st.columns(3)
            for col, key, label in zip(cols, ["Yea", "Nay", "Absent"], ["Yes", "No", "Absent / excused"], strict=False):
                names = v["members"].get(key, [])
                col.markdown(f"*{label} ({len(names)})*  \n" + "  \n".join(
                    f"{n['name']}" + (f" ({(n['party'] or '')[:1]}-{n['district']})" if n.get("party") and n.get("district") else "") for n in names))
        st.divider()
    st.caption("These are recorded votes of the full House or Senate. Committee recommendations (such as “do pass 12–1”) appear in the timeline and are not final votes. "
               "Source: official roll-call data from ndlegis.gov.")


# ------------------------------------------------------------------ hearings


def hearings() -> None:
    header()
    st.markdown("## Hearings")
    st.caption("Officially scheduled committee meetings for tracked bills. All times are Central Time (CT), the time zone of the State Capitol in Bismarck.")
    all_bills = st.toggle("Show hearings for all bills, not only tracked ones", key="hear_all")
    uids = None if all_bills else {c["uid"] for c in _cards()}
    items = cached(f"hearings:{all_bills}", lambda db: D.upcoming_hearings(db, uids, days=90))
    facts = cached("facts", D.facts)
    rule = facts.get("testimony_deadline_rule")
    if rule:
        html(f'<div class="nw-note"><b>Want to testify?</b> {C.e(rule["value"])} '
             + (C.link(facts["how_to_submit_testimony_url"]["value"], "Official guide to submitting testimony") + ". " if facts.get("how_to_submit_testimony_url") else "")
             + f'<small>Quoted from the {C.link(rule["url"], "official schedule page")}, checked {C.e(fmt_relative(rule["checked_at"]))}.</small></div>')
    if facts.get("work_session_testimony_note"):
        st.caption("Public hearings take testimony. Committee work sessions are meetings to discuss and vote on recommendations; " + facts["work_session_testimony_note"]["value"])
    if not items:
        html('<div class="nw-note">No hearings are officially listed right now. This does not mean none will happen: '
             'committees post hearings as they are scheduled, and this page updates automatically.</div>')
    else:
        now = utc_to_local(utcnow())
        counts = Counter(local_date(h["when"]) for h in items)
        months = sorted({(d.year, d.month) for d in counts})
        for y, m in months[:2]:
            st.markdown(f"#### {now.replace(year=y, month=m, day=1):%B %Y}")
            html(C.month_calendar(y, m, counts, now.date()))
        html(C.hearing_rows(items))
    st.markdown("[Official public hearing schedule](https://www.ndlegis.gov/legend/committee/hearings/public-schedule/)")
    footer()


# ------------------------------------------------------------------ activity


def activity() -> None:
    header()
    st.markdown("## Recent activity")
    st.caption("Every change the monitor has recorded for tracked bills, newest first. Each entry shows the official date and links to its source.")
    uids = {c["uid"] for c in _cards()}
    only_important = st.toggle("Only important updates (hearings, votes, final outcomes)", key="act_imp")
    items = cached(f"feed:{only_important}", lambda db: D.feed(db, uids, limit=500, min_importance=3 if only_important else 1))
    html(C.feed_rows(items[:200], previous_visit()))
    footer()


# ------------------------------------------------------------------ following


def following() -> None:
    header()
    st.markdown("## Following")
    follow = st.session_state.get("follow", set())
    st.caption("Bills you follow are remembered in this browser only. No account, no email, no personal data.")
    cards = [c for c in _possible_cards() if c["uid"] in follow]
    if not cards:
        html('<div class="nw-note">You are not following any bills yet. Open any bill and press <b>☆ Follow</b>.</div>')
    else:
        pv = previous_visit()
        events = cached("feed_follow:" + ",".join(sorted(follow)), lambda db: D.feed(db, set(follow), limit=200))
        new = [e for e in events if pv and not e["backfill"] and e["detected_at"] > pv]
        html(C.stats([
            ("Following", len(cards), "bills", False),
            ("New for you", len(new), "since your last visit" if pv else "first visit", bool(new)),
            ("Upcoming hearings", sum(1 for c in cards if c["next_hearing"]), "officially listed", False),
            ("Finished", sum(1 for c in cards if c["outcome"]), "final outcome recorded", False),
        ]))
        for c in cards:
            html(C.bill_card(c, followed=True))
        html('<div class="nw-kicker">Updates on bills you follow</div>')
        html(C.feed_rows(events[:60], pv))
        share = "?follow=" + ",".join(sorted(follow))
        st.caption(f"To keep this list on another device, bookmark this page with your list: `following{share}`")
    footer()


# ------------------------------------------------------------------ about


def about() -> None:
    h = header()
    st.markdown("## How this works")
    st.markdown(
        """
**Where the information comes from.** Every fact about a bill (titles, sponsors, actions, hearings, votes,
testimony) is copied from the North Dakota Legislative Branch website and its official data service. Each bill page
links to the original pages.

**How bills are found.** The monitor reads every bill the Legislature publishes. It looks for topics such as sexual
orientation, gender identity, healthcare, schools, identity documents, marriage and family, libraries, and HIV, first in
the official title and summary, then in the full text of every version of the bill. Some words only count when related
words appear nearby (for example, “restroom” near “sex”). Bills with weaker matches go to a review list, where a person
decides whether they belong, and writes down why.

**What this site does not do.** It does not take political positions. Labels such as “may restrict access or
protections” describe possible effects, and are written by reviewers with a stated reason. Automatic matches only show
where words appear. Nothing here is legal advice.

**Updates.** A scheduled job checks the official sources every hour during a session, and less often between
sessions, even when nobody has this page open. If a check fails, this site keeps showing the last information it
received and says so at the top of the page.
"""
    )
    st.markdown("### How a bill becomes law in North Dakota")
    html(
        '<ol class="nw-path" aria-label="Typical steps"><li class="done"><span>Introduced in House or Senate</span></li>'
        '<li class="done"><span>Committee hearing &amp; recommendation</span></li><li class="done"><span>Vote by that chamber</span></li>'
        '<li class="done"><span>Same steps in the other chamber</span></li><li class="done"><span>Governor signs or vetoes</span></li>'
        '<li class="done"><span>Filed as law</span></li></ol>'
    )
    st.markdown(
        "Bills can stop at any step. If the two chambers pass different versions, a **conference committee** may work out "
        "one version. The Governor can **veto** a bill, and the Legislature can override a veto with a two-thirds vote. "
        "Resolutions follow a different path and usually do not go to the Governor."
    )
    st.markdown("### Words you will see")
    for term, meaning in GLOSSARY.items():
        st.markdown(f"**{term}** — {meaning}")

    st.markdown("### Data freshness")
    rows = []
    for s in h.get("sources", []):
        rows.append({
            "Source": s["source"], "Last checked": fmt_date(s["checked_at"]),
            "Result": "OK" if s["ok"] else f"Failed: {s['error']}",
            "Last success": fmt_date(s["last_ok"]) if s["last_ok"] else "never",
            "Published by source": fmt_date(s["source_last_updated"]) if s["source_last_updated"] else "not stated",
        })
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("“Last checked” is when this monitor read the source. “Published by source” is the update time the Legislature reports for that data.")
    st.caption(f"Monitoring mode: {h['mode'].replace('_', ' ')} (full check every {h['expected_interval_min']} minutes).")
    footer()
