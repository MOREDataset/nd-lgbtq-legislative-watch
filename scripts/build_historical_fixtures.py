"""Build tests/fixtures/historical from raw samples saved by the "Collect source samples" workflow.

Usage: python scripts/build_historical_fixtures.py <samples_dir>

Keeps real records only for a few 2025 bills, unchanged except for removing
other bills, and records where and when each file came from.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from ndwatch.sources.http import url_to_filename

BILLS = ["HB 1144", "HB 1217", "HB 1430", "SB 2307", "HB 1001", "SB 2392"]
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "historical"
API = "https://ndlegis.gov/api/assembly/69-2025/data"


def main(src: Path) -> None:
    manifest = {m["url"]: m for m in json.loads((src / "manifest.json").read_text())}
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.gz"):
        old.unlink()
    provenance = []

    def save(url: str, content: bytes, note: str = "") -> None:
        (OUT / (url_to_filename(url) + ".gz")).write_bytes(gzip.compress(content, mtime=0))
        m = manifest.get(url, {})
        provenance.append({"url": url, "retrieved_at": m.get("fetched_at"), "original_sha256": m.get("sha256"),
                           "note": note})

    def raw(url: str) -> bytes:
        return (src / url_to_filename(url)).read_bytes()

    for name in ("sessions", "members"):
        save(f"{API}/{name}.json", raw(f"{API}/{name}.json"))
    save("https://ndlegis.gov/api/data/assemblies.json", raw("https://ndlegis.gov/api/data/assemblies.json"))

    bills = json.loads(raw(f"{API}/bills.json"))
    keep = {k: v for k, v in bills["bills"].items() if v["name"] in BILLS and v.get("session_id") == "202501"}
    bills["bills"] = keep
    save(f"{API}/bills.json", json.dumps(bills).encode(), note=f"subset: {', '.join(BILLS)} (2025 Regular Session)")

    rc = json.loads(raw(f"{API}/roll_call.json"))
    rc["roll_call"] = [r for r in rc["roll_call"] if r.get("bill") in BILLS and r.get("session_id") == "202501"]
    save(f"{API}/roll_call.json", json.dumps(rc).encode(), note="subset: roll calls for the bills above")

    for f in sorted(src.iterdir()):
        url = next((u for u in manifest if url_to_filename(u) == f.name), None)
        if url and ("bill-testimony" in url or url.endswith(".pdf") or "public-schedule" in url):
            save(url, f.read_bytes())

    (OUT / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    total = sum(p.stat().st_size for p in OUT.glob("*.gz"))
    print(f"wrote {len(provenance)} files, {total / 1024:.0f} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
