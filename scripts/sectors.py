"""Broad sectors from the SEC's industry codes (SIC), which EDGAR lists for every
company that files. The codes are old and a bit coarse (Amazon is "catalog and
mail-order retail"), so the groups are broad on purpose."""

FUNDS = "Funds & ETFs"
UNKNOWN = "Unclassified"

# (first SIC, last SIC, sector). First match wins, so narrow ranges go first.
RANGES = [
    (2830, 2836, "Health care"), (3841, 3851, "Health care"), (8000, 8099, "Health care"), (5122, 5122, "Health care"),
    (2000, 2199, "Consumer staples"), (2840, 2844, "Consumer staples"), (5400, 5499, "Consumer staples"),
    (5140, 5149, "Consumer staples"), (5180, 5182, "Consumer staples"),
    (3570, 3579, "Technology"), (3600, 3699, "Technology"), (3820, 3829, "Technology"),
    (7370, 7379, "Technology"), (3661, 3679, "Technology"),
    (4800, 4899, "Media & telecom"), (2700, 2799, "Media & telecom"), (7810, 7849, "Media & telecom"),
    (3711, 3711, "Consumer discretionary"), (3714, 3716, "Consumer discretionary"),
    (3940, 3949, "Consumer discretionary"), (2300, 2399, "Consumer discretionary"), (3140, 3149, "Consumer discretionary"),
    (5200, 5999, "Consumer discretionary"), (7200, 7299, "Consumer discretionary"), (3020, 3021, "Consumer discretionary"), (7000, 7099, "Consumer discretionary"), (7900, 7999, "Consumer discretionary"),
    (2510, 2599, "Consumer discretionary"), (3630, 3639, "Consumer discretionary"),
    (6500, 6799, "Financials & real estate"), (6000, 6499, "Financials & real estate"),
    (1300, 1399, "Energy"), (2900, 2999, "Energy"), (4920, 4925, "Energy"),
    (4900, 4991, "Utilities"),
    (1000, 1299, "Materials"), (1400, 1499, "Materials"), (2400, 2499, "Materials"), (2600, 2699, "Materials"),
    (2800, 2899, "Materials"), (3200, 3399, "Materials"),
    (1500, 1799, "Industrials"), (3400, 3599, "Industrials"), (3700, 3799, "Industrials"), (3800, 3899, "Industrials"),
    (4000, 4799, "Industrials"), (5000, 5199, "Industrials"), (7300, 7399, "Industrials"), (8700, 8799, "Industrials"),
]


def sector(sec):
    if not sec:
        return UNKNOWN
    if sec.get("sector"):
        return sec["sector"]
    if sec.get("fund"):
        return FUNDS
    code = sec.get("sic")
    if code is None:
        return UNKNOWN
    code = int(code)
    return next((name for lo, hi, name in RANGES if lo <= code <= hi), "Other")
