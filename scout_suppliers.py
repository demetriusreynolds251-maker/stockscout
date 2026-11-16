"""
scout_suppliers.py — the supplier hunter.

Question it answers: "Which companies — especially smaller ones I've never
heard of — say in their own yearly report that they do business with X?"

How:
  1. Search every 10-K (yearly report) filed with the SEC for the anchor
     company's name, using the SEC's free full-text search.
  2. For each company found, pull the sentences around the mention and sort
     them into: CUSTOMER (anchor buys from them = they are a supplier),
     SUPPLIER (anchor sells to them), COMPETITOR, or just MENTIONS.
  3. Look up each company's market cap and rank smallest-first, so the
     lesser-known names come out on top.

Public records only. Nothing here guesses.

Usage:
  python3 scout_suppliers.py NVIDIA --ticker NVDA --max 20 --post
  python3 scout_suppliers.py NVIDIA --ticker NVDA --demo
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scout_data, scout_discord  # noqa: E402
from scout_analysis import money  # noqa: E402
from scout_ceo import HEADERS  # same SEC contact header  # noqa: E402

EFTS = "https://efts.sec.gov/LATEST/search-index"
SEC_PAUSE = 0.15  # SEC allows ~10 requests/sec; stay well under

LESSER_KNOWN_CAP = 50e9  # under $50B market cap = "lesser-known" for our purposes

CUSTOMER_WORDS = ("customer", "customers", "sales to", "revenue from", "purchases from us", "accounted for", "% of our revenue", "percent of our revenue", "design win", "design wins")
SUPPLIER_WORDS = ("supplier", "suppliers", "we purchase", "we source", "we rely on", "we depend on", "components from", "licens")
COMPETITOR_WORDS = ("competitor", "competitors", "compete", "competition", "competitive")


# ---------------- step 1: who mentions the anchor in a 10-K? ----------------
def search_10k_mentions(anchor, years=2, max_pages=5, demo=False):
    """Return {cik: {name, ticker, filings:[{date, url}]}} for 10-Ks mentioning `anchor`."""
    if demo:
        with open(os.path.join(HERE, "fixtures", f"suppliers_{anchor.upper()}.json")) as f:
            return json.load(f)["hits"]

    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    found = {}
    for page in range(max_pages):
        # The SEC search pages with "from" (an offset), 100 results at a time.
        params = {"q": f'"{anchor}"', "forms": "10-K", "dateRange": "custom",
                  "startdt": start, "enddt": dt.date.today().isoformat(), "from": page * 100}
        r = requests.get(EFTS, params=params, headers=HEADERS, timeout=40)
        r.raise_for_status()
        body = r.json().get("hits", {})
        hits = body.get("hits", [])
        if not hits:
            break
        total = (body.get("total") or {}).get("value", 0)
        for h in hits:
            src = h["_source"]
            name_full = (src.get("display_names") or [""])[0]
            # display_names look like: "Astera Labs, Inc.  (ALAB)  (CIK 0001736297)"
            m = re.match(r"(.*?)\s+\((.*?)\)\s+\(CIK\s+(\d+)\)", name_full)
            if m:
                name, ticker, cik = m.group(1).strip(), m.group(2).strip(), m.group(3)
            else:
                name, ticker, cik = name_full.split("(")[0].strip(), None, (src.get("ciks") or [""])[0]
            ticker = ticker.split(",")[0].strip() if ticker else None  # some list several
            if not ticker or len(ticker) > 6:
                continue  # no ticker = not tradable (or a weird entity); skip
            acc, doc = h["_id"].split(":", 1)
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
            entry = found.setdefault(cik, {"name": name, "ticker": ticker, "filings": []})
            entry["filings"].append({"date": src.get("file_date"), "url": url})
        time.sleep(SEC_PAUSE)
        if (page + 1) * 100 >= total:
            break
    return found


# ---------------- step 2: what do they say about it? ----------------
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _clean(raw_html):
    return html.unescape(_WS.sub(" ", _TAG.sub(" ", raw_html))).strip()


def _sentences_mentioning(text, anchor, limit=8):
    """Whole sentences that contain the anchor name, most informative first."""
    pat = re.compile(re.escape(anchor), re.I)
    hits = [s.strip() for s in _SENT_SPLIT.split(text) if pat.search(s)]
    # prefer sentences that also carry a relationship word (customer/supplier/competitor)
    keywords = CUSTOMER_WORDS + SUPPLIER_WORDS + COMPETITOR_WORDS
    hits.sort(key=lambda s: -sum(1 for w in keywords if w in s.lower()))
    seen, out = set(), []
    for s in hits:
        if s not in seen and 20 <= len(s) <= 600:
            seen.add(s); out.append(s)
        if len(out) >= limit:
            break
    return out


def fetch_context(url, anchor, demo_text=None, max_bytes=25_000_000):
    """Download the filing, strip HTML, return (mention_count, sentences)."""
    if demo_text is not None:
        text = _clean(demo_text)
    else:
        r = requests.get(url, headers=HEADERS, timeout=90, stream=True)
        r.raise_for_status()
        raw, size = [], 0
        for chunk in r.iter_content(262_144):
            raw.append(chunk); size += len(chunk)
            if size > max_bytes:
                break
        text = _clean(b"".join(raw).decode("utf-8", errors="ignore"))
        time.sleep(SEC_PAUSE)
    count = len(re.findall(re.escape(anchor), text, flags=re.I))
    return count, _sentences_mentioning(text, anchor)


def classify(sentences, anchor="NVIDIA"):
    """Label the relationship by the words right next to the anchor's name, sentence by sentence.
    Each sentence votes; the strongest pattern wins. Shown with the quote so you can judge it yourself."""
    a = re.escape(anchor)
    patterns = {
        "CUSTOMER": [  # the anchor BUYS from this company -> this company is a supplier to it
            rf"customers?[^.]{{0,60}}(including|includes?|such as|like|namely|are|were)[^.]{{0,80}}{a}",
            rf"{a}[^.]{{0,80}}(accounted for|represented|comprised)[^.]{{0,40}}(revenue|sales)",
            rf"(sales|revenue|shipments)[^.]{{0,30}}\bto\b[^.]{{0,20}}{a}",
            rf"{a}[^.]{{0,40}}\b(is|was|are|became|remains)\b[^.]{{0,20}}(our|a)[^.]{{0,25}}customers?",
            rf"(design wins?|qualified|selected)[^.]{{0,60}}{a}", rf"{a}[^.]{{0,60}}(selected|qualified) (our|us)",
            rf"we (sell|supply|provide|ship)[^.]{{0,60}}{a}",
        ],
        "SUPPLIER": [  # this company BUYS from the anchor
            rf"(purchase|buy|procure|source|acquire|lease|rely on|depend on|dependent on)[^.]{{0,60}}(from )?{a}",
            rf"{a}[^.]{{0,40}}(supplier|vendor|provider)", rf"(supplier|vendor)s?[^.]{{0,40}}(including|such as)[^.]{{0,60}}{a}",
            rf"{a}[^.]{{0,15}}(GPUs?|chips?|processors?|hardware|platform)",
        ],
        "COMPETITOR": [rf"compet\w*[^.]{{0,100}}{a}", rf"{a}[^.]{{0,60}}compet\w*"],
        "PARTNER": [rf"(partner\w*|collaborat\w*|alliance|joint)[^.]{{0,80}}{a}", rf"{a}[^.]{{0,60}}(partner\w*|collaborat\w*)"],
    }
    votes = {k: 0 for k in patterns}
    for sent in sentences:
        for label, pats in patterns.items():
            if any(re.search(p, sent, flags=re.I) for p in pats):
                votes[label] += 1
    order = ["CUSTOMER", "COMPETITOR", "SUPPLIER", "PARTNER"]  # tie-break: most informative first
    best = max(order, key=lambda k: (votes[k], -order.index(k)))
    return best if votes[best] > 0 else "MENTIONS"


RELATION_PLAIN = {
    "CUSTOMER": "names the anchor as a CUSTOMER → this company is a supplier/partner. If the anchor grows, this one may too.",
    "SUPPLIER": "says it BUYS from the anchor → the anchor is its supplier. Less interesting for supplier-hunting.",
    "COMPETITOR": "calls the anchor a COMPETITOR → not a supplier; it wins when the anchor loses.",
    "PARTNER": "describes a PARTNERSHIP with the anchor → working together; read the quote to see how much money is involved.",
    "MENTIONS": "mentions the anchor without a clear customer/supplier/competitor phrase → read the sentences yourself.",
}


# ---------------- step 3: rank, write, post ----------------
def run(anchor, anchor_ticker=None, max_companies=20, demo=False, with_context=True):
    hits = search_10k_mentions(anchor, demo=demo)
    demo_texts = {}
    if demo:
        with open(os.path.join(HERE, "fixtures", f"suppliers_{anchor.upper()}.json")) as f:
            demo_texts = json.load(f).get("texts", {})

    rows = []
    for cik, e in hits.items():
        if anchor_ticker and e["ticker"].upper() == anchor_ticker.upper():
            continue  # the anchor's own filing
        row = {"name": e["name"], "ticker": e["ticker"], "cik": cik,
               "filings": len(e["filings"]), "latest": max(f["date"] for f in e["filings"] if f["date"]),
               "url": sorted(e["filings"], key=lambda f: f["date"] or "")[-1]["url"],
               "mentions": None, "sentences": [], "relation": "MENTIONS", "market_cap": None, "price": None}
        if with_context:
            try:
                row["mentions"], row["sentences"] = fetch_context(row["url"], anchor, demo_text=demo_texts.get(e["ticker"]))
                row["relation"] = classify(row["sentences"], anchor)
            except Exception as ex:
                row["sentences"] = [f"(could not read filing: {type(ex).__name__})"]
        try:
            snap = scout_data.get_snapshot(e["ticker"], demo=demo)
            row["market_cap"], row["price"] = snap.get("market_cap"), snap.get("price")
        except Exception:
            pass  # no fixture / no quote → stays None, still listed
        rows.append(row)

    # Rank: customers first, then smallest market cap first, unknown cap last
    order = {"CUSTOMER": 0, "PARTNER": 1, "MENTIONS": 2, "SUPPLIER": 3, "COMPETITOR": 4}
    rows.sort(key=lambda r: (order[r["relation"]], r["market_cap"] is None, r["market_cap"] or 0))
    rows = rows[:max_companies]

    # Save raw
    data_dir = os.path.join(HERE, "data"); os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, f"suppliers_{anchor.upper()}_{dt.date.today().isoformat()}.json"), "w") as f:
        json.dump(rows, f, indent=2, default=str)

    return rows, render(anchor, rows, demo)


def render(anchor, rows, demo):
    L = [f"# 🔎 Supplier hunt — who mentions **{anchor}** in their yearly report (10-K)",
         f"_{dt.date.today().isoformat()} · {'DEMO sample data' if demo else 'SEC EDGAR full-text search, last 2 years'} · smallest companies first_", ""]
    if not rows:
        L.append("No companies found."); return "\n".join(L)
    L.append("**How to read this:** a company must disclose big customers in its 10-K, so 'CUSTOMER' below means they "
             f"name {anchor} as someone who buys from them — that's a supplier/partner. Under $50B market cap is tagged "
             "🟢 lesser-known. Mentions = how many times the name appears in the filing (more = more dependence, roughly).")
    L.append("")
    for i, r in enumerate(rows, 1):
        tag = "🟢 lesser-known" if (r["market_cap"] or 0) and r["market_cap"] < LESSER_KNOWN_CAP else ("🔵 large" if r["market_cap"] else "⚪ size unknown")
        L.append(f"## {i}. {r['name']} ({r['ticker']}) — {r['relation']} · {tag}")
        L.append(f"Market cap {money(r['market_cap'])} · {r['filings']} filing(s), latest {r['latest']}"
                 + (f" · {r['mentions']} mention(s)" if r["mentions"] is not None else ""))
        L.append(f"_{RELATION_PLAIN[r['relation']]}_")
        for s in r["sentences"][:2]:
            L.append(f"> {s[:350]}{'…' if len(s) > 350 else ''}")
        L.append(f"Filing: {r['url']}")
        L.append("")
    L.append("_Next: run `python3 run_scout.py report TICKER` on any 🟢 CUSTOMER to get the full plain-English report, "
             "and add it to `config.yaml` if you want it tracked daily._")
    return "\n".join(L)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Find companies whose 10-K mentions an anchor company.")
    p.add_argument("anchor", help="company name as it appears in filings, e.g. NVIDIA")
    p.add_argument("--ticker", help="anchor's ticker so its own filing is skipped, e.g. NVDA")
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--no-context", action="store_true", help="skip downloading filings (fast, no sentences)")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--post", action="store_true", help="send to Discord")
    a = p.parse_args()
    rows, text = run(a.anchor, a.ticker, a.max, demo=a.demo, with_context=not a.no_context)
    print(text)
    rep_dir = os.path.join(HERE, "reports"); os.makedirs(rep_dir, exist_ok=True)
    path = os.path.join(rep_dir, f"suppliers_{a.anchor.upper()}_{dt.date.today().isoformat()}.md")
    with open(path, "w") as f:
        f.write(text)
    print(f"\n[saved → {path}]")
    if a.post:
        import yaml
        cfg = yaml.safe_load(open(os.path.join(HERE, "config.yaml")))
        hook = scout_discord.load_webhook(os.path.join(HERE, cfg.get("discord_webhook_file", "")))
        print(f"[posted {scout_discord.post(text, hook)} message(s) to Discord]")
