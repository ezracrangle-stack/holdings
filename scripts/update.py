"""Check SEC EDGAR for new 13F filings and save them to data/filings/.
Never deletes anything already saved.

The SEC asks every automated visitor to say who they are. Set the
SEC_USER_AGENT environment variable to "Name email@example.com"
(in GitHub: Settings > Secrets and variables > Actions > Variables).

Usage:
  python scripts/update.py
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FILINGS = DATA / "filings"
RUN_FILE = DATA / "last_run.json"
LETTERS_FILE = DATA / "letters_index.json"
LETTERS_SITE = "https://letters.ezrasnotes.com"
LETTERS_YAML = "https://raw.githubusercontent.com/ezracrangle-stack/letters/main/managers.yaml"
ALERT_FILE = ROOT / "alert.md"

MIN_GAP = 0.25          # seconds between requests: 4 per second, the SEC allows 10
TIMEOUT = 30
FORMS = {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}
DOLLARS_FROM = "2023-01-03"   # before this date, 13F values were in thousands of dollars
GRACE_DAYS = 52               # 45-day deadline + weekends/holidays + a few days of slack


class Edgar:
    def __init__(self):
        ua = os.environ.get("SEC_USER_AGENT", "").strip()
        if "@" not in ua:
            sys.exit("SEC_USER_AGENT is missing. The SEC requires a name and an email, "
                     "e.g. SEC_USER_AGENT='Ezra Notes you@example.com'.")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.last = 0.0

    def get(self, url):
        for attempt in range(4):
            wait = MIN_GAP - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = self.s.get(url, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))     # network hiccup: wait and try again
                continue
            if r.status_code in (429, 503):       # SEC says slow down
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()


def strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def text(el, path, default=None):
    x = el.find(path)
    return x.text.strip() if x is not None and x.text else default


def mdy_to_iso(s):
    m, d, y = s.split("-")
    return f"{y}-{m}-{d}"


def list_filings(edgar, cik):
    """Every 13F the firm filed, oldest first."""
    sub = edgar.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        blocks.append(edgar.get(f"https://data.sec.gov/submissions/{f['name']}").json())
    out = []
    for b in blocks:
        for i, form in enumerate(b["form"]):
            if form in FORMS:
                out.append({"accession": b["accessionNumber"][i], "form": form,
                            "filed": b["filingDate"][i], "period": b["reportDate"][i]})
    return sub["name"], sorted(out, key=lambda x: (x["filed"], x["accession"]))


def read_filing(edgar, cik, f):
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accession'].replace('-', '')}/"
    items = edgar.get(base + "index.json").json()["directory"]["item"]
    xmls = [i["name"] for i in items if i["name"].lower().endswith(".xml")]
    f["url"] = base + f"{f['accession']}-index.html"
    if "primary_doc.xml" not in xmls:
        f["skipped"] = "Filed before the SEC's XML format (2013). Not read."
        return f
    cover = strip_ns(ET.fromstring(edgar.get(base + "primary_doc.xml").content))
    f["period"] = mdy_to_iso(text(cover, ".//periodOfReport") or text(cover, ".//reportCalendarOrQuarter"))
    f["report_type"] = text(cover, ".//reportType")
    f["amendment_type"] = text(cover, ".//amendmentInfo/amendmentType")
    f["filer_name"] = text(cover, ".//filingManager/name")
    total = text(cover, ".//summaryPage/tableValueTotal")
    if f["form"].startswith("13F-NT") or (f["report_type"] or "").upper().startswith("13F NOTICE"):
        f["holdings"] = []
        return f
    table = [x for x in xmls if x != "primary_doc.xml"]
    if not table:
        raise RuntimeError("no information table in the filing")
    root = strip_ns(ET.fromstring(edgar.get(base + table[0]).content))
    k = 1 if f["filed"] >= DOLLARS_FROM else 1000
    rows = {}
    for t in root.iter("infoTable"):
        key = (text(t, "cusip").upper(), (text(t, "putCall") or "").title())
        r = rows.setdefault(key, {"cusip": key[0], "put_call": key[1] or None,
                                   "issuer": text(t, "nameOfIssuer"), "class": text(t, "titleOfClass"),
                                   "shares": 0, "unit": text(t, "shrsOrPrnAmt/sshPrnamtType"), "value": 0})
        r["shares"] += int(float(text(t, "shrsOrPrnAmt/sshPrnamt", "0")))
        r["value"] += int(float(text(t, "value", "0"))) * k
    f["holdings"] = sorted(rows.values(), key=lambda r: -r["value"])
    f["table_total"] = int(float(total)) * k if total else None
    return f


def refresh_letters_index():
    """Which managers and companies have a page on letters.ezrasnotes.com,
    and the "why I read" line of each manager. Kept from last time if the site can't be read."""
    s = requests.Session()
    s.headers["User-Agent"] = "EzrasNotesHoldingsBot/1.0 (+https://holdings.ezrasnotes.com/about.html)"
    sitemap = s.get(LETTERS_SITE + "/sitemap.xml", timeout=TIMEOUT)
    sitemap.raise_for_status()
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap.text)
    companies = sorted({m.group(1) for u in locs if (m := re.search(r"/c/(.+?)(?:-\d+)?\.html$", u))})
    managers_yaml = s.get(LETTERS_YAML, timeout=TIMEOUT)
    managers_yaml.raise_for_status()
    why = {m["id"]: {"why": m.get("why"), "name": m.get("name"), "firm": m.get("firm")}
           for m in yaml.safe_load(managers_yaml.text)["managers"]}
    pages = {m.group(1) for u in locs if (m := re.search(r"/m/(.+?)\.html$", u))}
    LETTERS_FILE.write_text(json.dumps({"companies": companies,
                                        "managers": {k: v for k, v in why.items() if k in pages}},
                                       indent=1, ensure_ascii=False), encoding="utf-8")


NEWSLETTER_FEED = "https://www.ezrasnotes.com/feed"
SEEN_FILE = DATA / "posts_seen.json"


def suggest_posts(config):
    """New Ezra's Notes posts that name a manager or a company on the site.
    Each post is suggested once; add the ones that fit to data/posts.yaml."""
    import html
    r = requests.get(NEWSLETTER_FEED, timeout=TIMEOUT,
                     headers={"User-Agent": "EzrasNotesHoldingsBot/1.0 (+https://holdings.ezrasnotes.com/about.html)"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    listed = {p["url"].split("?")[0] for p in (yaml.safe_load((DATA / "posts.yaml").read_text(encoding="utf-8")) or [])}
    seen = set(json.loads(SEEN_FILE.read_text(encoding="utf-8"))) if SEEN_FILE.exists() else None
    names = {}
    for m in config["managers"]:
        names[m["name"]] = f"manager `{m['id']}`"
        names[m["firm"]] = f"manager `{m['id']}`"
    secs = yaml.safe_load((DATA / "securities.yaml").read_text(encoding="utf-8")) or {}
    for v in secs.values():
        if not v.get("fund"):
            slug = re.sub(r"[^a-z0-9]+", "-", v["name"].lower()).strip("-")
            names[v["name"]] = f"company `{slug}`"
    out, links = [], []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").split("?")[0]
        links.append(link)
        if link in listed or (seen is not None and link in seen) or seen is None:
            continue
        text = html.unescape((item.findtext("title") or "") + " " + (item.findtext("description") or ""))
        hits = sorted({tag for name, tag in names.items() if re.search(r"\b" + re.escape(name) + r"\b", text)})
        if hits:
            out.append(f"- [{item.findtext('title')}]({link}) mentions {', '.join(hits)}. "
                       "If it belongs on the site, add it to data/posts.yaml.")
    SEEN_FILE.write_text(json.dumps(sorted((seen or set()) | set(links)), indent=1), encoding="utf-8")
    return out


def expected_period(today):
    """Latest quarter whose 13F deadline (plus slack) has passed."""
    q_ends = [dt.date(today.year - 1, 12, 31)] + [dt.date(today.year, m, d) for m, d in
                                                  ((3, 31), (6, 30), (9, 30), (12, 31))]
    done = [q for q in q_ends if today >= q + dt.timedelta(days=GRACE_DAYS)]
    return max(done).isoformat()


def main():
    config = yaml.safe_load((ROOT / "managers.yaml").read_text(encoding="utf-8"))
    FILINGS.mkdir(parents=True, exist_ok=True)
    edgar = Edgar()
    problems, new = [], []
    today = dt.date.today()
    for m in config["managers"]:
        path = FILINGS / f"{m['id']}.json"
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"filings": []}
        have = {f["accession"] for f in saved["filings"]}
        try:
            ciks = m["cik"] if isinstance(m["cik"], list) else [m["cik"]]   # a firm can file under more than one entity over time
            listed = []
            for cik in ciks:
                name, found = list_filings(edgar, int(cik))
                listed += [dict(f, cik=int(cik)) for f in found]
            saved["sec_name"] = name
            for f in sorted(listed, key=lambda f: (f["filed"], f["accession"])):
                if f["accession"] in have:
                    continue
                saved["filings"].append(read_filing(edgar, f["cik"], f))
                f["first_seen"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                f["backfill"] = not have
                new.append((m, f))
                print(f"  {m['id']}: {f['form']} for {f['period']} filed {f['filed']}")
        except Exception as e:                       # keep what we have, warn Ezra
            problems.append(f"- **{m['name']}** ({m['firm']}): couldn't read EDGAR ({e}). "
                            "Nothing was deleted; the site still shows the last good data.")
        saved["filings"].sort(key=lambda f: (f["filed"], f["accession"]))
        path.write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")

        hr = [f for f in saved["filings"] if f["form"].startswith("13F-HR")]
        last = max((f["period"] for f in hr), default=None)
        exp = expected_period(today)
        if last and last < exp:
            problems.append(f"- **{m['name']}** ({m['firm']}): no 13F for the quarter ending {exp} yet "
                            f"(latest is {last}). The firm may be late, below the $100M threshold, "
                            "or no longer filing. Nothing was deleted.")
        nts = [f for f in saved["filings"] if f["form"].startswith("13F-NT") and f["period"] == exp]
        if nts:
            problems.append(f"- **{m['name']}**: filed a 13F notice (13F-NT) for {exp}, which means "
                            "another firm reports the holdings. Check whether the CIK is still right.")

    try:
        refresh_letters_index()
    except Exception as e:
        problems.append(f"- Couldn't read letters.ezrasnotes.com to check which pages exist ({e}). "
                        "Links to the letters site use last week's list.")

    try:
        posts = suggest_posts(config)
        if posts:
            problems.append("New posts on Ezra's Notes that could link from this site:\n" + "\n".join(posts))
    except Exception as e:
        print(f"Couldn't read the Ezra's Notes feed: {e}")

    RUN_FILE.write_text(json.dumps({"last_run": dt.datetime.now(dt.timezone.utc)
                                    .isoformat(timespec="seconds")}), encoding="utf-8")
    if problems:
        ALERT_FILE.write_text("The EDGAR check found something that needs a look:\n\n"
                              + "\n".join(problems) + "\n", encoding="utf-8")
    elif ALERT_FILE.exists():
        ALERT_FILE.unlink()
    print(f"{len(new)} new filings, {len(problems)} problems")


if __name__ == "__main__":
    main()
