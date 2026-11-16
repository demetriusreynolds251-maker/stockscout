"""
scout_data.py — gets the raw facts about a stock.

One function matters: get_snapshot(ticker, demo=False)
It returns a plain dict with the same keys every time, whether the data
came live from Yahoo Finance (via the yfinance package) or from a saved
sample file in fixtures/ (demo mode, for testing without internet).

Nothing here talks to Discord or writes reports. Facts only.
"""
import json
import os
import re
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def _safe(d, key, default=None):
    v = d.get(key, default)
    return default if v in (None, "", "N/A") else v


def _pct(x):
    """Turn 0.153 into 15.3 (percent). Leaves None alone."""
    return None if x is None else round(float(x) * 100, 1)


def empty_snapshot(ticker):
    return {
        "ticker": ticker, "name": None, "sector": None, "industry": None,
        "summary": None, "website": None,
        "price": None, "prev_close": None, "day_change_pct": None,
        "high_52w": None, "low_52w": None, "market_cap": None, "beta": None,
        "pe": None, "forward_pe": None, "eps": None,
        "revenue": None, "revenue_growth_pct": None, "net_income": None,
        "profit_margin_pct": None, "free_cash_flow": None, "debt_to_equity": None,
        "dividend_yield_pct": None, "short_pct_float": None,
        "institutional_pct": None, "insider_pct": None,
        "analyst_target": None, "analyst_rec": None, "analyst_count": None,
        # extra fields for the analysis engine
        "gross_margin_pct": None, "operating_margin_pct": None, "earnings_growth_pct": None,
        "operating_cash_flow": None, "total_cash": None, "total_debt": None, "current_ratio": None,
        "price_to_sales": None, "roe_pct": None, "shares_out": None, "employees": None,
        "target_low": None, "target_high": None, "rec_mean": None, "ma50": None, "ma200": None,
        "ttm": {},                       # last-4-quarter totals from the financial statements
        "quarterly_revenue": [],         # [(YYYY-MM-DD, revenue)] oldest -> newest
        "next_earnings": None,           # "YYYY-MM-DD" or None
        "officers": [],                  # [{name, title, age, pay}]
        "news": [],                      # [{title, publisher, link, date}]  general coverage
        "bear_news": [],                 # critical coverage, searched for on purpose
        "shares_short": None, "shares_short_prior": None, "short_days_to_cover": None,
        "source": None, "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def _from_fixture(ticker):
    path = os.path.join(FIXTURES, f"{ticker}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No demo file for {ticker} at {path}")
    with open(path) as f:
        snap = empty_snapshot(ticker)
        snap.update(json.load(f))
        snap["source"] = "DEMO sample data (not live)"
        return snap


def _from_yfinance(ticker, news_items=8):
    import yfinance as yf  # imported here so demo mode needs no internet
    t = yf.Ticker(ticker)
    info = t.info or {}
    snap = empty_snapshot(ticker)

    snap.update({
        "name": _safe(info, "shortName") or _safe(info, "longName"),
        "sector": _safe(info, "sector"), "industry": _safe(info, "industry"),
        "summary": _safe(info, "longBusinessSummary"), "website": _safe(info, "website"),
        "price": _safe(info, "currentPrice") or _safe(info, "regularMarketPrice"),
        "prev_close": _safe(info, "previousClose"),
        "high_52w": _safe(info, "fiftyTwoWeekHigh"), "low_52w": _safe(info, "fiftyTwoWeekLow"),
        "market_cap": _safe(info, "marketCap"), "beta": _safe(info, "beta"),
        "pe": _safe(info, "trailingPE"), "forward_pe": _safe(info, "forwardPE"),
        "eps": _safe(info, "trailingEps"),
        "revenue": _safe(info, "totalRevenue"),
        "revenue_growth_pct": _pct(_safe(info, "revenueGrowth")),
        "net_income": _safe(info, "netIncomeToCommon"),
        "profit_margin_pct": _pct(_safe(info, "profitMargins")),
        "free_cash_flow": _safe(info, "freeCashflow"),
        # Yahoo reports debt/equity as a PERCENT (2.57 means 2.57%, i.e. 0.0257). Store the plain ratio.
        "debt_to_equity": (_safe(info, "debtToEquity") / 100.0) if _safe(info, "debtToEquity") is not None else None,
        "gross_margin_pct": _pct(_safe(info, "grossMargins")),
        "operating_margin_pct": _pct(_safe(info, "operatingMargins")),
        "earnings_growth_pct": _pct(_safe(info, "earningsGrowth")),
        "operating_cash_flow": _safe(info, "operatingCashflow"),
        "total_cash": _safe(info, "totalCash"), "total_debt": _safe(info, "totalDebt"),
        "current_ratio": _safe(info, "currentRatio"),
        "price_to_sales": _safe(info, "priceToSalesTrailing12Months"),
        "roe_pct": _pct(_safe(info, "returnOnEquity")),
        "shares_out": _safe(info, "sharesOutstanding"), "employees": _safe(info, "fullTimeEmployees"),
        "target_low": _safe(info, "targetLowPrice"), "target_high": _safe(info, "targetHighPrice"),
        "rec_mean": _safe(info, "recommendationMean"),
        "ma50": _safe(info, "fiftyDayAverage"), "ma200": _safe(info, "twoHundredDayAverage"),
        "shares_short": _safe(info, "sharesShort"), "shares_short_prior": _safe(info, "sharesShortPriorMonth"),
        "short_days_to_cover": _safe(info, "shortRatio"),
        "dividend_yield_pct": _pct(_safe(info, "dividendYield")),
        "short_pct_float": _pct(_safe(info, "shortPercentOfFloat")),
        "institutional_pct": _pct(_safe(info, "heldPercentInstitutions")),
        "insider_pct": _pct(_safe(info, "heldPercentInsiders")),
        "analyst_target": _safe(info, "targetMeanPrice"),
        "analyst_rec": _safe(info, "recommendationKey"),
        "analyst_count": _safe(info, "numberOfAnalystOpinions"),
        "source": "Yahoo Finance via yfinance",
    })
    if snap["price"] and snap["prev_close"]:
        snap["day_change_pct"] = round((snap["price"] / snap["prev_close"] - 1) * 100, 2)

    # Last four quarters from the actual financial statements (more reliable than the summary numbers)
    try:
        snap["ttm"], snap["quarterly_revenue"] = _statements(t)
    except Exception:
        pass

    # Next earnings date
    try:
        cal = t.calendar or {}
        dates = cal.get("Earnings Date") or []
        if dates:
            d = dates[0]
            snap["next_earnings"] = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
    except Exception:
        pass

    # Leadership
    for o in info.get("companyOfficers", []) or []:
        snap["officers"].append({
            "name": o.get("name"), "title": o.get("title"),
            "age": o.get("age"), "pay": o.get("totalPay"),
        })

    # News
    try:
        for n in (t.news or [])[:news_items]:
            c = n.get("content", n)  # yfinance changed shape across versions
            snap["news"].append({
                "title": c.get("title"),
                "publisher": (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher"),
                "link": (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link"),
                "date": (c.get("pubDate") or "")[:10],
            })
    except Exception:
        pass
    if not snap["news"]:
        snap["news"] = _google_news(snap.get("name") or ticker, ticker, news_items)
    if news_items:
        bull_titles = {n.get("title") for n in snap["news"]}
        snap["bear_news"] = [n for n in _bear_news(snap.get("name") or ticker, ticker) if n.get("title") not in bull_titles]
    return snap


def _statements(t):
    """Sum the last 4 quarters (TTM = trailing twelve months) of key lines; also share count a year apart."""
    def row(df, *names):
        for n in names:
            if df is not None and len(df.columns) and n in df.index:
                return [None if v != v else float(v) for v in df.loc[n].values]  # v != v catches NaN
        return []

    def ttm(vals):
        v = [x for x in vals[:4] if x is not None]
        return sum(v) if len(v) == 4 else None

    inc, cf, bs = t.quarterly_income_stmt, t.quarterly_cashflow, t.quarterly_balance_sheet
    out = {
        "revenue": ttm(row(inc, "Total Revenue")),
        "operating_income": ttm(row(inc, "Operating Income")),
        "net_income": ttm(row(inc, "Net Income")),
        "interest_income": ttm(row(inc, "Interest Income")),
        "tax_provision": ttm(row(inc, "Tax Provision")),
        "operating_cash_flow": ttm(row(cf, "Operating Cash Flow")),
        "capex": ttm(row(cf, "Capital Expenditure")),
        "free_cash_flow": ttm(row(cf, "Free Cash Flow")),
        "stock_comp": ttm(row(cf, "Stock Based Compensation")),
        # cash tied up as the business grows (negative = cash used)
        "chg_receivables": ttm(row(cf, "Change In Receivables", "Changes In Account Receivables")),
        "chg_inventory": ttm(row(cf, "Change In Inventory")),
    }
    ocf_q, ni_q, rec_q = row(cf, "Operating Cash Flow"), row(inc, "Net Income"), row(cf, "Change In Receivables", "Changes In Account Receivables")
    if ocf_q and ni_q and ocf_q[0] is not None and ni_q[0]:
        out["last_q"] = {"operating_cash_flow": ocf_q[0], "net_income": ni_q[0],
                         "chg_receivables": rec_q[0] if rec_q else None}
    shares = row(bs, "Ordinary Shares Number", "Share Issued")
    if len(shares) >= 5 and shares[0] and shares[4]:
        out["shares_now"], out["shares_year_ago"] = shares[0], shares[4]
    revs = row(inc, "Total Revenue")
    dates = [c.strftime("%Y-%m-%d") for c in inc.columns] if inc is not None and len(inc.columns) else []
    q = [(d, r) for d, r in zip(dates, revs) if r is not None][:5]
    return out, list(reversed(q))


def _short_name(name, ticker):
    return re.sub(r",?\s+(Inc\.?|Corp(oration)?\.?|Ltd\.?|Holdings?|Group|Co\.?|Technologies|Technology)$", "", name or ticker, flags=re.I).strip()


BEAR_TERMS = '(downgrade OR "short seller" OR "short report" OR lawsuit OR investigation OR overvalued OR "sell rating" OR falls OR plunges OR risks)'


def _bear_news(name, ticker, limit=6):
    """The other side on purpose: downgrades, short-seller reports, lawsuits, sell-offs."""
    return _google_news(name, ticker, limit, query=f'"{_short_name(name, ticker)}" {BEAR_TERMS}')


def _google_news(name, ticker, limit=8, query=None):
    """Headline source: Google News RSS. Used when Yahoo returns none, and for the bear-side search."""
    import urllib.parse
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    import requests
    short = _short_name(name, ticker)
    q = urllib.parse.quote_plus(query or f'"{short}" OR {ticker} stock')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        out = []
        for item in ET.fromstring(r.content).iter("item"):
            title = (item.findtext("title") or "").strip()
            src = item.findtext("source") or ""
            if src and title.endswith(" - " + src):
                title = title[: -len(" - " + src)]
            try:
                date = parsedate_to_datetime(item.findtext("pubDate")).strftime("%Y-%m-%d")
            except Exception:
                date = ""
            out.append({"title": title, "publisher": src, "link": item.findtext("link"), "date": date})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def get_snapshot(ticker, demo=False, news_items=8):
    ticker = ticker.upper().strip()
    if demo:
        return _from_fixture(ticker)
    return _from_yfinance(ticker, news_items=news_items)


def save_snapshot(snap, data_dir):
    """Keep a dated copy so you can look back at what the numbers were."""
    os.makedirs(data_dir, exist_ok=True)
    day = dt.date.today().isoformat()
    path = os.path.join(data_dir, f"{snap['ticker']}_{day}.json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=2, default=str)
    return path
