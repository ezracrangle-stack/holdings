"""Weekly check that every link from this site to letters.ezrasnotes.com works.
Writes links-alert.md when one fails, so the workflow can open an issue.

Usage: python scripts/check_links.py   (after scripts/build.py)
"""
import pathlib
import re
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALERT = ROOT / "links-alert.md"
PATTERN = re.compile(r'href="(https://letters\.ezrasnotes\.com/[^"#]*)"')


def main():
    links = {}
    for f in (ROOT / "docs").rglob("*.html"):
        for url in PATTERN.findall(f.read_text(encoding="utf-8")):
            links.setdefault(url, f.relative_to(ROOT / "docs").as_posix())
    s = requests.Session()
    s.headers["User-Agent"] = "EzrasNotesHoldingsBot/1.0 (+https://holdings.ezrasnotes.com/about.html)"
    bad = []
    for url, page in sorted(links.items()):
        try:
            r = s.head(url, timeout=30, allow_redirects=True)
            if r.status_code >= 400:
                r = s.get(url, timeout=30)
            if r.status_code >= 400:
                bad.append(f"- {url} answered {r.status_code} (linked from /{page})")
        except requests.RequestException as e:
            bad.append(f"- {url} didn't answer ({e.__class__.__name__}, linked from /{page})")
        time.sleep(0.5)
    if bad:
        ALERT.write_text("These links to Investor Letters don't work:\n\n" + "\n".join(bad)
                         + "\n\nUsually a manager or company changed its id on the letters site. "
                           "Match the id in managers.yaml or data/securities.yaml.\n", encoding="utf-8")
    elif ALERT.exists():
        ALERT.unlink()
    print(f"Checked {len(links)} links, {len(bad)} broken")


if __name__ == "__main__":
    main()
