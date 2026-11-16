"""Build the static site into docs/ from managers.yaml and data/."""
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import sys
from email.utils import format_datetime
from xml.sax.saxutils import escape

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import portfolio as P  # noqa: E402

ROOT = P.ROOT
OUT = ROOT / "docs"
SITE_URL = "https://holdings.ezrasnotes.com"
LETTERS_URL = "https://letters.ezrasnotes.com"
GA_ID = ""  # Google Analytics stream for this site. Empty string turns it off.
NEWSLETTER_URL = "https://www.ezrasnotes.com"
SUBSCRIBE_URL = "https://www.ezrasnotes.com"
MOVES_ON_HOME = 40
ALERT_FILE = ROOT / "alert.md"


def money(v):
    v = v or 0
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def pct(x, signed=False):
    if x is None:
        return ""
    s = f"{x * 100:+.0f}%" if signed else f"{x * 100:.1f}%"
    return s.replace("-", "−")


def pretty_date(iso):
    if not iso:
        return ""
    d = dt.date.fromisoformat(iso[:10])
    return d.strftime("%B %-d, %Y")


def short_date(iso):
    return dt.date.fromisoformat(iso[:10]).strftime("%b %-d, %Y") if iso else ""


def move_label(c):
    """Same words as most 13F trackers: Buy, Add, Reduce, Sell."""
    k = c["kind"]
    if k == "new":
        return "Buy"
    if k == "sold":
        return "Sell"
    if k == "first":
        return "First 13F"
    if k == "same" or c.get("pct") is None:
        return "No change"
    return f"{'Add' if k == 'added' else 'Reduce'} {abs(c['pct']) * 100:.0f}%"


def price(v):
    return f"${v:,.2f}" if v else ""


STEPS = [(0.20, 6), (0.15, 5), (0.10, 4), (0.05, 3), (0.025, 2), (0, 1)]
STEP_LABELS = ["Under 2.5%", "2.5-5%", "5-10%", "10-15%", "15-20%", "20%+"]
SECTOR_STEPS = [(0.50, 6), (0.40, 5), (0.30, 4), (0.20, 3), (0.10, 2), (0, 1)]
SECTOR_LABELS = ["Under 10%", "10-20%", "20-30%", "30-40%", "40-50%", "50%+"]


def calendar(m):
    """Every quarter-end from the first 13F to the last, including quarters with no filing."""
    first, last = m["quarters"][0]["period"], m["quarters"][-1]["period"]
    by = {q["period"]: q for q in m["quarters"]}
    y, mo = int(first[:4]), int(first[5:7])
    cols = []
    while True:
        end = dt.date(y, mo, 30 if mo in (6, 9) else 31).isoformat()
        cols.append({"period": end, "label": P.quarter_label(end), "q": by.get(end)})
        if end >= last:
            return cols
        mo += 3
        if mo > 12:
            mo, y = mo - 12, y + 1


def spread(m, cols, values):
    """Values per filed quarter → values per calendar column (None = no 13F that quarter)."""
    idx = {q["period"]: i for i, q in enumerate(m["quarters"])}
    return [values[idx[c["period"]]] if c["q"] else None for c in cols]


def timeline(m):
    """Grid for the manager's chart: one row per holding, one column per quarter,
    shaded by weight. Rows: current holdings by weight, then past ones, most recent first."""
    quarters = m["quarters"]
    rows = {}
    for i, q in enumerate(quarters):
        for p in q["positions"]:
            key = p["slug"] + ("|" + p["put_call"] if p["put_call"] else "")
            r = rows.setdefault(key, {"name": p["name"] + (f" ({p['put_call'].lower()}s)" if p["put_call"] else ""),
                                      "slug": p["slug"], "fund": p["fund"], "ticker": p["ticker"],
                                      "cells": [0.0] * len(quarters), "last": i})
            r["cells"][i] += p["weight"]
            r["last"] = i
    last = len(quarters) - 1
    out = sorted(rows.values(), key=lambda r: (r["last"] != last, -r["cells"][last] if r["last"] == last else -r["last"]))
    if m.get("top"):                       # diversified 13Fs: only today's biggest positions
        out = [r for r in out if r["last"] == last][:m["top"]]
    cols = calendar(m)
    for r in out:
        r["cells"] = spread(m, cols, r["cells"])
        r["steps"] = [None if w is None else next(n for t, n in STEPS if w >= t) if w > 0 else 0 for w in r["cells"]]
        r["current"] = r["last"] == last
    return out


def sector_grid(m):
    """Rows: sectors, ordered by latest weight then by most recent quarter held. Same steps as the holdings grid."""
    quarters = m["quarters"]
    rows = {}
    for i, q in enumerate(quarters):
        for name, w in q["sectors"]:
            r = rows.setdefault(name, {"name": name, "cells": [0.0] * len(quarters), "last": i})
            r["cells"][i] = w
            r["last"] = i
    last = len(quarters) - 1
    out = sorted(rows.values(), key=lambda r: (r["last"] != last, -r["cells"][last] if r["last"] == last else -r["last"]))
    cols = calendar(m)
    for r in out:
        r["cells"] = spread(m, cols, r["cells"])
        r["steps"] = [None if w is None else next(n for t, n in SECTOR_STEPS if w >= t) if w > 0 else 0 for w in r["cells"]]
        r["current"] = r["last"] == last
        r["fund"] = True          # no link
    return out


UTM = "utm_source=holdings.ezrasnotes.com&utm_medium=referral"


def load_posts():
    path = ROOT / "data" / "posts.yaml"
    posts = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    for p in posts or []:
        p["date"] = str(p["date"])
        p["href"] = p["url"] + ("&" if "?" in p["url"] else "?") + UTM
        p.setdefault("managers", [])
        p.setdefault("companies", [])
    return sorted(posts or [], key=lambda p: p["date"], reverse=True)


def load_managers():
    config = yaml.safe_load((ROOT / "managers.yaml").read_text(encoding="utf-8"))
    lpath = ROOT / "data" / "letters_index.json"
    letters = json.loads(lpath.read_text(encoding="utf-8")) if lpath.exists() else {"companies": [], "managers": {}}
    managers = []
    for m in config["managers"]:
        m = dict(m)
        lid = m.get("letters")
        lid = m["id"] if lid in (True, "yes") else lid if isinstance(lid, str) and lid != "no" else None
        on_letters = lid in letters["managers"]
        m["letters_url"] = f"{LETTERS_URL}/m/{lid}.html" if on_letters else None
        if on_letters and not m.get("why"):
            m["why"] = letters["managers"][lid]["why"]
        managers.append(m)
    unknown, warnings = P.load(managers)
    managers = [m for m in managers if m["latest"]]
    managers.sort(key=lambda m: m["name"].split()[-1].lower())
    return managers, set(letters["companies"]), unknown, warnings


def build_companies(managers, letters_companies):
    """Every company any manager has held, with current and past holders."""
    companies = {}
    for m in managers:
        for q in m["quarters"]:
            for p in q["positions"]:
                if p["fund"]:
                    continue
                c = companies.setdefault(p["slug"], {"slug": p["slug"], "name": p["name"], "tickers": set(),
                                                     "now": {}, "past": {}})
                if p["ticker"]:
                    c["tickers"].add(p["ticker"])
                c["past"][m["id"]] = {"m": m, "last": q}
        for p in m["latest"]["positions"]:
            if p["fund"]:
                continue
            c = companies[p["slug"]]
            row = c["now"].setdefault(m["id"], {"m": m, "weight": 0, "value": 0, "since": p["since"],
                                                "since_label": p["since_label"],
                                                "first_filing": p["first_filing"], "lines": []})
            row["weight"] += p["weight"]
            row["value"] += p["value"]
            row["lines"].append(p)
            if p["since"] < row["since"]:
                row.update(since=p["since"], since_label=p["since_label"], first_filing=p["first_filing"])
            chg = next((x for x in m["latest"]["changes"] if x["key"] == p["key"]), None)
            row["move"] = move_label(chg) if chg else ""
    for c in companies.values():
        for mid in c["now"]:
            c["past"].pop(mid, None)
        c["now"] = sorted(c["now"].values(), key=lambda r: -r["weight"])
        c["past"] = sorted(c["past"].values(), key=lambda r: r["last"]["period"], reverse=True)
        c["tickers"] = sorted(c["tickers"])
        c["letters_url"] = f"{LETTERS_URL}/c/{c['slug']}.html" if c["slug"] in letters_companies else None
        c["holders"] = len(c["now"])
        c["avg_weight"] = sum(r["weight"] for r in c["now"]) / len(c["now"]) if c["now"] else 0
    return companies


def build():
    managers, letters_companies, unknown, warnings = load_managers()
    companies = build_companies(managers, letters_companies)
    posts = load_posts()
    by_id = {m["id"]: m for m in managers}
    for m in managers:
        m["posts"] = [p for p in posts if m["id"] in p["managers"]]
    for c in companies.values():
        c["posts"] = [p for p in posts if c["slug"] in p["companies"]]
    bad_refs = [f"{p['title']}: {x}" for p in posts for x in p["managers"] if x not in by_id] + \
               [f"{p['title']}: {x}" for p in posts for x in p["companies"] if x not in companies]
    shared = sorted((c for c in companies.values() if c["holders"]),
                    key=lambda c: (-c["holders"], -c["avg_weight"], c["name"]))
    former = sorted((c for c in companies.values() if not c["holders"]), key=lambda c: c["name"].lower())

    # latest filings and the big moves in each manager's latest 13F
    filings = sorted(((m, q) for m in managers for q in m["quarters"]),
                     key=lambda x: (x[1]["filed"], x[1]["period"]), reverse=True)
    latest_filings = sorted(((m, m["latest"]) for m in managers),
                            key=lambda x: (x[1]["filed"], x[0]["name"]), reverse=True)
    moves = []
    for m, q in latest_filings:
        for c in q["changes"]:
            if P.is_big(c):
                moves.append({"m": m, "q": q, "c": c})
    # biggest positions first; moves in positions under 0.5% of the 13F are left off the home page
    moves = [x for x in moves if max(x["c"]["weight"], x["c"]["prev_weight"]) >= 0.005]
    moves.sort(key=lambda x: -max(x["c"]["weight"], x["c"]["prev_weight"]))
    groups = [(k, label, [x for x in moves if x["c"]["kind"] == k][:MOVES_ON_HOME])
              for k, label in (("new", "New positions"), ("sold", "Sold out"),
                               ("added", "Big increases"), ("trimmed", "Big reductions"))]

    run_path = ROOT / "data" / "last_run.json"
    last_run = json.loads(run_path.read_text(encoding="utf-8")).get("last_run") if run_path.exists() else None

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    env.filters.update(money=money, pct=pct, date=pretty_date, short=short_date, move=move_label, price=price)
    asset_v = hashlib.md5(b"".join((ROOT / "static" / f).read_bytes()
                                   for f in ("style.css", "holdings.css", "search.js"))).hexdigest()[:8]
    common = dict(asset_v=asset_v, ga_id=GA_ID, site_url=SITE_URL, letters_url=LETTERS_URL,
                  newsletter_url=NEWSLETTER_URL, subscribe_url=SUBSCRIBE_URL, updated=pretty_date(last_run),
                  manager_count=len(managers))

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "m").mkdir(parents=True)
    (OUT / "c").mkdir()
    shutil.copytree(ROOT / "static", OUT / "static")
    shutil.copy(ROOT / "static" / "favicon.ico", OUT / "favicon.ico")

    def render(template, path, root, **kw):
        out = OUT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(env.get_template(template).render(root=root, page=path, **common, **kw), encoding="utf-8")

    render("index.html", "index.html", "", latest_filings=latest_filings, groups=groups, posts=posts[:3],
           managers=managers, shared=shared[:30], has_moves=bool(moves))
    render("directory.html", "managers.html", "", managers=managers)
    render("companies.html", "companies.html", "", shared=shared, former=former)
    render("about.html", "about.html", "")
    render("search.html", "search.html", "")
    (OUT / "search.json").write_text(json.dumps({
        "managers": [{"n": m["name"], "f": m["firm"], "s": " ".join(x for x in (m.get("style"), m.get("why")) if x), "u": f"m/{m['id']}.html"}
                     for m in managers],
        "companies": [{"n": c["name"], "t": " ".join(c["tickers"]), "h": c["holders"], "u": f"c/{c['slug']}.html"}
                      for c in sorted(companies.values(), key=lambda c: (-c["holders"], c["name"]))],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    render("404.html", "404.html", "/")
    for m in managers:
        render("manager.html", f"m/{m['id']}.html", "../", m=m, q=m["latest"], companies=companies,
               grid=timeline(m), sgrid=sector_grid(m), cols=calendar(m), step_labels=STEP_LABELS, sector_labels=SECTOR_LABELS)
        render("activity.html", f"m/{m['id']}/activity.html", "../../", m=m, companies=companies)
        for h in m["history"].values():
            render("stock_history.html", f"m/{m['id']}/stock/{h['slug']}.html", "../../../", m=m, h=h,
                   companies=companies)
        for q in m["quarters"]:
            render("quarter.html", f"m/{m['id']}/{q['slug']}.html", "../../", m=m, q=q, companies=companies)
    for c in companies.values():
        render("company.html", f"c/{c['slug']}.html", "../", c=c)

    for m in managers:                       # old addresses keep working
        for old in m.get("old_ids") or []:
            for src, dst in [(f"m/{old}.html", f"/m/{m['id']}.html"),
                             (f"m/{old}/activity.html", f"/m/{m['id']}/activity.html")] + \
                            [(f"m/{old}/{q['slug']}.html", f"/m/{m['id']}/{q['slug']}.html") for q in m["quarters"]] + \
                            [(f"m/{old}/stock/{h}.html", f"/m/{m['id']}/stock/{h}.html") for h in m["history"]]:
                out = OUT / src
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(f'<!DOCTYPE html><meta charset="utf-8"><title>Moved</title>'
                               f'<link rel="canonical" href="{SITE_URL}{dst}">'
                               f'<meta name="robots" content="noindex">'
                               f'<meta http-equiv="refresh" content="0; url={dst}">'
                               f'<p>This page moved to <a href="{dst}">{SITE_URL}{dst}</a>.</p>\n', encoding="utf-8")
    write_feed(filings)
    write_sitemap()
    (OUT / "CNAME").write_text("holdings.ezrasnotes.com\n")
    (OUT / ".nojekyll").write_text("")

    notes = []
    if unknown:
        notes.append("These 13F lines have no company name or ticker yet. Add them to data/securities.yaml:\n"
                     + "\n".join(f"- `{k}`: {v}" for k, v in sorted(unknown.items())))
    nosector = sorted({p["name"] for m in managers for p in m["latest"]["positions"] if p["sector"] == "Unclassified"})
    if nosector:
        notes.append("These holdings have no sector yet. Add their SIC code (it's on their EDGAR page) "
                     "to data/securities.yaml: " + ", ".join(nosector))
    if bad_refs:
        notes.append("data/posts.yaml points to managers or companies the site doesn't have "
                     "(check the spelling):\n" + "\n".join(f"- {b}" for b in bad_refs))
    if warnings:
        notes.append("\n".join(f"- {w}" for w in warnings))
    if notes:
        with ALERT_FILE.open("a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("The EDGAR check found something that needs a look:\n")
            f.write("\n" + "\n\n".join(notes) + "\n")
    print(f"Built {len(managers)} managers, {len(companies)} companies into docs/")


def write_sitemap():
    urls = []
    for f in sorted(OUT.rglob("*.html")):
        rel = f.relative_to(OUT).as_posix()
        if rel != "404.html" and 'http-equiv="refresh"' not in f.read_text(encoding="utf-8")[:400]:
            urls.append(f"{SITE_URL}/" + ("" if rel == "index.html" else rel))
    body = "\n".join(f"  <url><loc>{escape(u)}</loc></url>" for u in urls)
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     f"{body}\n</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")


def write_feed(filings):
    """RSS: one item per 13F, newest filing first. The first import is left out so
    readers aren't flooded, except to fill the feed up to 20 items while it's new."""
    fresh = [x for x in filings if not x[1]["backfill"]]
    if len(fresh) < 20:
        fresh += [x for x in filings if x[1]["backfill"]][: 20 - len(fresh)]
    items = []
    for m, q in fresh[:50]:
        when = dt.datetime.fromisoformat(q["first_seen"] or q["filed"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        big = [c for c in q["changes"] if P.is_big(c)]
        summary = "; ".join(f"{c['name']}: {move_label(c).lower()}" for c in big[:8]) or "No big changes."
        url = f"{SITE_URL}/m/{m['id']}/{q['slug']}.html"
        items.append(f"""  <item>
    <title>{escape(f"{m['name']} ({m['firm']}): 13F for {q['label']}")}</title>
    <link>{url}</link>
    <guid isPermaLink="true">{url}</guid>
    <pubDate>{format_datetime(when)}</pubDate>
    <description>{escape(f"{q["total_positions"]:,} positions, {money(q["total"])}. {summary}")}</description>
  </item>""")
    newest = max((q["filed"] for _, q in filings), default="2026-01-01")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>Investor Holdings · Ezra's Notes</title>
  <link>{SITE_URL}/</link>
  <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
  <description>New 13F filings from the value investors Ezra follows.</description>
  <language>en</language>
  <lastBuildDate>{format_datetime(dt.datetime.fromisoformat(newest).replace(tzinfo=dt.timezone.utc))}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""
    (OUT / "feed.xml").write_text(feed, encoding="utf-8")


if __name__ == "__main__":
    build()
