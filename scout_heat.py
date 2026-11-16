"""
scout_heat.py — the live "heat" scanner behind #signals.

Every evening it scores ~1,200 US stocks under $5 on the 13-signal checklist that was
backtested on 2019-2023, checks the market backdrop filter, flags top/exit warnings,
and assigns each stock a STAGE:

  💤 0 Quiet        score 0-2
  🌱 1 Setup        score 3-4    something is brewing (catalyst, distress, early fails)
  🔥 2 Heating      score 5-6    crowd and squeeze signals are joining in
  🚀 3 Confluence   score 7+     the zone where big runs were most likely in the backtest
  (Live scores run about one point lower than the original backtest because the same-day fails
   sources are stricter, so every stage is one point lower; re-tested on those sources, 2019-2023.)
  ⚠️ 4 Top warning  any exit flag during a run (company selling stock, blow-off break)
  🧊 5 Fading       fell 35%+ from its recent high after a run (trailing stop zone)

"Entry rules met" (🎯) = stage 3 (7+) AND market backdrop rising AND not already up 50%+ in 60 days.

Live data differs from the backtest in two ways, stated on every post:
  - The two fails signals use same-day sources (Reg SHO threshold lists, FINRA daily short volume)
    instead of the SEC fails files the backtest used, which arrive ~2 weeks late.
  - Price, volume and momentum come from Yahoo daily data instead of SEC fails prices.
"""
import datetime as dt
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "heat")
SEC_H = {"User-Agent": "StockScout research tool contact: your-email@example.com"}
EFTS = "https://efts.sec.gov/LATEST/search-index"
os.makedirs(DATA, exist_ok=True)

SIGNALS = [
    ("s_cheap", "💵", "Under $5"),
    ("s_mom", "📈", "Up 50%+ in a month"),
    ("s_high", "🏔️", "At a 1-year high"),
    ("s_fails_spike", "🧨", "Short-sale / delivery-fail spike"),
    ("s_fails_persist", "🔁", "On the Reg SHO threshold list (fails 5+ days straight)"),
    ("s_short_rising", "🩳", "Short sellers adding 25%+"),
    ("s_vol_surge", "📢", "Volume 5x normal"),
    ("s_merger", "🤝", "Merger / letter of intent filed"),
    ("s_vote", "🗳️", "Vote / merger paperwork pending"),
    ("s_dividend", "🎁", "Special dividend / spin-off"),
    ("s_distress", "🩹", "Delisting warning in the last year"),
    ("s_meme", "🦍", "Meme mood across the market"),
    ("s_cluster", "🧲", "3+ signals fired within 2 weeks"),
]
STAGES = {
    0: ("💤", "Quiet", "Nothing lining up. Ignore."),
    1: ("🌱", "Setup", "Something is brewing (a catalyst, distress, or early squeeze pressure). Watch list only."),
    2: ("🔥", "Heating", "Crowd and squeeze signals are joining the setup. Research it now; this is where TRCH sat in Nov 2020."),
    3: ("🚀", "Confluence", "7+ signals at once: the zone where big runs were most likely in the backtest (TRCH hit 9–11 from Dec 2020 to Jan 2021)."),
    4: ("⚠️", "Top warning", "An exit signal fired during a run (company selling stock into it, or a blow-off break). Take profits; no new buys."),
    5: ("🧊", "Fading", "Down 35%+ from its recent high after a run. The trailing stop says out."),
}
# from the 2019-2023 backtest (score first reached, next 4 months)
TRACK = {
    1: "Doubled within 4 months: ~13% of the time.",
    2: "Doubled within 4 months: ~14–16% of the time.",
    3: "Doubled within 4 months: ~17% (20% in meme moods). As a buy rule (rising market, 35% trailing stop): 48% of 67 trades won; winners +95%, losers −29%.",
    4: "TRCH's peak came the day its second stock-sale filing hit (Jun 21 2021); it fell 82% in four weeks.",
    5: "The 35% trailing stop was the best-performing exit in the backtest.",
}


# ---------------------------------------------------------------- universe and prices
def universe():
    cache = os.path.join(DATA, "universe.json")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 20 * 3600:
        return json.load(open(cache))
    import yfinance as yf
    from yfinance import EquityQuery as EQ
    q = EQ("and", [EQ("lt", ["intradayprice", 5]), EQ("gt", ["intradayprice", 0.2]),
                   EQ("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE"]), EQ("gt", ["avgdailyvol3m", 100000])])
    out = []
    for off in range(0, 5000, 250):
        r = yf.screen(q, size=250, offset=off, sortField="intradaymarketcap", sortAsc=False)
        qs = r.get("quotes", [])
        out += [{"t": x["symbol"], "name": x.get("shortName") or x.get("longName") or x["symbol"]} for x in qs]
        if len(qs) < 250:
            break
    json.dump(out, open(cache, "w"))
    return out


def prices(tickers):
    import yfinance as yf
    close, vol = {}, {}
    for i in range(0, len(tickers), 250):
        chunk = tickers[i:i + 250]
        d = yf.download(chunk, period="1y", interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=True)
        for t in chunk:
            try:
                sub = d[t] if len(chunk) > 1 else d
                c, v = sub["Close"].dropna(), sub["Volume"].dropna()
                if len(c) >= 30:
                    close[t], vol[t] = c, v
            except Exception:
                pass
    return close, vol


# ---------------------------------------------------------------- SEC fails-to-deliver (lagged ~2 weeks)
def ftd_recent(n_files=5):
    import io
    import zipfile
    cache = os.path.join(DATA, "ftd_recent.pkl")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 3 * 86400:
        return pd.read_pickle(cache)
    frames, m = [], pd.Period(dt.date.today(), "M")
    for k in range(4):
        for half in "ba":
            name = f"cnsfails{(m - k).strftime('%Y%m')}{half}"
            r = requests.get(f"https://www.sec.gov/files/data/fails-deliver-data/{name}.zip", headers=SEC_H, timeout=90)
            if r.status_code != 200 or r.content[:2] != b"PK":
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]), sep="|", dtype=str, encoding="latin-1", on_bad_lines="skip")
            df.columns = [c.strip().upper() for c in df.columns]
            df = df.rename(columns={"SETTLEMENT DATE": "settle", "SYMBOL": "t", "QUANTITY (FAILS)": "fails"})
            df = df[pd.to_numeric(df.settle, errors="coerce").notna()]
            frames.append(df[["settle", "t", "fails"]])
            if len(frames) >= n_files:
                break
        if len(frames) >= n_files:
            break
    f = pd.concat(frames)
    f["settle"] = pd.to_datetime(f.settle, format="%Y%m%d")
    f["fails"] = pd.to_numeric(f.fails, errors="coerce").fillna(0)
    f["t"] = f.t.str.strip().str.upper()
    f.to_pickle(cache)
    return f


def ftd_flags(f):
    last_day = f.settle.max()
    days = sorted(f.settle.unique())
    last10 = days[-10:]
    prior = [d for d in days if d < last10[0]]
    out = {}
    for t, g in f.groupby("t"):
        recent = g[g.settle.isin(last10)]
        base = g[g.settle.isin(prior)].fails.sum() / max(1, len(prior))
        mx = recent.fails.max() if len(recent) else 0
        out[t] = {"s_fails_spike": bool(mx >= 5 * base and mx >= 250_000),
                  "s_fails_persist": bool(recent.settle.nunique() >= 8)}
    return out, pd.Timestamp(last_day).date()


# ---------------------------------------------------------------- same-day replacements for the delayed SEC fails data
WEB_H = {"User-Agent": "Mozilla/5.0 StockScout personal research"}


def _trading_days(n):
    days, d = [], dt.date.today()
    while len(days) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return days                      # most recent first; holidays simply come back empty


def _cached_get(url, path):
    if os.path.exists(path):
        return open(path).read()
    r = requests.get(url, headers=WEB_H, timeout=40)
    if r.status_code != 200 or len(r.text) < 50:
        return None
    open(path, "w").write(r.text)
    return r.text


def threshold_lists(n_days=10):
    """Reg SHO threshold lists (Nasdaq + NYSE family): stocks with 5+ straight settlement days of large delivery fails."""
    cdir = os.path.join(DATA, "regsho"); os.makedirs(cdir, exist_ok=True)
    out = {}
    for d in _trading_days(n_days + 4):
        names = set()
        nq = _cached_get(f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{d:%Y%m%d}.txt", os.path.join(cdir, f"nq_{d}.txt"))
        ny = _cached_get(f"https://www.nyse.com/api/regulatory/threshold-securities/download?selectedDate={d:%d-%b-%Y}",
                         os.path.join(cdir, f"ny_{d}.txt"))
        for txt in (nq, ny):
            for line in (txt or "").splitlines()[1:]:
                parts = line.split("|")
                if len(parts) > 3 and parts[0] and parts[0].isupper() and not parts[0].isdigit():
                    names.add(parts[0].strip())
        if names:
            out[d] = names
        if len(out) >= n_days:
            break
    return out                       # {date: set(tickers)}


def short_volume(n_days=25):
    """FINRA daily short-sale volume, published the next morning."""
    cdir = os.path.join(DATA, "shortvol"); os.makedirs(cdir, exist_ok=True)
    frames = []
    for d in _trading_days(n_days + 6):
        txt = _cached_get(f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d:%Y%m%d}.txt", os.path.join(cdir, f"{d}.txt"))
        if not txt:
            continue
        rows = [l.split("|") for l in txt.splitlines()[1:] if l.count("|") >= 4 and l[:2].isdigit()]
        df = pd.DataFrame(rows).iloc[:, :5]
        df.columns = ["date", "t", "short", "exempt", "total"]
        frames.append(df)
        if len(frames) >= n_days:
            break
    f = pd.concat(frames)
    f["date"] = pd.to_datetime(f.date, format="%Y%m%d")
    for c in ("short", "total"):
        f[c] = pd.to_numeric(f[c], errors="coerce").fillna(0)
    return f


def live_fails_flags():
    """Same-day versions of the two fails signals.
    persist = on today's (latest) threshold list
    spike   = short-sale volume >= 5x its prior 20-day average (and >= 1M shares), or newly added to the threshold list in the last 5 days"""
    th = threshold_lists()
    days = sorted(th)                               # oldest -> newest
    latest = th[days[-1]] if days else set()
    new5 = set()
    for i, d in enumerate(days[-5:]):
        before = set().union(*[th[x] for x in days[:len(days) - 5 + i]]) if len(days) > 5 else set()
        new5 |= th[d] - before
    sv = short_volume()
    last = sv.date.max()
    cur = sv[sv.date == last].set_index("t").short
    prior = sv[sv.date < last].groupby("t").short.mean()
    spike = set(cur[(cur >= 5 * prior.reindex(cur.index).fillna(0)) & (cur >= 1_000_000)].index)
    flags = {}
    for t in set(latest) | spike | new5:
        flags[t] = {"s_fails_persist": t in latest, "s_fails_spike": (t in spike) or (t in new5)}
    asof = {"threshold": days[-1].isoformat() if days else None, "short_volume": pd.Timestamp(last).date().isoformat()}
    return flags, asof


# ---------------------------------------------------------------- FINRA short interest (twice a month)
def _finra_one(t):
    from io import StringIO
    start = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    body = {"limit": 10, "compareFilters": [{"compareType": "equal", "fieldName": "symbolCode", "fieldValue": t}],
            "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": start, "endDate": dt.date.today().isoformat()}]}
    for attempt in range(4):
        try:
            r = requests.post("https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest", json=body, timeout=40)
            if r.status_code == 200:
                if not r.text.strip():
                    return t, None
                d = pd.read_csv(StringIO(r.text)).sort_values("settlementDate")
                return t, d.currentShortPositionQuantity.tolist()
        except Exception:
            pass
        time.sleep(2 + 3 * attempt)
    return t, None


def finra_flags(tickers):
    cache = os.path.join(DATA, "finra.json")
    data = json.load(open(cache)) if os.path.exists(cache) else {}
    fresh = data.get("_date") == dt.date.today().isoformat() or (
        data.get("_date") and (dt.date.today() - dt.date.fromisoformat(data["_date"])).days < 4)
    todo = [t for t in tickers if not fresh or t not in data]
    if todo:
        with ThreadPoolExecutor(4) as ex:
            for t, shorts in ex.map(_finra_one, todo):
                data[t] = shorts
        data["_date"] = dt.date.today().isoformat()
        json.dump(data, open(cache, "w"))
    out = {}
    for t in tickers:
        s = data.get(t)
        out[t] = bool(s and len(s) >= 3 and s[-1] >= 1.25 * s[-3] and s[-1] >= 500_000)
    return out


# ---------------------------------------------------------------- SEC filings (current tickers, kept up to date)
EDGAR_GROUPS = {
    "merger": ('"letter of intent" OR "merger agreement" OR "business combination agreement" OR "arrangement agreement" '
               'OR "reverse merger" OR "share exchange agreement"', "8-K"),
    "dividend": ('"special dividend" OR "spin-off" OR "spinoff" OR "preferred stock dividend"', "8-K"),
    "distress": ('"5550(a)(2)" OR "minimum bid price"', "8-K"),
    "atm": ('"at the market offering" OR "at-the-market offering" OR "sales agreement"', "424B5"),
    "vote": ('"merger" OR "business combination"', "DEFM14A,S-4,425"),
}


def edgar_update():
    store = os.path.join(DATA, "edgar_live.pkl")
    old = pd.read_pickle(store) if os.path.exists(store) else pd.DataFrame(columns=["group", "date", "t", "form", "adsh"])
    start = (pd.to_datetime(old.date).max() - pd.Timedelta(days=2)).date() if len(old) else dt.date.today() - dt.timedelta(days=370)
    rows = []
    for g, (q, forms) in EDGAR_GROUPS.items():
        s = start
        while s <= dt.date.today():
            e = min(dt.date.today(), s + dt.timedelta(days=30))
            frm = 0
            while True:
                try:
                    r = requests.get(EFTS, params={"q": q, "forms": forms, "dateRange": "custom", "startdt": s.isoformat(),
                                                   "enddt": e.isoformat(), "from": frm}, headers=SEC_H, timeout=60)
                    body = r.json().get("hits", {})
                except Exception:
                    time.sleep(3); continue
                hits = body.get("hits", [])
                for h in hits:
                    src = h["_source"]
                    for name in src.get("display_names") or []:
                        m = re.search(r"\(([A-Z0-9.\-, ]+)\)\s+\(CIK", name)
                        if not m:
                            continue
                        for t in m.group(1).split(","):
                            rows.append({"group": g, "date": src.get("file_date"), "t": t.strip(), "form": src.get("form"),
                                         "adsh": h["_id"].split(":")[0]})
                frm += 100
                time.sleep(0.15)
                if not hits or frm >= min((body.get("total") or {}).get("value", 0), 10000):
                    break
            s = e + dt.timedelta(days=1)
    new = pd.concat([old, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(["group", "t", "adsh"])
    new["date"] = pd.to_datetime(new.date)
    new = new[new.date >= pd.Timestamp(dt.date.today() - dt.timedelta(days=400))]
    new.to_pickle(store)
    return new


def edgar_flags(ed, t, today):
    sub = ed[ed.t == t]
    out = {}
    for g, col, days in (("merger", "s_merger", 120), ("vote", "s_vote", 90), ("dividend", "s_dividend", 180),
                         ("distress", "s_distress", 365)):
        d = sub[sub.group == g].date
        out[col] = bool(((today - d).dt.days.between(0, days)).any())
    atm = sub[sub.group == "atm"].date.sort_values()
    out["_atm10"] = bool(((today - atm).dt.days.between(0, 10)).any())
    out["_atm_two_15"] = int(((today - atm).dt.days.between(0, 15)).sum()) >= 2
    out["_filings"] = [(r.date.date().isoformat(), r.group, r.form) for r in sub.sort_values("date").tail(6).itertuples()]
    return out


# ---------------------------------------------------------------- scoring
def scan(log=print):
    U = universe()
    names = {u["t"]: u["name"] for u in U}
    tickers = list(names)
    log(f"universe {len(tickers)}")
    close, vol = prices(tickers)
    log(f"prices {len(close)}")
    today = pd.Timestamp(dt.date.today())
    # market backdrop: median 60-trading-day change across the universe (the backtest's key filter)
    chg60 = [c.iloc[-1] / c.iloc[-61] for c in close.values() if len(c) > 61 and c.iloc[-61] > 0]
    breadth = float(np.median(chg60)) if chg60 else 1.0
    # meme mood proxy: share of the universe with 5-day volume >= 5x its prior 50-day average, vs its own past year
    surge_share = []
    vols = [v for v in vol.values() if len(v) >= 120]
    for back in range(0, 200, 5):
        n = s = 0
        for v in vols:
            if len(v) < back + 60:
                continue
            seg = v.iloc[: len(v) - back]
            a5, a50 = seg.iloc[-5:].mean(), seg.iloc[-55:-5].mean()
            n += 1
            s += a50 > 0 and a5 >= 5 * a50
        surge_share.append(s / max(n, 1))
    meme = bool(surge_share and surge_share[0] >= np.percentile(surge_share, 80) and surge_share[0] > 0)
    try:
        fflags, fails_asof = live_fails_flags()
    except Exception as e:
        log(f"daily fails sources unavailable ({e}); falling back to the delayed SEC files")
        try:
            fflags, d = ftd_flags(ftd_recent()); fails_asof = {"sec_delayed": d.isoformat()}
        except Exception:
            fflags, fails_asof = {}, {}
    shorts = finra_flags(list(close))
    log("finra done")
    ed = edgar_update()
    log(f"edgar rows {len(ed)}")
    rows = []
    for t, c in close.items():
        v = vol[t]
        p = float(c.iloc[-1])
        p21 = float(c.iloc[-22]) if len(c) > 22 else np.nan
        p60 = float(c.iloc[-61]) if len(c) > 61 else np.nan
        hi_prior = float(c.iloc[:-1].tail(252).max())
        a10, a50 = v.iloc[-10:].mean(), v.iloc[-60:-10].mean()
        e = edgar_flags(ed, t, today)
        s = {
            "s_cheap": 0.05 <= p < 5,
            "s_mom": bool(p21 and p / p21 >= 1.5),
            "s_high": len(c) >= 60 and p >= hi_prior,
            "s_fails_spike": fflags.get(t, {}).get("s_fails_spike", False),
            "s_fails_persist": fflags.get(t, {}).get("s_fails_persist", False),
            "s_short_rising": shorts.get(t, False),
            "s_vol_surge": bool(a50 > 0 and a10 >= 5 * a50 and a10 >= 1_000_000),
            "s_merger": e["s_merger"], "s_vote": e["s_vote"], "s_dividend": e["s_dividend"], "s_distress": e["s_distress"],
            "s_meme": meme,
        }
        # cluster: 3+ distinct non-cheap, non-market signals active now or in the last 14 days
        recent_mom = bool(len(c) > 32 and (c.iloc[-10:] / c.shift(21).iloc[-10:] >= 1.5).any())
        recent_high = bool(len(c) > 70 and (c.iloc[-10:] >= c.rolling(252, min_periods=60).max().shift(1).iloc[-10:]).any())
        stock_specific = [s[k] for k in ("s_fails_spike", "s_fails_persist", "s_short_rising", "s_vol_surge", "s_merger",
                                         "s_vote", "s_dividend", "s_distress")] + [recent_mom, recent_high]
        s["s_cluster"] = sum(bool(x) for x in stock_specific) >= 3
        score = sum(bool(s[k]) for k, _, _ in SIGNALS)
        run60 = p / p60 if p60 and p60 > 0 else np.nan
        run2x = bool(run60 >= 2)
        mx10, mx30 = float(c.iloc[-10:].max()), float(c.iloc[-30:].max())
        ran_recently = bool(len(c) > 90 and (c.iloc[-30:] / c.shift(60).iloc[-30:] >= 2).any())
        exits = {"Company selling new stock into the run": e["_atm10"] and run2x,
                 "Second stock-sale filing within 15 days": e["_atm_two_15"] and ran_recently,
                 "Blow-off break: 20%+ off a 10-day high after doubling": ran_recently and p <= 0.8 * mx10}
        fading = ran_recently and p <= 0.65 * mx30
        if any(exits.values()):
            stage = 4
        elif fading:
            stage = 5
        elif score >= 7:
            stage = 3
        elif score >= 5:
            stage = 2
        elif score >= 3:
            stage = 1
        else:
            stage = 0
        entry_ok = stage == 3 and breadth > 1.10 and not (run60 >= 1.5)
        rows.append({"t": t, "name": names.get(t, t), "price": round(p, 4), "score": score, "stage": stage, "entry_ok": entry_ok,
                     "run60": None if np.isnan(run60) else round(run60, 2), "chg1d": round((p / float(c.iloc[-2]) - 1) * 100, 1),
                     "high30": round(mx30, 4), "signals": {k: bool(s[k]) for k, _, _ in SIGNALS},
                     "exits": [k for k, v in exits.items() if v], "filings": e["_filings"]})
    res = {"date": dt.date.today().isoformat(), "breadth": round(breadth, 3), "risk_on": breadth > 1.10, "meme": meme,
           "fails_asof": fails_asof, "rows": rows}
    json.dump(res, open(os.path.join(DATA, f"scan_{res['date']}.json"), "w"))
    return res


# ---------------------------------------------------------------- what changed since last scan
def changes(res):
    path = os.path.join(DATA, "state.json")
    prev = json.load(open(path)) if os.path.exists(path) else {}
    out = []
    for r in res["rows"]:
        before = prev.get(r["t"])
        if before is None or r["stage"] != before:
            if r["stage"] >= 2 or (before is not None and before >= 2):
                out.append((r, before))
    json.dump({r["t"]: r["stage"] for r in res["rows"]}, open(path, "w"))
    return out, bool(prev)


# ---------------------------------------------------------------- Discord cards
def _attach(card_dict, path):
    """Mark a card to carry a chart image (the bot uploads the file and shows it inside the card)."""
    if path and os.path.exists(path):
        card_dict["_file"] = path
        card_dict["image"] = {"url": "attachment://" + os.path.basename(path)}
    return card_dict


def _chart(t, **kw):
    try:
        import scout_charts
        return scout_charts.make_chart(t, **kw)
    except Exception as e:
        print(f"chart failed for {t}: {e}")
        return None
def _bar(score):
    return "🟩" * min(score, 13) + "⬜" * (13 - min(score, 13))


def backdrop_line(res):
    b = (res["breadth"] - 1) * 100
    if res["risk_on"]:
        return f"🟢 **Market backdrop: RISING** (cheap stocks {b:+.0f}% over 60 days). Confluence setups are tradeable."
    return (f"🔴 **Market backdrop: NOT RISING** (cheap stocks {b:+.0f}% over 60 days, needs +10%). "
            "In the backtest, setups in markets like this lost money on average: watch and research only.")


def card(r, res, before=None):
    e, name, meaning = STAGES[r["stage"]]
    hit = [f"{em} {lab}" for k, em, lab in SIGNALS if r["signals"][k]]
    h = None
    if r["stage"] in (2, 3, 4, 5):
        try:
            h = stock_history(r["t"])
        except Exception:
            h = None
    ran = already_ran(h)
    if ran and r["stage"] in (2, 3):
        e, name = "🏁", f"{name} · already ran"
    title = f"{e} {r['t']} · ${r['price']:.2f} ({r['chg1d']:+.1f}% today) · Stage {r['stage']} {name}"
    if before is not None and before != r["stage"]:
        title += f"  (was {STAGES[before][0]} {STAGES[before][1]})"
    plain = {
        3: ("🤔 **Why it's here:** lots of the warning signs we found before big runs (like TRCH's) are lighting up at once. "
            "It's a stock that *could* take off, not one that will."),
        4: "🤔 **Why it's here:** it already ran up and just showed a sign the run may be ending (a sharp drop off its high, or the company selling new shares).",
        5: "🤔 **Why it's here:** its run is over: it's down 35%+ from its recent high.",
    }.get(r["stage"], "🤔 **Why it's here:** a few early signs. Too early to matter.")
    if r["stage"] == 3 and r["entry_ok"]:
        todo = "👉 **What to do:** it qualifies. Follow the 🟢 BUY card in #signals (exact buy price, sell line, and size)."
    elif r["stage"] == 3:
        todo = "👉 **What to do:** nothing yet. Watch only (reason below). If it ever qualifies, a 🟢 BUY card will post in #signals."
    elif r["stage"] in (4, 5):
        todo = "👉 **What to do:** if you own it, take your profit / get out. If you don't own it, don't buy it."
    else:
        todo = "👉 **What to do:** nothing."
    lines = [f"**{r['name']}**", todo, plain, "", f"{_bar(r['score'])}  **{r['score']}/13 signals**", "**Signals hit:**\n" + ("\n".join(hit) or "none")]
    if r["exits"]:
        lines.append("\n**🚨 Exit warnings:**\n" + "\n".join(f"• {x}" for x in r["exits"]))
    if TRACK.get(r["stage"]):
        lines.append(f"**Track record:** {TRACK[r['stage']]}")
    if r["stage"] == 3:
        if r["entry_ok"]:
            lines.append("\n🎯 **Entry rules met.** Plan from the backtest: small position, no margin, sell if it falls 35% from its high "
                         "or on the first exit warning.")
        else:
            why = []
            if not res["risk_on"]:
                why.append("the market backdrop isn't rising")
            if ran:
                why.append(f"it already reached its usual peak (${h['high_since_low']:.2f}) and is {h['off_high_pct']}% off that high")
            elif r["run60"] and r["run60"] >= 1.5:
                why.append(f"it's already up {(r['run60'] - 1) * 100:.0f}% in 60 days (late)")
            lines.append("\n⏸️ **Watch, don't chase:** " + " and ".join(why or ["entry rules not met"]) + ".")
            if ran:
                lines.append("🧭 **What usually comes next:** after a run like this, it usually gave back about "
                             f"**{h['median_give_back_pct']}%** of the peak price before the next run. A second leg up can happen "
                             "(news, a squeeze), but that's the exception, not the pattern. **Waiting costs nothing**; "
                             "if it sets up again, the scanner will flag it.")
    if r["stage"] == 4:
        pass
    if r["stage"] == 5:
        lines.append(f"\nRecent high was ${r['high30']:.2f}.")
    if h:
        lines.append("\n" + history_line(h))
    if r["filings"]:
        lines.append("\n**Recent filings:** " + "; ".join(f"{d} {g}" for d, g, f in r["filings"][-3:]))
    color = {0: 0x4A5568, 1: 0x2F6F4E, 2: 0x975A16, 3: 0x1F3A5F, 4: 0x9B2C2C, 5: 0x4A5568}[r["stage"]]
    out = {"color": color, "title": title[:256], "description": "\n".join(lines)[:4000]}
    if r["stage"] >= 2:
        _attach(out, _chart(r["t"], title=f"{r['t']}  ${r['price']:.2f}  ·  Stage {r['stage']} {name}  ·  {r['score']}/13", hist=h))
    return out


def embeds(res, changed, first_run, top_n=5):
    rows = res["rows"]
    st3 = sorted([r for r in rows if r["stage"] == 3], key=lambda r: -r["score"])
    st4 = sorted([r for r in rows if r["stage"] == 4], key=lambda r: -r["score"])
    ready = [r["t"] for r in rows if r["entry_ok"]]
    b = (res["breadth"] - 1) * 100
    market = (f"🟢 Cheap stocks are **rising** ({b:+.0f}% over 60 days), so setups can be traded." if res["risk_on"] else
              f"🔴 Cheap stocks are **falling** ({b:+.0f}% over 60 days). In past tests, buying these setups in a falling market lost money.")
    todo = (f"👉 **What to do:** **{', '.join(ready)}** qualif{'ies' if len(ready) == 1 else 'y'}: follow the 🟢 BUY card in #signals." if ready else
            "👉 **What to do:** nothing today. This channel is a watch list. When a stock qualifies, a 🟢 BUY card goes to #signals with exact prices.")
    head = {
        "color": 0x1F3A5F,
        "title": f"🌡️ Cheap-stock radar · {dt.date.fromisoformat(res['date']).strftime('%a %b %d')}",
        "description": "\n".join([
            f"📌 **Today:** {market}",
            f"• 🚀 **{len(st3)}** stocks have many run signs lined up (could take off; shown below)",
            f"• ⚠️ **{len(st4)}** stocks that already ran just flashed a top warning (listed at the bottom)",
            "", todo, "",
            "🤔 **What this is:** every weekday the bot checks ~1,250 stocks under $5 for the warning signs we found before big runs like TRCH's. "
            "These are lottery-style stocks: even the best setups lost money about 6 times in 10; a few huge winners carried the average."]),
    }
    cards = [head]
    if not ready:
        # Quiet mode: nothing to act on, so one short card instead of a wall of details.
        extra = []
        if st3:
            extra.append("🚀 **Watching:** " + ", ".join(r["t"] for r in st3[:15]) + (f" (+{len(st3) - 15} more)" if len(st3) > 15 else "")
                         + "\nCurious about one? Type `!heat TICKER` in #lookup. No need to act.")
        if st4:
            extra.append("⚠️ **Already ran and flashing a top:** " + ", ".join(r["t"] for r in st4[:15])
                         + "\nOnly matters if you own one: then take your profit. Otherwise skip them.")
        extra.append("🔕 **Short version:** you can mute this channel. Anything you need to act on goes to #signals with an @mention.")
        head["description"] = (head["description"].replace(" (could take off; shown below)", "").replace(" (listed at the bottom)", "")
                               + "\n\n" + "\n\n".join(extra))[:4000]
        head["footer"] = {"text": "Research only, not investment advice"}
        return cards
    for r in st3[:top_n]:
        cards.append(card(r, res))
    if len(st3) > top_n:
        cards[-1]["description"] = (cards[-1]["description"] + f"\n\n…plus {len(st3) - top_n} more in this stage: "
                                    + ", ".join(r["t"] for r in st3[top_n:top_n + 15]))[:4000]
    if st4:
        cards.append({"color": 0x9B2C2C, "title": f"⚠️ Top warnings ({len(st4)})",
                      "description": ("👉 **If you own any of these, take your profit / get out. If you don't, don't buy them.**\n\n"
                                      + "\n".join(f"**{r['t']}** ${r['price']:.2f} ({r['chg1d']:+.1f}% today)" for r in st4[:25]))[:4000]})
    fa = res.get("fails_asof") or {}
    cards[-1]["footer"] = {"text": "Research only, not investment advice · type a ticker in #lookup for the full report · !heat TICKER for its stage"}
    return cards


def heat_for(ticker, res):
    for r in res["rows"]:
        if r["t"] == ticker.upper():
            return r
    return None


# ---------------------------------------------------------------- #signals: buy-ready stocks, tracked until they close
SIG_PATH = os.path.join(DATA, "signals_book.json")
RISK_DEFAULT = {"source": "re-tested on the same-day sources, 2019-2023", "trades": 67, "win_pct": 47.8, "avg_win_pct": 95.3,
                "avg_loss_pct": -29.4, "avg_pct": 30.2, "avg_without_top5_pct": 4.6, "p6": 37.8, "p8": 10.9, "p10": 3.0,
                "median_days": 47, "worst_streak": 8, "bad_year": "2021: −24% per trade, 17% won"}


def risk_stats():
    p = os.path.join(DATA, "risk_stats.json")
    return dict(RISK_DEFAULT, **json.load(open(p))) if os.path.exists(p) else RISK_DEFAULT


def losing_streak(book):
    n = 0
    for c in sorted(book["closed"], key=lambda c: c["closed"]):
        n = 0 if c["result_pct"] > 0 else n + 1
    return n


def streak_card(n, R):
    if n < 4:
        return None
    worst = R.get("worst_streak", 8)
    if n >= worst + 4:
        lvl, color, msg = "🛑 STOP", 0x9B2C2C, (f"{n} losses in a row: well beyond the worst streak in testing ({worst}). "
                                                  "Treat the strategy as broken. Stop taking new signals until it's re-tested on recent data.")
    elif n >= worst + 2:
        lvl, color, msg = "⏸️ PAUSE", 0x9B2C2C, (f"{n} losses in a row: worse than anything in testing (worst was {worst}; a 10-loss streak showed up in only "
                                                   f"~{R['p10']:.0f}% of 50-signal stretches). The market may have changed. Pause new buys until a winner closes.")
    elif n >= 6:
        lvl, color, msg = "⚠️ ROUGH PATCH", 0x975A16, (f"{n} losses in a row. Painful, but it has happened: streaks of 6+ came up in ~{R['p6']:.0f}% of "
                                                        f"50-signal stretches, and the worst was {worst}. Keep sizes small; don't double up to win it back.")
    else:
        lvl, color, msg = "ℹ️ LOSING STREAK", 0x4A5568, (f"{n} losses in a row. Normal: only about {R['win_pct']:.0f}% of signals win, "
                                                         "and one big winner (+95% average) usually pays for several −29% losses.")
    todo = {"🛑 STOP": "👉 **What to do:** don't take new BUY cards until this strategy is re-tested. Keep (or close) open ones by their own sell rules.",
            "⏸️ PAUSE": "👉 **What to do:** skip new BUY cards until one of the open signals closes as a winner.",
            "⚠️ ROUGH PATCH": "👉 **What to do:** keep following the cards at the SAME small size. Don't bet bigger to win it back.",
            "ℹ️ LOSING STREAK": "👉 **What to do:** nothing different. This is normal for this strategy."}[lvl]
    return {"color": color, "title": f"{lvl} · {n} losing signals in a row",
            "description": "🤔 **Why you're seeing this:** losing streaks are part of every strategy. This card tells you whether this one is "
                           "still normal or a sign something changed.\n\n" + msg + "\n\n" + todo}


TRAIL = 0.35          # sell if price falls 35% from its highest close since the signal (best exit in the backtest)
MAX_DAYS = 120        # the backtest held at most 4 months


def _book():
    return json.load(open(SIG_PATH)) if os.path.exists(SIG_PATH) else {"open": {}, "closed": []}


def update_signals(res):
    """Open new signals for stocks meeting entry rules; update and close open ones. Returns (new, updates, closed, book)."""
    book = _book()
    today = res["date"]
    rows = {r["t"]: r for r in res["rows"]}
    new, updates, closed = [], [], []
    for t, s in list(book["open"].items()):
        r = rows.get(t)
        if r is None:
            continue
        p = r["price"]
        s["peak"] = max(s["peak"], p)
        s["last"] = p
        stop = round(s["peak"] * (1 - TRAIL), 4)
        days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(s["date"])).days
        reason = None
        if p <= stop:
            reason = f"price fell 35% from its peak (${s['peak']:.2f})"
        elif r["exits"]:
            reason = "exit warning: " + "; ".join(r["exits"])
        elif days >= MAX_DAYS:
            reason = "4-month time limit reached"
        if reason:
            s.update({"closed": today, "exit": p, "reason": reason, "result_pct": round((p / s["entry"] - 1) * 100, 1)})
            book["closed"].append(s); del book["open"][t]; closed.append(s)
        else:
            s["stop"] = stop
            updates.append(dict(s, days=days, gain_pct=round((p / s["entry"] - 1) * 100, 1)))
    for r in res["rows"]:
        if r["entry_ok"] and r["t"] not in book["open"]:
            s = {"t": r["t"], "name": r["name"], "date": today, "entry": r["price"], "peak": r["price"], "last": r["price"],
                 "stop": round(r["price"] * (1 - TRAIL), 4), "score": r["score"],
                 "signals": [k for k, v in r["signals"].items() if v]}
            book["open"][r["t"]] = s; new.append((s, r))
    json.dump(book, open(SIG_PATH, "w"), indent=1)
    return new, updates, closed, book


def signal_embeds(res, new, updates, closed, book):
    cards = []
    b = (res["breadth"] - 1) * 100
    R = risk_stats()
    for s, r in new:
        hit = [f"{em} {lab}" for k, em, lab in SIGNALS if r["signals"][k]]
        try:
            hobj = stock_history(s["t"]); hist = history_line(hobj)
        except Exception:
            hobj, hist = None, "📜 History unavailable today."
        cards.append({"color": 0x2F6F4E, "title": f"🟢 BUY SIGNAL · {s['t']} · ${s['entry']:.2f}",
                      "description": "\n".join([
                          f"**{s['name']}**",
                          f"{_bar(r['score'])}  **{r['score']}/13 signals**",
                          "", "✅ **WHEN TO BUY**",
                          f"• At the next market open, **if it's ${s['entry'] * 1.10:.2f} or less** (within 10% of today's ${s['entry']:.2f}).",
                          "• If it opens higher than that, **skip it**: the backtest bought at the signal-day close, so a big gap-up "
                          "means paying more than the tested price.",
                          "• **Size: small.** Lottery-ticket money you can afford to lose. No margin.",
                          "", "🚪 **WHEN TO SELL** (I'll post a 🔴 SELL here when one hits)",
                          f"• **Stop:** a close below **${s['stop']:.2f}** today. The stop moves up to 35% under the highest close as it rises.",
                          "• **Exit warning:** the company files to sell new stock into the run, or a blow-off break (20%+ off a 10-day high).",
                          f"• **Time:** after 4 months no matter what (typical hold in testing: {R['median_days']} days).",
                          "", hist,
                          "", "**Why it qualifies:** "
                          f"🚀 7+ signals · 🟢 market rising ({b:+.0f}% over 60 days) · not already up 50%+ "
                          f"({'up ' + format((r['run60'] - 1) * 100, '.0f') + '%' if r['run60'] else 'n/a'} in 60 days)",
                          "**Signals hit:** " + " · ".join(hit),
                          "", "⚖️ **The risk, in plain numbers** (" + R["source"] + f", {R['trades']} signals):",
                          f"• Won **{R['win_pct']:.0f}%** of the time. Winners averaged **+{R['avg_win_pct']:.0f}%**, losers **{R['avg_loss_pct']:.0f}%**.",
                          f"• Without the 5 biggest winners, the average was only **{R['avg_without_top5_pct']:+.1f}%**: the payoff depends on catching the rare big run.",
                          f"• Losing streaks: **6 in a row** came up in ~{R['p6']:.0f}% of 50-signal stretches, **8** in ~{R['p8']:.0f}%, **10** in ~{R['p10']:.0f}%. "
                          f"The worst that actually happened was **{R.get('worst_streak', 8)} in a row**. I'll warn you here if a streak builds.",
                          f"• Bad years happen: **{R.get('bad_year', '')}**, even with the market filter on.",
                      ])[:4000]})
        _attach(cards[-1], _chart(s["t"], title=f"BUY SIGNAL  {s['t']}  ${s['entry']:.2f}  ·  {r['score']}/13",
                                  entry=s["entry"], entry_date=s["date"], stop=s["stop"], hist=hobj))
    for s in closed:
        good = s["result_pct"] > 0
        cards.append({"color": 0x2F6F4E if good else 0x9B2C2C,
                      "title": f"🔴 SELL NOW · {s['t']} · {s['result_pct']:+.1f}% {'✅' if good else '❌'}",
                      "description": f"🚪 **Sell at the next open.** Reason: {s['reason']}.\n\n"
                                     f"Bought signal {s['date']} at ${s['entry']:.2f} → ${s['exit']:.2f} on {s['closed']} "
                                     f"(**{s['result_pct']:+.1f}%**). Highest close along the way: ${s['peak']:.2f} "
                                     f"({(s['peak'] / s['entry'] - 1) * 100:+.0f}%)."
                                     + ("" if good else "\n\nLosses are part of this strategy: most signals lose a little, and the rare big winner pays for them.")})
        _attach(cards[-1], _chart(s["t"], title=f"SELL  {s['t']}  {s['result_pct']:+.1f}%", entry=s["entry"], entry_date=s["date"],
                                  exit_price=s["exit"], exit_date=s["closed"]))
    if updates:
        lines = []
        for u in sorted(updates, key=lambda u: -u["gain_pct"]):
            arrow = "🟢" if u["gain_pct"] >= 0 else "🔴"
            lines.append(f"{arrow} **{u['t']}** ${u['last']:.2f} · **{u['gain_pct']:+.1f}%** since {u['date']} · peak ${u['peak']:.2f}\n"
                         f"   ↳ HOLD. Sell if it closes below **${u['stop']:.2f}** · day {u['days']}/120")
        cards.append({"color": 0x1F3A5F, "title": f"📒 Open signals ({len(updates)})", "description": "\n".join(lines)[:4000]})
        for u in sorted(updates, key=lambda u: -u["gain_pct"])[:4]:
            cards.append(_attach({"color": 0x1F3A5F, "title": f"📈 {u['t']} · {u['gain_pct']:+.1f}% · HOLD, sell below ${u['stop']:.2f}"},
                                 _chart(u["t"], title=f"{u['t']}  {u['gain_pct']:+.1f}%  ·  day {u['days']}/120", entry=u["entry"],
                                        entry_date=u["date"], stop=u["stop"])))
    sc = streak_card(losing_streak(book), R)
    if sc:
        cards.append(sc)
    done = book["closed"]
    if done:
        wins = [c for c in done if c["result_pct"] > 0]
        avg = sum(c["result_pct"] for c in done) / len(done)
        cards.append({"color": 0x4A5568, "title": "🧾 Signal scorecard (all closed signals)",
                      "description": f"{len(done)} closed · {len(wins)} won ({len(wins) / len(done) * 100:.0f}%) · average {avg:+.1f}% per signal\n"
                                     f"Best: {max(done, key=lambda c: c['result_pct'])['t']} {max(c['result_pct'] for c in done):+.0f}% · "
                                     f"Worst: {min(done, key=lambda c: c['result_pct'])['t']} {min(c['result_pct'] for c in done):+.0f}%"})
    if not cards:
        near = sorted([r for r in res["rows"] if r["stage"] == 3], key=lambda r: -r["score"])[:3]
        why = ("the market backdrop isn't rising "
               f"(cheap stocks {b:+.0f}% over 60 days; signals need +10%)") if not res["risk_on"] else "no stock has 7+ signals without already having run 50%+"
        cards.append({"color": 0x4A5568, "title": f"📭 No buy signals · {dt.date.fromisoformat(res['date']).strftime('%a %b %d')}",
                      "description": f"Nothing meets every entry rule today: {why}.\n"
                                     + (("Closest: " + ", ".join(f"**{r['t']}** ({r['score']}/13)" for r in near) + " — see #watchlist-radar.")
                                        if near else "See #watchlist-radar for stocks that are heating up.")
                                     + "\n\n🤔 **Why that's good news:** in the backtest, standing aside in markets like this avoided an average loss of about 5% per trade."
                                     + "\n👉 **What to do:** nothing. No buy today is a decision, not a missed chance. This channel will @mention you when one qualifies."})
    cards[-1]["footer"] = {"text": "Buy signals follow the backtested rules exactly. Research only, not investment advice."}
    return cards


# ---------------------------------------------------------------- each stock's own history of runs
def stock_history(ticker):
    """Every past 'run' in this stock: a close at least double its lowest close of the prior ~90 trading days.
    Each run is followed until the price falls 35% from its peak (the same trailing stop the signals use).
    Returns a summary, or None if there isn't enough history. Prices are split-adjusted (Yahoo)."""
    cache = os.path.join(DATA, "history"); os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"{ticker}.json")
    # refreshed once a day, so "how far into the run is it today" uses today's price
    if os.path.exists(path) and dt.date.fromtimestamp(os.path.getmtime(path)) == dt.date.today():
        h = json.load(open(path))
        if "high_since_low" in h or not h.get("n"):
            return h
    import yfinance as yf
    c = yf.Ticker(ticker).history(period="max", auto_adjust=True)["Close"].dropna()
    c = c[c > 0]
    if len(c) < 250:
        return None
    vals, dates = c.values, c.index
    runs, i, floor = [], 90, 0
    while i < len(vals):
        w0 = max(i - 90, floor)                      # a new run's low must come after the previous run's peak
        if w0 >= i:
            i += 1; continue
        lo_idx = w0 + int(np.argmin(vals[w0:i]))
        lo = vals[lo_idx]
        if vals[i] >= 2 * lo:
            peak_idx, j = i, i
            while j < len(vals) and vals[j] > 0.65 * vals[peak_idx]:
                if vals[j] > vals[peak_idx]:
                    peak_idx = j
                j += 1
            after = vals[peak_idx:min(len(vals), peak_idx + 120)]
            runs.append({"start": str(dates[lo_idx].date()), "low": round(float(lo), 4), "peak_date": str(dates[peak_idx].date()),
                         "peak": round(float(vals[peak_idx]), 4), "gain_pct": round((vals[peak_idx] / lo - 1) * 100),
                         "days_to_peak": int(peak_idx - lo_idx),
                         "give_back_pct": round((1 - after.min() / vals[peak_idx]) * 100)})
            floor = peak_idx + 1
            i = j + 1
        else:
            i += 1
    out = {"ticker": ticker, "since": str(dates[0].date()), "years": round(len(vals) / 252, 1), "runs": runs}
    if runs:
        g = [r["gain_pct"] for r in runs]; dd = [r["days_to_peak"] for r in runs]; gb = [r["give_back_pct"] for r in runs]
        out.update({"n": len(runs), "median_gain_pct": int(np.median(g)), "median_days": int(np.median(dd)),
                    "median_give_back_pct": int(np.median(gb)), "best_gain_pct": int(max(g))})
        lo90 = float(vals[-90:].min())
        out["low_90d"] = round(lo90, 4)
        out["typical_peak_from_low"] = round(lo90 * (1 + np.median(g) / 100), 4)
        out["up_from_low_pct"] = round((vals[-1] / lo90 - 1) * 100)
        k = len(vals) - 90 + int(np.argmin(vals[-90:]))
        hi = float(vals[k:].max()); hk = k + int(np.argmax(vals[k:]))
        out["high_since_low"] = round(hi, 4)
        out["high_since_low_date"] = str(dates[hk].date())
        out["off_high_pct"] = round((1 - vals[-1] / hi) * 100)
    else:
        out["n"] = 0
    json.dump(out, open(path, "w"))
    return out


def already_ran(h):
    """True when the stock already touched its usual run peak since its 90-day low and has pulled back 15%+."""
    if not h or not h.get("typical_peak_from_low") or not h.get("high_since_low"):
        return False
    return h["high_since_low"] >= 0.9 * h["typical_peak_from_low"] and h.get("off_high_pct", 0) >= 15


def history_line(h, price=None):
    if not h:
        return "📜 Not enough price history to judge how this stock usually runs."
    if not h.get("n"):
        return f"📜 **Its own history:** in {h['years']} years of data it never doubled off a 90-day low. A run here would be a first."
    s = (f"📜 **Its own history ({h['years']} yrs):** doubled off a low **{h['n']}×**. Typical run: **+{h['median_gain_pct']}%** "
         f"over **{h['median_days']} trading days** from the low, best +{h['best_gain_pct']}%; after peaking it usually gave back "
         f"**{h['median_give_back_pct']}%**.")
    if h.get("typical_peak_from_low"):
        tp, hi = h["typical_peak_from_low"], h.get("high_since_low")
        done = h["up_from_low_pct"] / max(h["median_gain_pct"], 1)
        s += (f"\n🎯 **Typical peak zone:** its 90-day low is ${h['low_90d']:.2f}; a typical run from there tops out near "
              f"**${tp:.2f}**.")
        if hi and hi >= 0.9 * tp:
            # it already got there: judge by the high it reached, not today's price
            s += (f" It already hit **${hi:.2f}** on {h['high_since_low_date']} and is now **{h['off_high_pct']}% below** that high → "
                  "🔴 late: it has already made a typical-size run. Late buyers usually catch the give-back, not the gain.")
        else:
            phase = ("🟢 early: most of a typical run would still be ahead" if done < 0.35 else
                     "🟡 midway through a typical-size run" if done < 0.8 else
                     "🔴 late: it has already made about a typical-size run")
            s += f" It's up {h['up_from_low_pct']}% from that low today → {phase}."
    return s
