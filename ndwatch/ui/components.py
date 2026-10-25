"""HTML fragments for the dashboard.

All text that comes from official sources is escaped before it is placed in
HTML: source content is untrusted input.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from ndwatch.explain import IMPACT_LABELS, headline
from ndwatch.process import CURRENT, DONE, FAILED, SKIPPED
from ndwatch.timeutil import fmt_date, fmt_relative, fmt_time, utc_to_local, utcnow


def e(s) -> str:
    return escape("" if s is None else str(s))


def bill_href(uid: str) -> str:
    return f"bills?bill={quote(uid, safe='')}"


def safe_url(url: str | None) -> str | None:
    """Only allow http(s) links to be rendered."""
    if url and url.startswith(("https://", "http://")):
        return url
    return None


def link(url: str | None, text: str) -> str:
    u = safe_url(url)
    if not u:
        return e(text)
    return f'<a href="{e(u)}" target="_blank" rel="noopener noreferrer">{e(text)}</a>'


def bands() -> str:
    return '<div class="nw-bands" aria-hidden="true">' + "<span></span>" * 6 + "</div>"


def masthead(now: datetime | None = None) -> str:
    loc = utc_to_local(now or utcnow())
    dl = f"Bismarck, N.D. &middot; {loc:%A}, {loc:%B} {loc.day}, {loc.year}"
    return (
        '<div class="nw-mast"><div class="t">North Dakota <em>LGBTQ+</em> Legislative Watch</div>'
        f'<div class="nw-dateline">{dl}</div></div>' + bands()
    )


def freshness(h: dict) -> str:
    last = h.get("last_ok_run")
    if last is None:
        return '<div class="nw-warn"><b>No successful update has been recorded yet.</b> The information below may be incomplete.</div>'
    out = (
        f'<div class="nw-fresh">Official sources last checked <b>{e(fmt_relative(last))}</b> '
        f'({e(fmt_date(last))}). Updates run automatically; you never need to refresh.</div>'
    )
    if h.get("stale"):
        out += (
            '<div class="nw-warn"><b>Updates may be delayed.</b> The automatic check has not succeeded for '
            f'{e(fmt_relative(last).replace(" ago", ""))}. What you see may be out of date; confirm on '
            '<a href="https://ndlegis.gov" target="_blank" rel="noopener">ndlegis.gov</a>.</div>'
        )
    failing = h.get("failing_sources") or []
    if failing and not h.get("stale"):
        names = ", ".join(sorted({f["source"].split(":")[0].replace("_", " ") for f in failing}))
        out += f'<div class="nw-note">Some official sources could not be read in the latest check ({e(names)}). Information from them may be older.</div>'
    return out


def stats(items: list[tuple[str, int | str, str, bool]]) -> str:
    cells = "".join(
        f'<div class="nw-stat{" hot" if hot else ""}"><div class="n">{e(n)}</div><div class="l">{e(label)}</div><div class="s">{e(sub)}</div></div>'
        for label, n, sub, hot in items
    )
    return f'<div class="nw-stats" role="list">{cells}</div>'


def status_pills(card: dict) -> str:
    out = []
    if card.get("outcome") == "became_law":
        out.append('<span class="nw-pill law">Became law</span>')
    elif card.get("outcome") in ("failed", "vetoed", "withdrawn"):
        out.append(f'<span class="nw-pill fail">{e(card.get("outcome_label"))}</span>')
    elif card.get("outcome") == "adopted":
        out.append(f'<span class="nw-pill law">{e(card.get("outcome_label") or "Adopted")}</span>')
    elif card.get("live"):
        out.append('<span class="nw-pill live">Active</span>')
    else:
        out.append('<span class="nw-pill">No final action recorded</span>')
    if card.get("impact"):
        out.append(f'<span class="nw-pill">{e(IMPACT_LABELS.get(card["impact"], card["impact"]))}</span>')
    if card.get("relevance") == "possible" and card.get("reviewed") != "include":
        out.append('<span class="nw-pill">Possibly related &middot; not yet reviewed</span>')
    return "".join(out)


def bill_card(c: dict, followed: bool = False, new: bool = False) -> str:
    topics = "".join(f'<span class="nw-pill">{e(t)}</span>' for t in c.get("topic_labels", [])[:3])
    nh = c.get("next_hearing")
    if nh:
        kind = "Public hearing" if (nh["type"] or "").lower() == "bill hearing" else (nh["type"] or "Meeting")
        nxt = f'<div class="next"><b>Next:</b> {e(kind)}, {e(fmt_date(nh["when"]))}' + (
            f' &middot; {e(nh["committee"])}' if nh.get("committee") else "") + (
            f' &middot; Room {e(nh["room"])}' if nh.get("room") else "") + "</div>"
    elif c.get("outcome"):
        nxt = f'<div class="next">Final outcome: <b>{e(c.get("outcome_label"))}</b></div>'
    else:
        nxt = '<div class="next">No upcoming event has been officially announced.</div>'
    meta = []
    if c.get("session_name"):
        meta.append(e(c["session_name"]))
    if c.get("primary_sponsor"):
        meta.append("Introduced by " + e(c["primary_sponsor"]))
    if c.get("last_action_date"):
        meta.append("Last action " + e(fmt_date(c["last_action_date"], date_only=True, with_weekday=False)))
    star = ' <span class="nw-pill live">&#9733; Following</span>' if followed else ""
    newp = ' <span class="nw-pill new">New since your last visit</span>' if new else ""
    return (
        f'<div class="nw-card"><div class="top"><a class="nw-tag" href="{bill_href(c["uid"])}" target="_self">{e(c["name"])}</a>'
        f'{status_pills(c)}{star}{newp}</div>'
        f'<div class="sum"><a href="{bill_href(c["uid"])}" target="_self" style="color:inherit;text-decoration:none">{e(headline(c.get("summary"), c.get("title") or c["name"]))}</a></div>'
        f'<div class="meta">{" &middot; ".join(meta)}</div><div>{topics}</div>{nxt}</div>'
    )


def feed_rows(items: list[dict], last_visit: datetime | None = None, show_bill: bool = True) -> str:
    if not items:
        return '<div class="nw-note">No activity to show yet.</div>'
    rows = []
    for i in items:
        when = i["event_date"]
        if when:
            loc = utc_to_local(when)
            d = f"{loc:%b} {loc.day}<br>{loc.year}"
            if not i["date_only"]:
                d += f"<br>{e(fmt_time(when))}"
        else:
            loc = utc_to_local(i["detected_at"])
            d = f"{loc:%b} {loc.day}<br>{loc.year}<br><span title='Date the change was detected; the source gives no date'>detected</span>"
        fresh = bool(last_visit and not i["backfill"] and i["detected_at"] > last_visit)
        tag = ""
        if show_bill and i.get("uid") and i.get("bill"):
            tag = f'<a class="nw-tag" href="{bill_href(i["uid"])}" target="_self">{e(i["bill"])}</a> '
        detail = f'<div class="src">{e(i["detail"])}</div>' if i.get("detail") else ""
        src = f'<div class="src">Source: {link(i.get("source_url"), i.get("source_label") or "official record")}</div>'
        newp = ' <span class="nw-pill new">New</span>' if fresh else ""
        rows.append(
            f'<div class="nw-row imp{i["importance"]}{" fresh" if fresh else ""}"><div class="d">{d}</div>'
            f'<div class="body">{tag}<span class="h">{e(i["title"])}</span>{newp}{detail}{src}</div></div>'
        )
    return '<div class="nw-ledger">' + "".join(rows) + "</div>"


def path_html(path) -> str:
    items = []
    for s in path.steps:
        cls = {DONE: "done", CURRENT: "current", FAILED: "failed", SKIPPED: "skipped"}.get(s.state, "")
        sr = {DONE: "completed", CURRENT: "current step", FAILED: "stopped here", SKIPPED: "not reached"}.get(s.state, "not yet")
        label = s.note if s.key == "final" and s.note else s.label
        dt = f'<span class="dt">{e(fmt_date(s.date, date_only=True, with_weekday=False))}</span>' if s.date and s.state in (DONE, FAILED, CURRENT) else ""
        items.append(f'<li class="{cls}"><span>{e(label)}</span><span class="sr-only" style="position:absolute;left:-9999px">({sr})</span>{dt}</li>')
    return f'<ol class="nw-path" aria-label="Where this bill is in the process">{"".join(items)}</ol>'


def answers(blocks: list[tuple[str, str, bool]]) -> str:
    """blocks: (heading, html_value, wide)"""
    return '<div class="nw-answers">' + "".join(
        f'<div class="nw-q{" wide" if wide else ""}"><div class="k">{e(k)}</div><div class="v">{v}</div></div>'
        for k, v, wide in blocks
    ) + "</div>"


def evidence_quotes(evidence: list[dict], limit: int = 4) -> str:
    where_label = {"title": "official title", "summary": "official summary", "text": "bill text",
                   "century_code": "current law the bill changes", "ai": "AI suggestion (unverified)"}
    out = []
    for ev in evidence[:limit]:
        w = where_label.get(ev.get("where"), ev.get("where"))
        if ev.get("version"):
            w += f", version {ev['version']}"
        src = f" &middot; {link(ev.get('url'), 'open document')}" if ev.get("url") else ""
        out.append(f'<div class="nw-quote">{e(ev.get("snippet"))}<span class="w">Matched &ldquo;{e(ev.get("term"))}&rdquo; in the {e(w)}{src}</span></div>')
    return "".join(out)


def hearing_rows(items: list[dict], show_bill: bool = True) -> str:
    if not items:
        return ""
    out = []
    current_day = None
    for h in items:
        loc = utc_to_local(h["when"])
        day = loc.date()
        if day != current_day:
            current_day = day
            out.append(f'<div class="nw-day">{loc:%A}, {loc:%B} {loc.day}</div>')
        kind = "Public hearing" if h["public"] else f'{e(h["type"] or "Meeting")} (not a public hearing)'
        bill = f'<a class="nw-tag" href="{bill_href(h["uid"])}" target="_self">{e(h["bill"])}</a> ' if show_bill else ""
        where = " &middot; ".join(x for x in [e(h.get("committee")), f'Room {e(h["room"])}' if h.get("room") else ""] if x)
        links = link(h.get("hearing_url"), "Official hearing page")
        if h["public"] and h.get("testimony_url"):
            links += " &middot; " + link(h["testimony_url"], "Testimony already submitted")
        out.append(
            f'<div class="nw-hear"><div class="tm">{e(fmt_time(h["when"]))}</div><div>{bill}<b>{kind}</b>'
            f'<div>{e(h.get("summary") or "")}</div><div class="nw-row" style="border:none;padding:0;display:block"><div class="src">{where}<br>{links}</div></div></div></div>'
        )
    return "".join(out)


def month_calendar(year: int, month: int, counts: dict[date, int], today: date) -> str:
    cal = calendar.Calendar(firstweekday=6)  # Sunday first, as on US calendars
    cells = [f'<div class="hd">{d}</div>' for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]]
    for d in cal.itermonthdates(year, month):
        cls = []
        if d.month != month:
            cls.append("out")
        if counts.get(d):
            cls.append("has")
        if d == today:
            cls.append("today")
        n = counts.get(d)
        label = f"<b>{n} hearing{'s' if n != 1 else ''}</b>" if n else ""
        cells.append(f'<div class="{" ".join(cls)}" aria-label="{d:%B} {d.day}{": " + str(n) + " hearings" if n else ""}">{d.day}{label}</div>')
    return f'<div class="nw-cal">{"".join(cells)}</div>'


def week_window(now: datetime, days: int) -> tuple[datetime, datetime]:
    return now, now + timedelta(days=days)
