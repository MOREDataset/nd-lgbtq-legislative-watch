"""Command line entry point: `ndwatch <command>` (or `python -m ndwatch <command>`).

Commands
  init-db                 create tables
  monitor [--force]       run one monitoring cycle (what the scheduler calls)
  health                  exit 1 if monitoring is stale or the last run failed
  review list             bills waiting for a human decision
  review include|exclude  record a reviewer decision with a reason
  collect-samples DIR     save raw official responses for inspection/tests
  relevance-report CSV    write every bill's relevance result to a CSV file
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from ndwatch.config import load_settings
from ndwatch.db.schema import Bill, Relevance, ReviewDecision
from ndwatch.db.session import init_db, make_engine, session_factory
from ndwatch.timeutil import utcnow


def _factory(settings):
    engine = make_engine(settings.database_url)
    init_db(engine)
    return session_factory(engine)


def cmd_monitor(args, settings) -> int:
    from ndwatch.monitor import run_cycle
    from ndwatch.sources.http import HttpFetcher, ReplayFetcher

    factory = _factory(settings)
    fetcher = ReplayFetcher(args.replay) if args.replay else HttpFetcher(settings)
    report = run_cycle(
        factory, fetcher, settings, trigger=args.trigger, force=args.force,
        only_assemblies=args.assembly or None,
    )
    print(json.dumps(report.__dict__, indent=2, default=str))
    # Exit non-zero only if nothing could be read at all, so the scheduler flags it.
    return 1 if report.status == "failed" else 0


def cmd_health(args, settings) -> int:
    from ndwatch.monitor import STORAGE_WARN_MB, database_size_mb, monitor_health

    factory = _factory(settings)
    with factory() as db:
        h = monitor_health(db, settings)
        size = database_size_mb(db)
    h["database_size_mb"] = round(size) if size is not None else None
    print(json.dumps(h, indent=2, default=str))
    if size is not None and size > STORAGE_WARN_MB:
        print(f"Database is {size:.0f} MB, close to the free-tier limit (about 512 MB). "
              "See 'If the database fills up' in docs/DEPLOYMENT.md.", file=sys.stderr)
        return 1
    if h["last_ok_run"] is None:
        print("No successful monitoring run recorded yet.", file=sys.stderr)
        return 1
    if h["stale"]:
        print(f"Monitoring is stale: last success {h['minutes_since_ok']:.0f} minutes ago.", file=sys.stderr)
        return 1
    return 0


def cmd_review(args, settings) -> int:
    factory = _factory(settings)
    with factory() as db:
        if args.action == "list":
            decided = {d.bill_uid for d in db.scalars(select(ReviewDecision))}
            rows = db.execute(
                select(Bill, Relevance).join(Relevance, Relevance.bill_uid == Bill.uid)
                .where(Relevance.status == "possible").order_by(Relevance.score.desc())
            ).all()
            for bill, rel in rows:
                if bill.uid in decided:
                    continue
                print(f"{bill.uid:22} score {rel.score:3}  {', '.join(rel.topics)}  | {bill.summary or bill.title or ''}"[:200])
            return 0
        if not args.bill or not args.reason:
            print("--bill and --reason are required", file=sys.stderr)
            return 2
        if db.get(Bill, args.bill) is None:
            print(f"Unknown bill id {args.bill} (format: 202501:HB1144)", file=sys.stderr)
            return 2
        db.add(
            ReviewDecision(
                bill_uid=args.bill, decision=args.action, impact=args.impact, reason=args.reason,
                reviewer=args.reviewer, created_at=utcnow(),
            )
        )
        db.commit()
        print(f"Recorded: {args.action} {args.bill}")
        return 0


def cmd_collect_samples(args, settings) -> int:
    """Download a small set of raw official files (used to validate parsers)."""
    from ndwatch.sources.api import assemblies_url, assembly_url
    from ndwatch.sources.http import HttpFetcher, url_to_filename
    from ndwatch.sources.pages import PUBLIC_SCHEDULE_URL

    out = Path(args.directory)
    out.mkdir(parents=True, exist_ok=True)
    fetcher = HttpFetcher(settings)
    urls = [assemblies_url(), PUBLIC_SCHEDULE_URL]
    for year in args.assembly or ["69-2025"]:
        urls += [assembly_url(year, d) for d in ("sessions", "bills", "members", "committees", "roll_call")]
    urls += args.url or []
    manifest = []
    for url in urls:
        f = fetcher.get(url)
        name = url_to_filename(url)
        if f.ok:
            (out / name).write_bytes(f.content)
        manifest.append(
            {"url": url, "file": name, "ok": f.ok, "status": f.status, "bytes": len(f.content),
             "sha256": f.sha256 if f.ok else None, "fetched_at": f.fetched_at.isoformat(),
             "last_modified": f.last_modified, "content_type": f.content_type, "error": f.error}
        )
        print(f"{'OK ' if f.ok else 'ERR'} {f.status} {len(f.content):>10} {url}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0 if all(m["ok"] for m in manifest) else 1


def cmd_relevance_report(args, settings) -> int:
    """One row per bill: status, score, topics and the strongest evidence (for tuning rules)."""
    import csv

    factory = _factory(settings)
    with factory() as db:
        rows = db.execute(
            select(Bill, Relevance).join(Relevance, Relevance.bill_uid == Bill.uid, isouter=True)
            .order_by(Bill.session_id, Bill.name)
        ).all()
        with open(args.output, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["bill", "session", "status", "score", "topics", "texts_read", "title_summary", "evidence"])
            for bill, rel in rows:
                ev = []
                for e in (rel.evidence if rel else [])[:6]:
                    ev.append(f"[{e.get('where')} w{e.get('weight')} {e.get('topic')}] {e.get('snippet', '')[:160]}")
                w.writerow([
                    bill.name, bill.session_id, rel.status if rel else "", rel.score if rel else "",
                    ";".join(rel.topics) if rel else "", len(rel.text_versions_used) if rel else 0,
                    (bill.summary or bill.title or "")[:300], " || ".join(ev),
                ])
    print(f"Wrote {len(rows)} bills to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="ndwatch")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    m = sub.add_parser("monitor")
    m.add_argument("--force", action="store_true", help="run even if not due by the polling policy")
    m.add_argument("--trigger", default="manual")
    m.add_argument("--assembly", action="append", help="limit to an assembly, e.g. 69-2025")
    m.add_argument("--replay", help="read saved responses from this directory instead of the network")
    sub.add_parser("health")
    r = sub.add_parser("review")
    r.add_argument("action", choices=["list", "include", "exclude"])
    r.add_argument("--bill", help="bill id, e.g. 202501:HB1430")
    r.add_argument("--reason")
    r.add_argument("--impact", choices=["expands", "restricts", "administrative", "mixed", "unclear"])
    r.add_argument("--reviewer")
    c = sub.add_parser("collect-samples")
    c.add_argument("directory")
    c.add_argument("--assembly", action="append")
    c.add_argument("--url", action="append")
    rr = sub.add_parser("relevance-report")
    rr.add_argument("output")
    args = p.parse_args(argv)
    settings = load_settings()
    if args.cmd == "init-db":
        _factory(settings)
        print("Database ready.")
        return 0
    return {
        "monitor": cmd_monitor,
        "health": cmd_health,
        "review": cmd_review,
        "collect-samples": cmd_collect_samples,
        "relevance-report": cmd_relevance_report,
    }[args.cmd](args, settings)


if __name__ == "__main__":
    sys.exit(main())
