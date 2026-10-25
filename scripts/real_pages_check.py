"""False-alarm check on ~240 saved real web pages (Mozilla Readability test pages + Trafilatura's cache).

    python3 scripts/real_pages_check.py               # clones the two repos into ../data_src if missing
    python3 scripts/real_pages_check.py --json out.json

Runs analyze_html + _judge with PatternDetector + MLDetector on every page, under the web rules (how the
extension and URL scans judge live pages) and the email rules (saved .html/.eml files), and prints
clean/yellow/red counts, the most common reasons, and the slowest pages. These are ordinary pages, so
every red or yellow is a false alarm to look at.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parallax.detect import MLDetector, PatternDetector  # noqa: E402
from parallax.gap.html_gap import analyze_html  # noqa: E402
from parallax.scan import _judge  # noqa: E402

DATA = Path(os.environ.get("PARALLAX_DATA", ROOT.parent / "data_src"))
REPOS = {"readability": ("https://github.com/mozilla/readability", "test/test-pages/*/source.html"),
         "trafilatura": ("https://github.com/adbar/trafilatura", "tests/cache/*.html")}


def pages():
    for name, (url, pattern) in REPOS.items():
        if not (DATA / name).exists():
            subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(DATA / name)], check=True)
        yield from sorted((DATA / name).glob(pattern))


def verdict(findings):
    levels = {f.level for f in findings}
    return "red" if "threat" in levels else "yellow" if "caution" in levels else "clean"


def reason(why: str) -> str:   # "adds a hidden link: https://x" -> "adds a hidden link"
    return re.sub(r"\s*[:(].*$", "", why)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write per-page results here")
    a = ap.parse_args()
    dets = [PatternDetector(), MLDetector()]
    counts = {"web": Counter(), "email": Counter()}
    reasons = {"web": Counter(), "email": Counter()}
    times, rows = [], []
    for p in pages():
        html = p.read_text(errors="replace")
        t0 = time.time()
        res = analyze_html(html)
        secs = time.time() - t0
        times.append((secs, p, len(html)))
        row = {"page": str(p.relative_to(DATA)), "seconds": round(secs, 2)}
        for mode, web in (("web", True), ("email", False)):
            found = _judge(res["hidden"], res["visible_text"], dets, long_passage_caution=not web, web=web)
            v = verdict(found)
            counts[mode][v] += 1
            row[mode] = v
            for f in found:
                if f.level != "info":
                    for w in f.why:
                        reasons[mode][f"{f.level}: {reason(w)}"] += 1
        rows.append(row)
    n = len(rows)
    print(f"{n} pages")
    for mode in ("web", "email"):
        c = counts[mode]
        print(f"\n{mode} rules: {c['clean']} clean / {c['yellow']} yellow / {c['red']} red")
        for r, k in reasons[mode].most_common(8):
            print(f"   {k:4d}  {r}")
    times.sort(key=lambda t: -t[0])
    print("\nslowest pages (analyze_html):")
    for secs, p, size in times[:5]:
        print(f"   {secs:6.2f}s  {size / 1024:6.0f} KB  {p.relative_to(DATA)}")
    print(f"median {sorted(t[0] for t in times)[n // 2]:.2f}s, total {sum(t[0] for t in times):.0f}s")
    if a.json:
        json.dump({"counts": counts, "rows": rows}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
