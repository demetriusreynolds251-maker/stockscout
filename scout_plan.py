"""The monthly SPY plan ("volatility target with margin"), tested in research/strategy/.
Rule: once a month, after the last trading day's close, look at how much SPY swung over the last 20 trading days
(annualized). Hold  15% / that swing  times your account in SPY, never more than 1.5x. Under 1x, park the rest in a
T-bill fund (SGOV). Above 1x, the extra is borrowed on margin.
Backtest 1994-now (costs + margin interest at T-bill+3% included): 11.1%/yr vs 10.8% buy-and-hold SPY,
worst drop -41% vs -55%, worst year -22% vs -37%. Hidden check 2013-now: 14.2%/yr vs 14.8%, worst drop -26% vs -34%."""
import datetime as dt
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "plan.json")
TARGET, CAP, LOOK = 0.15, 1.5, 20
MARGIN_MIN = 2000   # US rule: a broker can't lend on margin until the account has $2,000
BT = {"full": ("1994 → now", "11.1%", "10.8%", "−41%", "−55%", "−22%", "−37%"),
      "hidden": ("2013 → now", "14.2%", "14.8%", "−26%", "−34%", "−14%", "−18%")}


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(d, open(STATE, "w"))


def today():
    import yfinance as yf
    h = yf.Ticker("SPY").history(period="3mo", auto_adjust=True)["Close"].dropna()
    r = h.pct_change().dropna()
    swing = float(r.iloc[-LOOK:].std() * math.sqrt(252))
    w = min(CAP, TARGET / swing)
    sg = yf.Ticker("SGOV").history(period="5d")["Close"].dropna()
    return {"date": str(h.index[-1].date()), "price": float(h.iloc[-1]), "swing": swing, "weight": w,
            "sgov": float(sg.iloc[-1]) if len(sg) else 100.0}


def is_last_trading_day(d=None):
    import pandas as pd
    from pandas.tseries.holiday import USFederalHolidayCalendar
    d = pd.Timestamp(d or dt.date.today())
    hol = USFederalHolidayCalendar().holidays(d, d + pd.Timedelta(days=10))
    nxt = d + pd.offsets.CustomBusinessDay(holidays=hol)
    return d.weekday() < 5 and nxt.month != d.month


def card(t, account=None, shares_now=None, monthly=False):
    w, p = t["weight"], t["price"]
    mood = "🟢 calm" if t["swing"] < 0.12 else "🟡 normal" if t["swing"] < 0.20 else "🟠 choppy" if t["swing"] < 0.30 else "🔴 stormy"
    lines = ["🤔 **What this is:** your main, slow-and-steady money plan. It holds the S&P 500 (SPY): more when the market is calm, "
             "less when it's wild, because big crashes usually start in wild markets. Once a month, one order. That's it.", "",
             f"**SPY ${p:,.2f}** · last 20 days it swung **{t['swing'] * 100:.1f}%/yr** ({mood})",
             f"Target: 15% ÷ {t['swing'] * 100:.1f}% = **{w:.2f}×** your account in SPY" + (" (capped at 1.5×)" if w >= CAP - 1e-9 else ""), ""]
    if account and account < MARGIN_MIN:
        we = min(w, 1.0)
        lines.append(f"💼 **For your ${account:,.0f}** (no margin until $2,000, so the most is 1.0×):")
        lines.append(f"• Hold **${account * we:,.2f} of SPY** (buy in dollars, fractional shares ≈ {account * we / p:.3f} share)")
        if we < 1:
            lines.append(f"• Keep the other **${account * (1 - we):,.2f}** in cash or SGOV until the market calms down")
        else:
            lines.append("• All of it in SPY: the market is calm enough")
        lines.append(f"• **Every time you add money:** invest it the same day, split the same way ({we * 100:.0f}% SPY right now). Don't wait for a dip.")
        lines.append(f"• 🎯 **Goal: reach $2,000.** That unlocks margin (up to 1.5×) and the dip boosts. You're {account / MARGIN_MIN * 100:.0f}% of the way there.")
        lines.append("")
    elif account:
        want = account * w
        n = int(want // p)
        lines.append(f"💼 **For your ${account:,.0f}:**")
        lines.append(f"• Hold **{n} shares of SPY** (≈ ${n * p:,.0f})")
        if w > 1:
            borrowed = max(n * p - account, 0)
            lines.append(f"• That borrows ≈ **${borrowed:,.0f} on margin** (at ~7%/yr that's about **${borrowed * 0.07 / 12:,.0f}/month** interest)")
        else:
            rest = account - n * p
            lines.append(f"• Put the rest, ≈ **${rest:,.0f}**, in **SGOV** (a T-bill fund paying ~short-term rates) ≈ {int(rest // t['sgov'])} shares")
        if shares_now is not None:
            diff = n - shares_now
            act = f"**BUY {diff}** more shares" if diff > 0 else f"**SELL {-diff}** shares" if diff < 0 else "**no change**"
            lines.append(f"• You have {shares_now} now → {act}")
        lines.append("")
    else:
        lines += ["💼 Type `!plan 10000` in #lookup (your account size) for exact share counts. `!plan set 10000` saves it for these monthly cards.", ""]
    lines += ["🧾 **How to place it**",
              "• Order type **LIMIT** at about the current price, time-in-force **Day**. Do it in the first hour after the open.",
              "• Only change if the new share count differs by **5%+** from what you hold (saves on small trades).",
              "", "🛡️ **Safety rules**",
              "• Never above **1.5×**. In 30+ years of testing the account never got close to a margin call (equity stayed above 65% of the position).",
              "• If your broker charges **more than 9%/yr** for margin, cap at **1.0×**: borrowing that expensive eats the extra return.",
              "• Next check: the last trading day of next month. Don't adjust in between.", "",
              f"📊 **Backtest** (costs + margin interest included): {BT['full'][0]}: **{BT['full'][1]}/yr** vs {BT['full'][2]} plain SPY · "
              f"worst drop **{BT['full'][3]}** vs {BT['full'][4]} · worst year **{BT['full'][5]}** vs {BT['full'][6]}.",
              f"Hidden check {BT['hidden'][0]}: **{BT['hidden'][1]}** vs {BT['hidden'][2]}, worst drop **{BT['hidden'][3]}** vs {BT['hidden'][4]}. "
              "Same-ish return as SPY, but much smaller crashes: more when calm, less when stormy."]
    title = ("📅 MONTHLY REBALANCE · " if monthly else "📐 SPY PLAN · ") + f"hold {w:.2f}× in SPY"
    return {"color": 0x2F6F4E if w >= 1 else 0x975A16, "title": title, "description": "\n".join(lines)[:4000],
            "footer": {"text": f"Based on the {t['date']} close · research only, not investment advice"}}
