# Investor Holdings · Ezra's Notes

Static site at **holdings.ezrasnotes.com**: the 13F portfolios of the value investors Ezra follows, taken from SEC EDGAR.

- `managers.yaml` is the file to edit (see `COMO-EDITAR.md`).
- `data/securities.yaml` gives each CUSIP in a 13F a company name and ticker. `data/splits.yaml` lists stock splits.
- GitHub Actions runs `scripts/update.py` (new filings from EDGAR, never deletes) and `scripts/build.py` (writes the site to `docs/`): every 3 hours on days 1-20 of February, May, August and November, and every Monday the rest of the year.
- Problems open an issue labeled `holdings-alert`. A weekly job (`scripts/check_links.py`) checks links to letters.ezrasnotes.com and opens `links-alert` issues.
- The SEC asks for a contact in every request: set the `SEC_USER_AGENT` secret to "Name email".
- Manager and company pages use the same ids as letters.ezrasnotes.com (`/m/{id}.html`, `/c/{slug}.html`).
