"""Copy real early-signal pages from collected samples into tests/fixtures/signals_real/.

Usage: python scripts/build_signal_fixtures.py SAMPLES_DIR [SAMPLES_DIR ...]
Each SAMPLES_DIR is a checkout of the `source-samples` branch (gzipped files + manifest.json).
"""

import json
import shutil
import sys
from pathlib import Path

WANTED = [
    "https://ndlegis.gov/assembly/69-2025/committees/interim",
    "https://ndlegis.gov/assembly/69-2025/committees/interim/human-services-committee",
    "https://ndlegis.gov/assembly/69-2025/committees/interim/health-care-committee",
    "https://ndlegis.gov/assembly/69-2025/committees/interim/judiciary-committee",
    "https://ndlegis.gov/assembly/69-2025/committees/interim/education-committee",
    "https://ndlegis.gov/assembly/69-2025/committees/interim/administrative-rules-committee",
    "https://ndlegis.gov/sites/default/files/pdf/committees/69-2025/27.0221.01000.pdf",
    "https://ndlegis.gov/events/agency-hearings",
    "https://ndlegis.gov/events/2026/10/13/department-environmental-quality",
    "https://ndlegis.gov/events/2026/09/09/department-public-instruction",
    "https://ndlegis.gov/events/2026/09/18/dhhs-foster-homes-adults",
    "https://www.sos.nd.gov/elections/voter/ballot-measures/measures-ballot",
    "https://www.sos.nd.gov/elections/voter/ballot-measures/petitions-circulation",
    "https://translegislation.com/bills/2025/ND",
    "https://translegislation.com/bills/2023/ND",
    "https://www.aclu.org/legislative-attacks-on-lgbtq-rights-2025?state=ND",
]


def main(dirs: list[str]) -> None:
    out = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "signals_real"
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, dict] = {}
    for d in dirs:
        for m in json.loads((Path(d) / "manifest.json").read_text()):
            src = Path(d) / (m["file"] + ".gz")
            if m["url"] in WANTED and m["ok"] and src.exists():
                shutil.copy(src, out / src.name)
                found[m["url"]] = {"file": src.name, "fetched_at": m["fetched_at"], "sha256": m["sha256"]}
    missing = [u for u in WANTED if u not in found]
    (out / "PROVENANCE.json").write_text(json.dumps(
        {"note": "Real pages from official sources (and two advocacy trackers), unmodified, gzipped.",
         "files": found}, indent=2))
    print(f"{len(found)} files written; missing: {missing}")


if __name__ == "__main__":
    main(sys.argv[1:])
