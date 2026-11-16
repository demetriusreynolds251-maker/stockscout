"""
scout_ceo.py — leadership background from PUBLIC RECORDS only.

What it does:
  1. Looks up the company's SEC id (CIK) from the ticker.
  2. Lists the latest proxy statements (DEF 14A) — the filing that holds
     each executive's work history, pay, and board seats.
  3. Lists recent 8-K filings — "something big happened" notices
     (CEO changes, mergers, lawsuits).
  4. Gives you ready-made search links for:
       - SEC enforcement actions (formal charges) with the CEO's name
       - Form 4 insider buys/sells for the company
       - Court records (PACER) and news
  5. Explains, in plain words, what to look for in each.

What it does NOT do: guess at character, repeat rumors, or label anyone
"shady". If it isn't in a public record, it isn't in this report.

The SEC asks for a real contact in the User-Agent header. Edit SEC_UA.
"""
import json
import os
import sys
import urllib.parse
import requests

SEC_UA = "StockScout research tool contact: your-email@example.com"  # <-- put your email here (SEC requires it)
HEADERS = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}


def lookup_cik(ticker):
    """Ticker -> 10-digit CIK string, via the SEC's public ticker list."""
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=30)
    r.raise_for_status()
    for row in r.json().values():
        if row.get("ticker", "").upper() == ticker.upper():
            return str(row["cik_str"]).zfill(10), row.get("title")
    return None, None


def recent_filings(cik, forms=("DEF 14A", "8-K", "10-K"), limit=6):
    """Return {form: [(date, description, url), ...]} for the forms we care about."""
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=HEADERS, timeout=30)
    r.raise_for_status()
    rec = r.json()["filings"]["recent"]
    out = {f: [] for f in forms}
    for form, date, acc, doc, desc in zip(rec["form"], rec["filingDate"], rec["accessionNumber"],
                                           rec["primaryDocument"], rec.get("primaryDocDescription", [""] * len(rec["form"]))):
        if form in out and len(out[form]) < limit:
            acc_nodash = acc.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}"
            out[form].append((date, desc or form, url))
    return out


def search_links(ceo_name, company_name, ticker, cik=None):
    q = urllib.parse.quote_plus
    links = {
        "SEC enforcement / litigation (formal charges)":
            f"https://www.sec.gov/litigation/litreleases?search={q(ceo_name)}",
        "SEC full-text search of all filings mentioning this name":
            f"https://efts.sec.gov/LATEST/search-index?q={q(chr(34)+ceo_name+chr(34))}",
        "Form 4 insider trades (buys/sells by executives)":
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik or ticker}&type=4&dateb=&owner=include&count=40",
        "FINRA BrokerCheck (if they were ever a licensed broker)":
            f"https://brokercheck.finra.org/search/genericsearch/grid?q={q(ceo_name)}",
        "Federal court records (PACER — paid, official)":
            "https://pcl.uscourts.gov/pcl/index.jsf",
        "News search": f"https://news.google.com/search?q={q(ceo_name + ' ' + company_name)}",
        "Wikipedia (check its sources, not just the text)": f"https://en.wikipedia.org/w/index.php?search={q(ceo_name)}",
    }
    return links


GUIDE = """
### How to read what you find (plain English)

**Proxy statement (DEF 14A)** — Look for the "Executive Officers" and "Director Biographies" sections.
They list every job the CEO held before, usually with dates. Then find "Summary Compensation Table"
for pay. Big pay tied to stock = they win when you win. Big guaranteed pay = they win regardless.
Also check "Related Party Transactions" — deals between the company and the CEO's friends/family.
Legal, but worth knowing.

**Past companies** — For each prior company in the bio, ask: did its stock go up or down while they
were there? Did they leave on good terms, or was there a scandal? A quick news search on
"<name> <old company>" answers this fast.

**M&A track record** — Count how many 8-K filings announce acquisitions. A CEO who buys a lot of
companies grows fast but takes on debt and integration risk. One who builds in-house grows slower
but cleaner. Neither is wrong; it's a style.

**SEC enforcement** — If the CEO's name shows up here, it means the government formally charged
them with breaking securities rules. That's serious and rare. No results = nothing on record.

**Form 4 insider trades** — Executives selling under a "10b5-1 plan" is routine (planned months ahead).
Large, unplanned sales right before bad news is the pattern to notice.

**What this tool will NOT tell you** — personality, private life, or anything not in a public record.
"Shady" is a conclusion you draw from documents, not a fact the system can hand you.
"""


def run(ticker, ceo_name=None, demo=False):
    lines = [f"# Leadership background — {ticker}", ""]
    if demo:
        lines.append("_DEMO mode: skipping live SEC lookups; showing the link set and the reading guide._")
        cik, company = None, ticker
    else:
        cik, company = lookup_cik(ticker)
        if not cik:
            lines.append(f"Could not find {ticker} in the SEC ticker list.")
            return "\n".join(lines)
        lines.append(f"Company: **{company}** · SEC id (CIK) {cik}")
        lines.append("")
        filings = recent_filings(cik)
        for form, label in (("DEF 14A", "Proxy statements (CEO bio + pay)"), ("8-K", "Big-news filings"), ("10-K", "Yearly reports")):
            lines.append(f"## {label} — {form}")
            for date, desc, url in filings.get(form, []):
                lines.append(f"- {date} · {desc} — {url}")
            if not filings.get(form):
                lines.append("- none found")
            lines.append("")

    if ceo_name:
        lines.append(f"## Public-record searches for **{ceo_name}**")
        for label, url in search_links(ceo_name, company or ticker, ticker, cik).items():
            lines.append(f"- {label}: {url}")
        lines.append("")
    lines.append(GUIDE)
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Leadership background from public records.")
    p.add_argument("ticker")
    p.add_argument("--ceo", help="CEO's full name, e.g. 'Jensen Huang'")
    p.add_argument("--demo", action="store_true", help="no network; show links + guide only")
    a = p.parse_args()
    print(run(a.ticker.upper(), a.ceo, demo=a.demo))
