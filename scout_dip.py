"""Dip boost: short margin trades on SPY and QQQ, layered on top of the monthly core plan (scout_plan).
Entry: the fund is above its 200-day average AND its 2-day RSI is under 10 -> buy +0.5x of the account (on margin) before the close.
Exit: the first close above the 5-day average, or after 10 trading days, whichever comes first.
Total exposure (core + boosts) never above 2.0x.
Checked at 2:45pm Central with the live price so orders can go in before the 3:00pm close (the backtest buys/sells at the close).
Backtest 2000-now with the core: 10.9%/yr vs 8.1% plain SPY ($1,000 -> $16,159 vs $8,009), worst drop -41% vs -55%.
Hidden 2013-now: 16.6%/yr vs 14.5%. Dip trades alone: ~70-78% winners, about +0.5% per trade over ~3.5 days."""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "dip_trades.json")
FUNDS = ("SPY", "QQQ")
BOOST, CAP, MAX_DAYS = 0.5, 2.0, 10


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"open": {}, "closed": []}


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"), indent=1)


def rsi2(c):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, 1e-9))


def live(t):
    """Daily closes with today's live price as the last close."""
    import yfinance as yf
    import pandas as pd
    h = yf.Ticker(t).history(period="2y", auto_adjust=True)["Close"].dropna()
    h.index = h.index.tz_localize(None).normalize()
    try:
        last = yf.Ticker(t).fast_info["last_price"]
        today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
        if last and today.weekday() < 5:
            h.loc[today] = float(last)
    except Exception:
        pass
    return h


def check(core_weight):
    """Returns (entries, exits, status) and updates the trade book. core_weight = today's monthly-plan exposure."""
    import pandas as pd
    s = load()
    entries, exits, status = [], [], {}
    today = str(pd.Timestamp.now(tz="America/New_York").date())
    used = core_weight + BOOST * len(s["open"])
    for t in FUNDS:
        c = live(t)
        ma200, ma5, r = c.rolling(200).mean().iloc[-1], c.rolling(5).mean().iloc[-1], rsi2(c).iloc[-1]
        p = float(c.iloc[-1])
        status[t] = {"price": p, "rsi2": float(r), "above200": bool(p > ma200), "ma5": float(ma5), "ma200": float(ma200)}
        if t in s["open"]:
            tr = s["open"][t]
            days = int(np.busday_count(tr["date"], today))
            if p > ma5 or days >= MAX_DAYS:
                pct = (p / tr["price"] - 1) * 100
                tr.update({"exit_date": today, "exit": p, "pct": pct, "why": "closed above its 5-day average" if p > ma5 else "10-day time limit"})
                s["closed"].append(dict(tr, t=t)); del s["open"][t]
                exits.append(dict(tr, t=t))
            else:
                status[t]["holding"] = {"days": days, "pct": (p / tr["price"] - 1) * 100}
        elif p > ma200 and r < 10:
            room = CAP - used
            if room >= BOOST - 1e-9:
                s["open"][t] = {"date": today, "price": p, "rsi2": float(r)}
                used += BOOST
                entries.append({"t": t, "price": p, "rsi2": float(r), "ma5": float(ma5)})
            else:
                status[t]["skipped"] = "margin cap reached"
    save(s)
    return entries, exits, status


def record():
    s = load()
    cl = s["closed"]
    if not cl:
        return "No dip trades closed yet."
    w = sum(1 for x in cl if x["pct"] > 0)
    avg = sum(x["pct"] for x in cl) / len(cl)
    return f"Live record: **{len(cl)} trades, {w} winners ({w / len(cl) * 100:.0f}%)**, average {avg:+.2f}% per trade (backtest: ~74% winners, about +0.5%)"


def cards(entries, exits, status, account=None):
    out = []
    small = bool(account) and account < 2000
    for e in entries:
        if small:
            out.append({"color": 0x4A5568, "title": f"📘 PRACTICE · DIP SIGNAL · {e['t']} · ${e['price']:.2f}",
                        "description": "\n".join([
                            f"{e['t']} just hit the dip-buy signal (RSI-2 = **{e['rsi2']:.0f}**, in an uptrend).",
                            f"**Nothing to do:** this trade uses margin, and your account (${account:,.0f}) is under the $2,000 margin minimum.",
                            "I'll track it anyway and post how it ends, so you can see how these trades go before you use real money on them.",
                            record()]),
                        "footer": {"text": "Practice only. Research, not investment advice."}})
            continue
        n = int(account * BOOST // e["price"]) if account else None
        size = f"**BUY {n} shares of {e['t']}** (≈ ${n * e['price']:,.0f}, half your account, on margin)" if n else \
            f"**BUY {e['t']}** worth half your account (type `!plan set 10000` with your size for exact shares)"
        out.append({"color": 0x2F6F4E, "title": f"🟢 DIP BOOST · BUY {e['t']} · ${e['price']:.2f}",
                    "description": "\n".join([
                        f"{e['t']} is in an uptrend (above its 200-day average) but just had a sharp 2-day dip (RSI-2 = **{e['rsi2']:.0f}**, buy zone is under 10).",
                        "", "✅ **WHEN TO BUY:** now, before today's 3:00pm Central close.",
                        f"• {size}",
                        "• Order: **LIMIT** at about the current price, time-in-force **Day**. This is on TOP of your monthly SPY plan.",
                        "", "🚪 **WHEN TO SELL:** I'll post a 🔴 SELL card here (checked daily at 2:45pm Central). Rule: the first day it closes above "
                        f"its 5-day average (about ${e['ma5']:.2f} today, it moves), or after 10 trading days at most.",
                        "", "📊 **Backtest:** these dip trades won **~70–78%** of the time, about **+0.5% per trade**, held **~3–4 days**, about 8 per year per fund. "
                        "Losers averaged about −1.3%. Losing streaks of 2–3 in a row are normal.",
                        "🛡️ Total exposure (monthly plan + boosts) is capped at **2.0×** your account.",
                        record()]),
                    "footer": {"text": "Research only, not investment advice."}})
    for x in exits:
        good = x["pct"] > 0
        if small:
            out.append({"color": 0x4A5568, "title": f"📘 PRACTICE · {x['t']} dip trade closed · {x['pct']:+.2f}% {'✅' if good else '❌'}",
                        "description": f"Bought {x['date']} at ${x['price']:.2f} → ${x['exit']:.2f} ({x['why']}).\n\n" + record(),
                        "footer": {"text": "Practice only. Research, not investment advice."}})
            continue
        out.append({"color": 0x2F6F4E if good else 0x9B2C2C, "title": f"🔴 SELL NOW · {x['t']} dip boost · {x['pct']:+.2f}% {'✅' if good else '❌'}",
                    "description": f"🚪 **Sell the boost shares before today's close** (keep your monthly-plan shares). Reason: {x['why']}.\n\n"
                                   f"Bought {x['date']} at ${x['price']:.2f} → ${x['exit']:.2f} today (**{x['pct']:+.2f}%** on the boost shares).\n\n" + record(),
                    "footer": {"text": "Research only, not investment advice."}})
    return out
