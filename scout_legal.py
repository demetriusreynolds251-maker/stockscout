"""
scout_legal.py — lawsuits and red-flag filings, rated by how serious they are.

Sources (all free, all public):
  1. Federal court cases naming the company   CourtListener (copies new federal filings, often within hours)
  2. Red-flag company filings                 SEC 8-K "event codes" (e.g. 4.02 = past financials can't be relied on)
  3. Lawsuit / investigation news             Google News: class actions, SEC/DOJ/FTC probes, subpoenas

Each item gets a severity and a plain-English "what this means":
  CRITICAL  can threaten the company itself (restatement, bankruptcy)
  SERIOUS   often moves the stock (securities fraud, antitrust, government action, auditor change)
  MEDIUM    worth knowing (patents against a smaller company, product liability, exec departures)
  LOW       routine for a company this size (single-person employment suits, patent suits against giants)

Limits, stated honestly: state courts and sealed cases are not covered; case types are sometimes filled
in a day after filing; a lawsuit is an accusation, not a verdict.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CL_URL = "https://www.courtlistener.com/api/rest/v4/search/"
UA = {"User-Agent": "StockScout personal research"}
SEC_UA = {"User-Agent": "StockScout research tool contact: your-email@example.com"}
SEV_ORDER = {"CRITICAL": 0, "SERIOUS": 1, "MEDIUM": 2, "LOW": 3}
SEV_ICON = {"CRITICAL": "🚨", "SERIOUS": "🔴", "MEDIUM": "🟠", "LOW": "⚪"}

GOV = re.compile(r"\b(united states|u\.s\.|securities and exchange commission|federal trade commission|department of justice|"
                 r"state of|people of the state|commonwealth of|attorney general|consumer financial protection)\b", re.I)

# Federal "nature of suit" codes -> (severity for a small/mid company, severity for a giant, plain meaning)
SUIT_TYPES = {
    "850": ("SERIOUS", "SERIOUS", "Securities case: usually shareholders claiming they were misled about the business. These often become class actions and can bring big settlements."),
    "410": ("SERIOUS", "SERIOUS", "Antitrust case: accused of unfairly blocking competition. Can mean large fines or forced changes to how it does business."),
    "470": ("SERIOUS", "SERIOUS", "Racketeering (RICO) case: a serious fraud-type accusation."),
    "830": ("MEDIUM", "LOW", "Patent case: someone claims the company's product uses their invention. Usually settled; occasionally a large verdict or a sales ban."),
    "835": ("MEDIUM", "LOW", "Patent case (drug-related)."),
    "820": ("MEDIUM", "LOW", "Copyright case: claims the company used someone's protected work (common for AI companies over training data)."),
    "840": ("LOW", "LOW", "Trademark case: dispute over names or logos."),
    "190": ("MEDIUM", "LOW", "Contract dispute: a business partner says a deal was broken."),
    "370": ("MEDIUM", "LOW", "Fraud claim by a private party."),
    "365": ("MEDIUM", "LOW", "Product liability: claims a product caused harm."),
    "367": ("MEDIUM", "LOW", "Product liability (health care/pharma)."),
    "890": ("MEDIUM", "LOW", "Other federal law claim (consumer protection, privacy, and similar)."),
    "442": ("LOW", "LOW", "Employment discrimination case, usually one person."),
    "446": ("LOW", "LOW", "Disability-access case (often about websites), usually one person."),
    "710": ("LOW", "LOW", "Wage/labor case."),
    "791": ("LOW", "LOW", "Employee benefits case."),
}

# SEC 8-K event codes that matter
EIGHT_K = {
    "4.02": ("CRITICAL", "The company says its past financial statements should NOT be relied on (a restatement). One of the most serious red flags a company can file."),
    "1.03": ("CRITICAL", "Bankruptcy or receivership."),
    "4.01": ("SERIOUS", "The company changed its auditor. Sometimes routine, sometimes a sign of accounting disagreements; read why."),
    "3.01": ("SERIOUS", "Notice it may be removed from its stock exchange (delisting) or doesn't meet listing rules."),
    "1.05": ("SERIOUS", "A material cybersecurity incident (a hack or breach serious enough to report)."),
    "2.06": ("MEDIUM", "A large write-down: something the company owns is worth much less than it said."),
    "5.02": ("MEDIUM", "A top executive or director is leaving, joining, or changing roles. Matters most if it's the CEO or CFO and sudden."),
    "2.05": ("MEDIUM", "Layoffs or closing part of the business, with costs."),
    "8.01": ("LOW", "'Other events': the company reported something it considers important. Sometimes this is a lawsuit or settlement; open the filing."),
}

NEWS_TERMS = ('("class action" OR lawsuit OR sued OR "securities fraud" OR subpoena OR investigation OR '
              '"Justice Department" OR "SEC charges" OR antitrust OR indictment OR settlement OR "steps down" OR resigns OR ousted OR "CEO exit")')
LEADER = re.compile(r"\b(ceo|chief executive|cfo|chief financial|founder|chairman|chair)\b.{0,60}\b(steps? down|resign|ousted|fired|depart|exit|leav|replaced|out\b)|"
                    r"\b(steps? down|resign\w*|oust\w*|fire[sd]|quits?)\b.{0,40}\b(ceo|chief executive|cfo)\b", re.I)
NEWS_LEGAL = re.compile(r"lawsuit|sued|\bsues\b|\bsuit\b|class action|court|judge|jury|verdict|settle|subpoena|probe|"
                        r"investigat|antitrust|regulator|\bsec\b|\bftc\b|\bdoj\b|justice department|indict|charge|fine[ds]?\b|"
                        r"penalt|complaint|alleg|fraud|patent|infring|injunction|ban\b|restat", re.I)
NEWS_SERIOUS = re.compile(r"class action|securities fraud|sec (charges|probe|investigat)|justice department|doj|indict|"
                          r"subpoena|antitrust|ftc|criminal|restat|fraud", re.I)


def _short(name):
    return re.sub(r",?\s+(Inc\.?|Corp(oration)?\.?|Ltd\.?|Holdings?|Group|Co\.?|plc|N\.V\.)$", "", name or "", flags=re.I).strip()


# ---------------------------------------------------------------- sources
def court_cases(name, market_cap=None, days=120):
    giant = (market_cap or 0) > 200e9
    nm = _short(name)
    q = f'caseName:("{nm}")'
    after = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    r = requests.get(CL_URL, params={"type": "r", "q": q, "order_by": "dateFiled desc", "filed_after": after},
                     headers=UA, timeout=40)
    r.raise_for_status()
    out = []
    for x in r.json().get("results", [])[:25]:
        case = x.get("caseName") or ""
        code = (x.get("suitNature") or "").split(" ")[0]
        sev_small, sev_giant, meaning = SUIT_TYPES.get(code, ("MEDIUM", "LOW", "Case type not listed yet (courts often add it a day or two after filing)."))
        sev = sev_giant if giant else sev_small
        plaintiff, _, defendant = case.partition(" v. ")
        company_is_plaintiff = nm.lower() in plaintiff.lower() and nm.lower() not in defendant.lower()
        if GOV.search(plaintiff) and not company_is_plaintiff:
            sev, meaning = "SERIOUS", "A GOVERNMENT agency is the one suing. Government cases carry more weight than private suits. " + meaning
        if company_is_plaintiff:
            sev, meaning = "LOW", "The company is the one SUING here (it's the plaintiff), usually to protect its own patents or contracts."
        if " et al" in defendant.lower() and code == "850":
            meaning += " Several defendants are named (often the company plus its executives), typical of a securities class action."
        out.append({
            "id": f"cl:{x.get('docket_id')}",
            "source": "Federal court",
            "date": (x.get("dateFiled") or "")[:10],
            "title": case,
            "detail": f"{x.get('court_citation_string') or x.get('court', '')} · {x.get('suitNature') or 'type pending'}",
            "severity": sev,
            "plain": meaning,
            "link": "https://www.courtlistener.com" + (x.get("docket_absolute_url") or ""),
        })
    return out


_TICKERS_CACHE = os.path.join(DATA, "sec_tickers.json")


def _cik_for(ticker):
    fresh = os.path.exists(_TICKERS_CACHE) and time.time() - os.path.getmtime(_TICKERS_CACHE) < 86400 * 7
    if not fresh:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA, timeout=30)
        r.raise_for_status()
        os.makedirs(DATA, exist_ok=True)
        with open(_TICKERS_CACHE, "w") as f:
            f.write(r.text)
    with open(_TICKERS_CACHE) as f:
        for row in json.load(f).values():
            if row.get("ticker", "").upper() == ticker.upper():
                return str(row["cik_str"]).zfill(10)
    return None


def red_flag_filings(ticker, days=120):
    cik = _cik_for(ticker)
    if not cik:
        return []
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_UA, timeout=30)
    r.raise_for_status()
    rec = r.json()["filings"]["recent"]
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = []
    for form, date, acc, doc, items in zip(rec["form"], rec["filingDate"], rec["accessionNumber"], rec["primaryDocument"], rec["items"]):
        if date < cutoff:
            break
        if form not in ("8-K", "8-K/A"):
            continue
        for code in [c.strip() for c in (items or "").split(",")]:
            if code in EIGHT_K:
                sev, meaning = EIGHT_K[code]
                out.append({
                    "id": f"8k:{acc}:{code}",
                    "source": "SEC filing",
                    "date": date,
                    "title": f"8-K item {code}",
                    "detail": form,
                    "severity": sev,
                    "plain": meaning,
                    "link": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
                })
    return out


def legal_news(name, ticker, limit=8):
    import scout_data
    items = scout_data._google_news(name, ticker, limit, query=f'"{_short(name)}" {NEWS_TERMS}')
    out = []
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    for n in items:
        if n.get("date") and n["date"] < cutoff:
            continue
        title = n.get("title", "")
        if LEADER.search(title):
            out.append({"id": "news:" + re.sub(r"\W+", "", title.lower())[:80], "source": "News", "date": n.get("date", ""), "title": title,
                        "detail": n.get("publisher", ""), "severity": "SERIOUS", "link": n.get("link", ""),
                        "plain": "LEADERSHIP CHANGE: a top executive is leaving. Sudden CEO exits (especially with a scandal) can move a stock for days "
                                 "and often push money into its rivals. Check the company's own announcement (an 8-K 'item 5.02' filing)."})
            continue
        if not NEWS_LEGAL.search(title):
            continue  # matched the search but isn't actually a legal story (e.g. "shares fall")
        serious = bool(NEWS_SERIOUS.search(title))
        medium = bool(re.search(r"lawsuit|sued|\bsues\b|complaint|alleg|injunction|regulator|probe|fine", title, re.I))
        out.append({
            "id": "news:" + re.sub(r"\W+", "", (n.get("title") or "").lower())[:80],
            "source": "News",
            "date": n.get("date", ""),
            "title": n.get("title", ""),
            "detail": n.get("publisher", ""),
            "severity": "SERIOUS" if serious else "MEDIUM" if medium else "LOW",
            "plain": ("Headline mentions a class action, government probe, or fraud claim. Law-firm 'investor alert' press releases "
                      "often follow a real filing within a day; some are just firms fishing for clients. Check for a matching court case."
                      if serious else
                      "A lawsuit or regulatory complaint is in the news. Read it to see whether it touches a major deal or the core business."
                      if medium else "Legal-related headline; likely minor."),
            "link": n.get("link", ""),
        })
    return out


def check(ticker, name, market_cap=None, days=120, log=print):
    """All legal items for one company, most serious and newest first. Never raises."""
    items = []
    for fn, args in ((court_cases, (name, market_cap, days)), (red_flag_filings, (ticker, days)), (legal_news, (name, ticker))):
        try:
            items += fn(*args)
        except Exception as e:
            log(f"  legal source {fn.__name__} failed for {ticker}: {type(e).__name__}: {e}")
    items.sort(key=lambda x: (SEV_ORDER[x["severity"]], ""), reverse=False)
    items.sort(key=lambda x: (SEV_ORDER[x["severity"]], -int((x["date"] or "0000-00-00").replace("-", ""))))
    return items


# ---------------------------------------------------------------- "new since last check" for alerts
SEEN = os.path.join(DATA, "legal_seen.json")


def new_items(ticker, items):
    """Returns items not seen before for this ticker, and records them. First check for a ticker just records (no flood)."""
    os.makedirs(DATA, exist_ok=True)
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    first_time = ticker not in seen
    known = set(seen.get(ticker, []))
    fresh = [i for i in items if i["id"] not in known]
    seen[ticker] = sorted(known | {i["id"] for i in items})
    with open(SEEN, "w") as f:
        json.dump(seen, f)
    return [] if first_time else fresh


def summary_counts(items):
    c = {k: 0 for k in SEV_ORDER}
    for i in items:
        c[i["severity"]] += 1
    return c
