"""Turn saved 13F filings into portfolios, weights and quarter-over-quarter changes."""
import datetime as dt
import json
import pathlib
import re
import unicodedata

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BIG_MOVE = 0.25            # a change of 25% or more in shares counts as "big" on the home page


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore")
                  .decode().lower()).strip("-")


def quarter_label(period):
    d = dt.date.fromisoformat(period)
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def quarter_slug(period):
    d = dt.date.fromisoformat(period)
    return f"{d.year}-q{(d.month - 1) // 3 + 1}"


def clean_issuer(s):
    s = re.sub(r"\b(INC|CORP|CORPORATION|CO|LTD|PLC|DEL|NEW|COM|HLDGS|S A|N V|SA|NV|AG|LP)\b\.?", "", s.upper())
    return " ".join(w.capitalize() for w in s.split()) or s


def load_securities():
    raw = yaml.safe_load((DATA / "securities.yaml").read_text(encoding="utf-8")) or {}
    return {str(k).upper(): v for k, v in raw.items()}


def effective_filings(filings):
    """One holdings list per quarter: the original 13F, then amendments in the order filed.
    A restatement replaces the quarter; a 'new holdings' amendment adds lines to it."""
    by_period = {}
    for f in sorted(filings, key=lambda f: (f["filed"], f["accession"])):
        if not f["form"].startswith("13F-HR") or f.get("skipped"):
            continue
        cur = by_period.get(f["period"])
        if cur is None or f["form"] == "13F-HR" or f.get("amendment_type") == "RESTATEMENT":
            by_period[f["period"]] = dict(f, holdings=list(f["holdings"]), amended=cur is not None)
        else:
            cur["holdings"] = cur["holdings"] + f["holdings"]
            cur["amended"] = True
            cur["filed_amendment"] = f["filed"]
    return [by_period[p] for p in sorted(by_period)]


def positions(filing, securities, unknown):
    """Lines of one quarter merged by company, ticker and put/call."""
    out = {}
    for r in filing["holdings"]:
        sec = securities.get(r["cusip"])
        if sec is None:
            unknown.setdefault(r["cusip"], r["issuer"])
            sec = {"name": clean_issuer(r["issuer"]), "ticker": None}
        key = (sec.get("ticker") or r["cusip"], r["put_call"])
        p = out.setdefault(key, {"key": "|".join(x or "" for x in key), "name": sec["name"],
                                  "slug": slugify(sec["name"]), "ticker": sec.get("ticker"),
                                  "fund": bool(sec.get("fund")), "put_call": r["put_call"],
                                  "class": r["class"], "unit": r["unit"], "shares": 0, "value": 0,
                                  "cusips": set()})
        p["shares"] += r["shares"]
        p["value"] += r["value"]
        p["cusips"].add(r["cusip"])
    total = sum(p["value"] for p in out.values()) or 1
    for p in out.values():
        p["weight"] = p["value"] / total
        p["cusips"] = sorted(p["cusips"])
    return sorted(out.values(), key=lambda p: -p["value"]), total


def load_splits():
    path = DATA / "splits.yaml"
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    return [dict(r, date=str(r["date"])) for r in rows or []]


def split_factor(splits, ticker, start, end):
    """Combined ratio of the listed splits between two quarter ends."""
    f = 1
    for s in splits:
        if s["ticker"] == ticker and start < s["date"] <= end:
            f *= s["ratio"]
    return f


def looks_like_split(prev, cur, factor):
    """Share count moved by about a whole-number multiple (2x, 3x, 10x, 1/10...) while the
    position's value barely changed, and no split is listed: worth a look."""
    if factor != 1 or not prev["shares"] or not cur["shares"] or not prev["value"]:
        return False
    r = cur["shares"] / prev["shares"]
    k = r if r >= 1 else 1 / r
    return k >= 1.9 and abs(k / round(k) - 1) < 0.03 and abs(cur["value"] / prev["value"] - 1) < 0.2


def changes(prev_q, cur_q, splits, warnings, who):
    prev_pos, cur_pos = prev_q["positions"], cur_q["positions"]
    prev = {p["key"]: p for p in prev_pos}
    cur = {p["key"]: p for p in cur_pos}
    out = []
    for k, p in cur.items():
        q = prev.get(k)
        if q is None:
            out.append(dict(p, kind="new", pct=None, prev_weight=0))
            continue
        f = split_factor(splits, p["ticker"], prev_q["period"], cur_q["period"])
        if cur_q.get("is_latest") and looks_like_split(q, p, f):
            warnings.append(f"{who}: {p['name']} shares went from {q['shares']:,} to {p['shares']:,} "
                            f"in {cur_q['label']} with little change in value. If that's a stock split, "
                            "add it to data/splits.yaml.")
        base = q["shares"] * f
        pct = p["shares"] / base - 1 if base else None
        kind = "added" if pct and pct > 0.005 else "trimmed" if pct and pct < -0.005 else "same"
        out.append(dict(p, kind=kind, pct=pct, split=f if f != 1 else None, prev_weight=q["weight"],
                        prev_shares=q["shares"]))
    for k, q in prev.items():
        if k not in cur:
            out.append(dict(q, kind="sold", pct=-1.0, prev_weight=q["weight"], weight=0, value=0, shares=0,
                            prev_shares=q["shares"]))
    order = {"new": 0, "added": 1, "trimmed": 2, "sold": 3, "same": 4}
    return sorted(out, key=lambda c: (order[c["kind"]], -(c["weight"] or c["prev_weight"])))


def is_big(c):
    return c["kind"] in ("new", "sold") or (c["pct"] is not None and abs(c["pct"]) >= BIG_MOVE)


def build_manager(m, saved, securities, unknown, splits, warnings):
    quarters = []
    for f in effective_filings(saved["filings"]):
        pos, total = positions(f, securities, unknown)
        quarters.append({"period": f["period"], "label": quarter_label(f["period"]),
                         "slug": quarter_slug(f["period"]), "filed": f["filed"], "url": f["url"],
                         "amended": f.get("amended"), "positions": pos, "total": total,
                         "first_seen": f.get("first_seen"), "backfill": f.get("backfill", True)})
    if quarters:
        quarters[-1]["is_latest"] = True
    for i, q in enumerate(quarters):
        q["changes"] = changes(quarters[i - 1], q, splits, warnings, m["name"]) if i else []
        q["prev"] = quarters[i - 1] if i else None
        # how long each position has been held without a break
        for p in q["positions"]:
            since = q["period"]
            for older in reversed(quarters[:i]):
                if any(o["key"] == p["key"] for o in older["positions"]):
                    since = older["period"]
                else:
                    break
            p["since"] = since
            p["since_label"] = quarter_label(since)
            p["first_filing"] = since == quarters[0]["period"]
    m["quarters"] = quarters
    m["latest"] = quarters[-1] if quarters else None
    return m


def load(managers):
    securities = load_securities()
    splits = load_splits()
    unknown, warnings = {}, []
    for m in managers:
        path = DATA / "filings" / f"{m['id']}.json"
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"filings": []}
        build_manager(m, saved, securities, unknown, splits, warnings)
    return unknown, warnings
