"""The 33 movers: learning cards, big-move alerts, and PRACTICE option-trade alerts.
Trade setup (tested on these 33, 2013-now): stock above its 200-day average + 2-day RSI under 10 -> buy; sell at the first close above the
5-day average (max 10 days). 68% of trades won in both 2013-2020 and 2021-now; about +0.5% / +1.0% per trade on the stock, ~4 trades a week.
The OPTION version (a call spread) has not been tested with real historical option prices yet, so cards are PRACTICE: the bot records the real
quoted price at entry and exit from the live option chain and keeps score, so we learn whether the option version makes money before using cash."""
import datetime as dt
import json
import math
import os

import scout_videos

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "movers")
os.makedirs(DATA, exist_ok=True)
BOOK = os.path.join(DATA, "practice_trades.json")

MOVERS = {
    "MSTR": ("Strategy (MicroStrategy)", "₿ Crypto-linked", "Owns a huge pile of Bitcoin, so it moves like a leveraged Bitcoin bet. Watch Bitcoin's price first."),
    "MARA": ("MARA Holdings", "₿ Crypto-linked", "Bitcoin miner. Moves with Bitcoin's price and with mining costs (electricity, the 'halving')."),
    "RIOT": ("Riot Platforms", "₿ Crypto-linked", "Bitcoin miner, also pitching its power sites to AI data centers. Bitcoin price + AI data-center deals."),
    "COIN": ("Coinbase", "₿ Crypto-linked", "Largest US crypto exchange. Moves with crypto prices, trading volume and crypto regulation news."),
    "NVDA": ("Nvidia", "🧠 AI chips", "Makes most AI chips. Moves on big-tech AI spending, China export rules, and (now) its CEO change."),
    "AMD": ("AMD", "🧠 AI chips", "Nvidia's main chip rival (AI chips + PC/server CPUs). Big AI customer deals move it hard."),
    "AVGO": ("Broadcom", "🧠 AI chips", "Builds custom AI chips for Google/Meta and networking chips. Moves on AI spending and big-customer news."),
    "MRVL": ("Marvell", "🧠 AI chips", "Custom AI chips and data-center networking. Very sensitive to Amazon/Microsoft AI orders."),
    "ARM": ("Arm Holdings", "🧠 AI chips", "Designs the chip blueprints inside almost every phone and many servers. Priced high, moves on AI hype."),
    "MU": ("Micron", "🧠 AI chips", "Memory chips (incl. the special memory AI chips need). Moves on memory prices, which swing in cycles."),
    "QCOM": ("Qualcomm", "🧠 AI chips", "Phone chips (Android, some Apple). Moves on phone sales and its push into PCs/AI."),
    "INTC": ("Intel", "🧠 AI chips", "Old chip giant in a turnaround, with government backing. Moves on factory news and turnaround progress."),
    "TSM": ("TSMC", "🧠 AI chips", "Taiwan factory that manufactures chips for Nvidia, Apple, AMD. Moves on AI demand and China-Taiwan tension."),
    "SMCI": ("Super Micro", "🏭 AI hardware", "Builds AI servers. Thin profits and past accounting trouble, so it swings hard on every headline."),
    "DELL": ("Dell", "🏭 AI hardware", "Sells AI servers and PCs. Moves on AI server orders and PC demand."),
    "VRT": ("Vertiv", "🏭 AI hardware", "Cooling and power gear for data centers. Hit hard by the data-center pause news; moves on construction outlook."),
    "AMAT": ("Applied Materials", "🏭 AI hardware", "Makes the machines that make chips. Moves on chip-factory spending and China export rules."),
    "LRCX": ("Lam Research", "🏭 AI hardware", "Chip-making equipment (etching). Moves with chip-factory spending, especially memory makers."),
    "PLTR": ("Palantir", "💻 Software & AI apps", "Data/AI software for governments and companies. Very popular with retail traders; moves on contracts and hype."),
    "ORCL": ("Oracle", "💻 Software & AI apps", "Databases + a fast-growing AI cloud funded with heavy borrowing. Moves on cloud deals (OpenAI) and debt worries."),
    "CRWD": ("CrowdStrike", "💻 Software & AI apps", "Cybersecurity software. Moves on earnings and big hacking news."),
    "PANW": ("Palo Alto Networks", "💻 Software & AI apps", "Cybersecurity. Moves on earnings, deals, and big security breaches."),
    "SNOW": ("Snowflake", "💻 Software & AI apps", "Cloud data storage for companies. Moves sharply on earnings (customer spending)."),
    "APP": ("AppLovin", "💻 Software & AI apps", "Mobile-app advertising powered by AI. Huge runs and drops; short-seller reports have hit it before."),
    "NFLX": ("Netflix", "💻 Software & AI apps", "Streaming. Moves mostly on earnings (subscribers, ads, pricing)."),
    "HOOD": ("Robinhood", "💳 Fintech", "Trading app. Moves with how much people trade: crypto and meme-stock frenzies help it."),
    "SOFI": ("SoFi", "💳 Fintech", "Online bank/lender. Moves on interest-rate expectations and member growth. Cheap options."),
    "NU": ("Nu Holdings", "💳 Fintech", "Digital bank in Brazil/Mexico. Moves on Latin American economy and currency. Cheap options."),
    "CVNA": ("Carvana", "💳 Fintech", "Online used-car seller with car loans. Very volatile; moves on earnings and short-seller fights."),
    "RKLB": ("Rocket Lab", "🚀 Space & future tech", "Small rockets + satellite parts. Moves on launch results and new rocket (Neutron) progress."),
    "ASTS": ("AST SpaceMobile", "🚀 Space & future tech", "Building satellites that connect directly to normal phones. Moves on launches and phone-carrier deals."),
    "IONQ": ("IonQ", "🚀 Space & future tech", "Quantum computing. Pure hype/news stock; moves on contracts and quantum breakthroughs (anyone's)."),
    "TSLA": ("Tesla", "🚗 EV", "Electric cars + robotaxi/robot promises. Moves on deliveries, Elon Musk news, and self-driving updates."),
}
ORDER = list(MOVERS)

LESSONS = [
    ("What an option is", "An option is a contract on 100 shares. A **CALL** goes up in value when the stock rises; a **PUT** goes up when the stock falls. "
     "You pay a price (the 'premium') up front; that's the most you can lose when you BUY an option."),
    ("Strike price", "The **strike** is the price the option is about. A $30 call on a $28 stock needs the stock above $30 at expiration to be worth anything then. "
     "Closer strikes cost more but win more often."),
    ("Expiration", "Every option has an **expiration date**. After it, the option is gone. Weekly options expire every Friday (some stocks every day of the week). "
     "Less time = cheaper, but it has less time to work."),
    ("Time decay", "Options lose a little value **every day**, even if the stock doesn't move (called 'theta'). That's why buying options and waiting is hard: "
     "you need the move to happen fairly soon."),
    ("The price is per share", "An option quoted at **$1.20** costs **$120** (it covers 100 shares). Always multiply by 100 before you buy."),
    ("Bid, ask, and limit orders", "**Bid** = what buyers pay, **ask** = what sellers want. Always use a **LIMIT** order near the middle. A market order on options "
     "can cost you 5–20% instantly."),
    ("Call spread (what our cards use)", "Buy one call and sell a higher-strike call, same expiration. It's cheaper than a plain call and the most you can lose is what you paid. "
     "The catch: your profit is capped at the gap between the strikes."),
    ("Why spreads fit small accounts", "A plain call on a $160 stock might cost $800. A $5-wide call spread on the same stock might cost $200, "
     "with a max profit of $300. Same direction, a fraction of the money at risk."),
    ("Implied volatility (IV)", "IV is how big a move the market is pricing in. High IV = expensive options (often before earnings). Buying right before earnings often "
     "loses even when you guess the direction, because the price drops after the news ('IV crush')."),
    ("Earnings", "Stocks can jump or drop 10–20% overnight on earnings. Our practice cards avoid holding options through earnings unless the card says so."),
    ("Take profits", "Plan the exit before you buy. Our cards: take profit at +50% of the spread's max gain, or when the stock bounces above its 5-day average; "
     "cut it if the spread loses half its value; always close before the last 2 days."),
    ("Position size", "Never put more than **10–20%** of your account into one option trade. Five losers in a row happens, and you need to still be in the game."),
    ("Assignment & expiration day", "If a short option in your spread finishes in the money you can be assigned shares. Simple fix: **close spreads before expiration day**. "
     "Webull also closes risky positions near expiration, but don't rely on it."),
    ("Options levels on Webull", "Webull gives options permission by level. Buying calls/puts needs Level 2; **spreads need Level 3**. Apply in the app: Menu → Options → Upgrade."),
]


def _yf():
    import yfinance as yf
    return yf


def stats(t):
    yf = _yf()
    tk = yf.Ticker(t)
    h = tk.history(period="2y", auto_adjust=True)
    h.index = h.index.tz_localize(None)
    c = h["Close"].dropna()
    r = c.pct_change().dropna()
    info = {}
    try:
        info = tk.info or {}
    except Exception:
        pass
    out = {"price": float(c.iloc[-1]), "chg1d": float(r.iloc[-1] * 100), "avgmove": float(r.iloc[-60:].abs().mean() * 100),
           "hi52": float(c.iloc[-252:].max()), "lo52": float(c.iloc[-252:].min()), "ma200": float(c.rolling(200).mean().iloc[-1]),
           "summary": (info.get("longBusinessSummary") or "")[:420], "mcap": info.get("marketCap"), "beta": info.get("beta")}
    # earnings: typical next-day move, next date
    try:
        ed = tk.get_earnings_dates(limit=16)
        ed.index = ed.index.tz_localize(None)
        past = sorted(d for d in ed.index if d < dt.datetime.now())[-8:]
        moves = []
        for d in past:
            d0 = d.normalize() + (dt.timedelta(days=1) if d.hour >= 12 else dt.timedelta(0))
            j = c.index.searchsorted(d0)
            if 0 < j < len(c):
                moves.append(abs(c.iloc[j] / c.iloc[j - 1] - 1) * 100)
        out["earn_move"] = float(np.mean(moves)) if moves else None
        fut = sorted(d for d in ed.index if d >= dt.datetime.now())
        out["next_earn"] = str(fut[0].date()) if fut else None
    except Exception:
        out["earn_move"], out["next_earn"] = None, None
    return out, c


def chain_for(t, min_days=9, max_days=24):
    yf = _yf()
    tk = yf.Ticker(t)
    today = dt.date.today()
    exps = [e for e in tk.options if min_days <= (dt.date.fromisoformat(e) - today).days <= max_days]
    if not exps:
        exps = [e for e in tk.options if (dt.date.fromisoformat(e) - today).days >= min_days][:1]
    if not exps:
        return None, None
    e = exps[0]
    ch = tk.option_chain(e).calls
    ch = ch[(ch.bid > 0) & (ch.ask > 0)].copy()
    return e, ch


def spread_quote(ch, buy_k, sell_k):
    a = ch[ch.strike == buy_k].iloc[0]
    b = ch[ch.strike == sell_k].iloc[0]
    mid = (a.bid + a.ask) / 2 - (b.bid + b.ask) / 2
    nat = a.ask - b.bid
    return float(mid), float(nat)


def suggest_spread(t, price, avgmove):
    """Buy the call nearest the money, sell a call about 3 typical days higher; 9-24 days to expiration."""
    e, ch = chain_for(t)
    if ch is None or ch.empty:
        return None
    ks = sorted(ch.strike.unique())
    buy_k = min(ks, key=lambda k: abs(k - price))
    target = price * (1 + 3 * avgmove / 100)
    above = [k for k in ks if k > buy_k]
    if not above:
        return None
    sell_k = min(above, key=lambda k: abs(k - target))
    mid, nat = spread_quote(ch, buy_k, sell_k)
    width = sell_k - buy_k
    if mid <= 0 or mid >= width:
        return None
    return {"expiry": e, "buy_k": float(buy_k), "sell_k": float(sell_k), "debit": round(mid, 2), "natural": round(nat, 2),
            "width": float(width), "max_loss": round(mid * 100), "max_gain": round((width - mid) * 100)}


def requote(t, tr):
    yf = _yf()
    ch = yf.Ticker(t).option_chain(tr["expiry"]).calls
    ch = ch[(ch.bid > 0) & (ch.ask > 0)]
    try:
        a = ch[ch.strike == tr["buy_k"]].iloc[0]; b = ch[ch.strike == tr["sell_k"]].iloc[0]
        return float(a.bid - b.ask), float((a.bid + a.ask) / 2 - (b.bid + b.ask) / 2)   # what you'd get selling now (natural, mid)
    except IndexError:
        return None, None


# ---------------------------------------------------------------- learn card
def learn_card(t, n):
    name, group, drivers = MOVERS[t]
    s, c = stats(t)
    chart_day = n % 2 == 1                       # alternate: even days = options lesson, odd days = chart lesson on this stock's chart
    lesson = LESSONS[(n // 2) % len(LESSONS)]
    lines = [f"**{name}** · {group}", "", f"🏢 **What it does:** {s['summary'][:380]}{'…' if len(s['summary']) > 380 else ''}" if s["summary"] else "",
             f"⚡ **What moves it:** {drivers}", "",
             f"📈 **Price ${s['price']:,.2f}** · 1-year range ${s['lo52']:,.2f} – ${s['hi52']:,.2f}",
             f"• Typical day: moves **{s['avgmove']:.1f}%** (SPY moves ~0.7%)",
             f"• {'Above' if s['price'] > s['ma200'] else 'Below'} its 200-day average (${s['ma200']:,.2f}): " +
             ("long-term uptrend ✅" if s["price"] > s["ma200"] else "long-term downtrend ⚠️ (our dip setup skips it)")]
    if s.get("earn_move"):
        lines.append(f"• Typical earnings move: **±{s['earn_move']:.1f}%** in one day" + (f" · next earnings **{s['next_earn']}**" if s.get("next_earn") else ""))
    sp = None
    try:
        sp = suggest_spread(t, s["price"], s["avgmove"])
    except Exception:
        pass
    if sp:
        lines += ["", f"🎟️ **What its options cost right now** (expiring {sp['expiry']}):",
                  f"• A call spread (buy ${sp['buy_k']:g} / sell ${sp['sell_k']:g}) ≈ **${sp['max_loss']}** to open · could make up to **${sp['max_gain']}**"]
    p = None
    if chart_day:
        try:
            import scout_chartlessons
            ltitle, ltext, p = scout_chartlessons.lesson(t, n // 2)
            lines += ["", f"📊 **{ltitle}** (on {t}'s real chart below)", ltext] + scout_videos.chart_lines(n // 2)
        except Exception as e:
            print("chart lesson failed:", e)
            chart_day = False
    if not chart_day:
        lines += ["", f"📘 **Options lesson #{(n // 2) % len(LESSONS) + 1}: {lesson[0]}**", lesson[1]] + scout_videos.options_lines(n // 2)
    lines += ["", f"👉 **How to use this card (2 minutes):** read what moves {t}, look at the chart, then remember its **normal day "
              f"(±{s['avgmove']:.1f}%)**. When an alert says {t} moved 3× that, you'll know it's real news. Try `!chart {t} 1` in #lookup to practice."]
    card = {"color": 0x1F3A5F, "title": f"🎓 Stock of the Day #{n + 1} · {t}", "description": "\n".join(x for x in lines if x is not None)[:4000],
            "footer": {"text": f"One of your 33 movers · lessons alternate: options one day, chart reading the next · research only, not investment advice"}}
    if not p:
        try:
            import scout_charts
            p = scout_charts.make_chart(t, title=f"{t}  ${s['price']:,.2f}  ·  {name}", days=365)
        except Exception:
            p = None
    if p:
        card["_file"] = p
        card["image"] = {"url": "attachment://" + os.path.basename(p)}
    return card


def chart_lesson_card(t, k):
    import scout_chartlessons
    ltitle, ltext, p = scout_chartlessons.lesson(t, k)
    card = {"color": 0x1F3A5F, "title": f"📊 {ltitle} · {t}", "description": ("\n".join([ltext] + scout_videos.chart_lines(k)))[:4000],
            "footer": {"text": "Type !chart TICKER 1-7 for any lesson on any of your 33."}}
    card["_file"] = p
    card["image"] = {"url": "attachment://" + os.path.basename(p)}
    return card


# ---------------------------------------------------------------- big moves
def big_moves():
    yf = _yf()
    d = yf.download(ORDER, period="6mo", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    out = []
    for t in ORDER:
        try:
            c = d[t]["Close"].dropna()
        except KeyError:
            continue
        r = c.pct_change().dropna()
        avg = r.iloc[-61:-1].abs().mean() * 100
        today = r.iloc[-1] * 100
        if abs(today) >= max(2.5 * avg, 5):
            out.append((t, today, avg, float(c.iloc[-1])))
    return sorted(out, key=lambda x: -abs(x[1]))


def big_move_card(moves):
    lines = [f"{'🟩' if m > 0 else '🟥'} **{t}** {m:+.1f}% today (normal day ±{a:.1f}%) · ${p:,.2f} · {MOVERS[t][0]}" for t, m, a, p in moves]
    return {"color": 0x975A16, "title": f"⚡ Unusual moves today in your 33 ({len(moves)})",
            "description": "\n".join(lines) + "\n\n🤔 **Why it matters:** a move this big almost always means news (earnings, a deal, a scandal). "
                           "\n👉 **What to do:** don't chase it today. Check #movers for a 📰 news card on that stock, or type the ticker in #lookup to see why. "
                           "If it's one of our setups, a 📘 card will show up in #options-trades.",
            "footer": {"text": "Moves of 2.5× the stock's normal day (and at least 5%)."}}


# ---------------------------------------------------------------- practice trade alerts
def _rsi2(c):
    x = c.diff(); up = x.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); dn = (-x.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, 1e-9))


def load_book():
    try:
        return json.load(open(BOOK))
    except Exception:
        return {"open": {}, "closed": []}


def save_book(b):
    json.dump(b, open(BOOK, "w"), indent=1)


def scan_trades(max_new=3):
    """Run near the close. Returns (new entry cards data, exit data). Uses live prices as today's close."""
    import pandas as pd
    if dt.date.today().weekday() >= 5:
        return [], []   # market closed: no new practice trades or exits on weekends
    yf = _yf()
    b = load_book()
    d = yf.download(ORDER, period="2y", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    today = str(dt.date.today())
    entries, exits = [], []
    for t in ORDER:
        try:
            c = d[t]["Close"].dropna()
            c.index = c.index.tz_localize(None) if c.index.tz is not None else c.index
            last = yf.Ticker(t).fast_info["last_price"]
            if last and c.index[-1].date() < dt.date.today():
                c.loc[pd.Timestamp(dt.date.today())] = float(last)
        except Exception:
            continue
        p, ma5, ma200, r = float(c.iloc[-1]), c.rolling(5).mean().iloc[-1], c.rolling(200).mean().iloc[-1], _rsi2(c).iloc[-1]
        avg = c.pct_change().iloc[-61:-1].abs().mean() * 100
        if t in b["open"]:
            tr = b["open"][t]
            days = int(np.busday_count(tr["date"], today))
            nat, mid = requote(t, tr)
            exp_days = (dt.date.fromisoformat(tr["expiry"]) - dt.date.today()).days
            gain = None if mid is None else (mid - tr["debit"])
            reason = None
            if p > ma5:
                reason = "stock bounced above its 5-day average (the setup's exit)"
            elif gain is not None and gain >= 0.5 * (tr["width"] - tr["debit"]):
                reason = "hit +50% of the spread's max gain"
            elif mid is not None and mid <= 0.5 * tr["debit"]:
                reason = "spread lost half its value (stop)"
            elif days >= 10 or exp_days <= 2:
                reason = "time limit"
            if reason:
                fill = nat if nat is not None else mid
                tr.update({"closed": today, "exit_mid": mid, "exit_natural": nat, "reason": reason, "stock_exit": p,
                           "pnl": None if fill is None else round((fill - tr["debit"]) * 100)})
                b["closed"].append(dict(tr, t=t)); del b["open"][t]
                exits.append(dict(tr, t=t))
        elif len(entries) < max_new and p > ma200 and r < 10:
            sp = suggest_spread(t, p, avg)
            if sp and sp["max_loss"] <= 600:
                tr = dict(sp, date=today, stock=p, rsi2=float(r), avgmove=float(avg))
                b["open"][t] = tr
                entries.append(dict(tr, t=t))
    save_book(b)
    return entries, exits


def record():
    b = load_book()
    cl = [x for x in b["closed"] if x.get("pnl") is not None]
    if not cl:
        return "📒 Practice record: no closed trades yet."
    w = sum(1 for x in cl if x["pnl"] > 0)
    return f"📒 Practice record: **{len(cl)} trades · {w} winners ({w / len(cl) * 100:.0f}%) · total {sum(x['pnl'] for x in cl):+,} $** (1 spread each, real quotes)"


def entry_card(e):
    name = MOVERS[e["t"]][0]
    return {"color": 0x4A5568, "title": f"📘 PRACTICE TRADE · BUY CALL SPREAD · {e['t']} · ${e['stock']:,.2f}",
            "description": "\n".join([
                f"**{name}** is in an uptrend but just had a sharp 2-day drop (RSI-2 = **{e['rsi2']:.0f}**; buy zone is under 10).",
                "On these 33 stocks this setup won **68%** of the time (2013–now), averaging **+0.5% to +1%** on the stock over ~4 days.", "",
                "🧾 **What you'd enter on Webull** (Options → pick the expiration → Call Spread / 'Vertical'):",
                f"• **Expiration:** {e['expiry']}",
                f"• **BUY** the **${e['buy_k']:g} call** · **SELL** the **${e['sell_k']:g} call**",
                f"• **Order type:** LIMIT · **Price:** **${e['debit']:.2f}** debit (the middle; the quick-fill price is ${e['natural']:.2f})",
                "• **Quantity:** 1 · **Time-in-force:** Day",
                f"• 💵 Costs **${e['max_loss']}** · most you can lose **${e['max_loss']}** · most you can make **${e['max_gain']}**", "",
                f"🤔 **How this trade makes or loses money** (if held to {e['expiry']}):",
                f"• {e['t']} **at or above ${e['sell_k']:g}** → the spread is worth ${e['width'] * 100:.0f} → you **make ${e['max_gain']}**",
                f"• {e['t']} **below ${e['buy_k']:g}** → the spread is worth $0 → you **lose the ${e['max_loss']}** you paid (never more)",
                f"• **Break-even:** {e['t']} at **${e['buy_k'] + e['debit']:.2f}** ({(e['buy_k'] + e['debit']) / e['stock'] * 100 - 100:+.1f}% from now). "
                "In between, you make or lose part of it.",
                "• We usually sell before expiration, as soon as the bounce happens, so you rarely wait until the last day.", "",
                "🚪 **When to sell** (I'll post a card): the stock closes above its 5-day average, OR the spread is up +50% of its max gain, "
                "OR it's lost half its value, OR 10 trading days / 2 days before expiration.", "",
                "⚠️ **PRACTICE ONLY:** the option version hasn't been tested on past prices yet. I'm recording the real quoted prices so we can see if it "
                "makes money before you use cash. Spreads need Webull options **Level 3**.",
                record()]),
            "footer": {"text": "Research only, not investment advice."}}


def exit_card(x):
    good = (x.get("pnl") or 0) > 0
    return {"color": 0x2F6F4E if good else 0x9B2C2C,
            "title": f"📘 PRACTICE · CLOSE {x['t']} SPREAD · {'+' if good else ''}{x.get('pnl', 0)} $ {'✅' if good else '❌'}",
            "description": "\n".join([
                f"🤔 **What happened:** {x['reason']}. That's the plan's signal to take the result and move on, win or lose, "
                "instead of hoping.",
                f"👉 **What to do:** close the spread today (both legs together, one order).",
                f"🧾 To close on Webull: open the position → **Close** → LIMIT at about **${(x.get('exit_mid') or 0):.2f}** credit · Day.",
                f"Opened {x['date']} at ${x['debit']:.2f} debit (stock ${x['stock']:,.2f}) → now about ${(x.get('exit_mid') or 0):.2f} mid / "
                f"${(x.get('exit_natural') or 0):.2f} quick-fill (stock ${x['stock_exit']:,.2f}).",
                f"Result on 1 spread (quick-fill price): **{x.get('pnl', 0):+} $**", "", record()]),
            "footer": {"text": "Practice only. Research, not investment advice."}}


def options_basics_card():
    return {"color": 0x1F3A5F, "title": "📘 Options basics (the 14 lessons)",
            "description": "\n\n".join(f"**{i + 1}. {a}**\n{b}" for i, (a, b) in enumerate(LESSONS))[:4000],
            "footer": {"text": "Type !videos for a video for every lesson. One lesson also appears on each Stock of the Day card."}}


def videos_card():
    import scout_chartlessons
    return {"color": 0x1F3A5F, "title": "🎥 Video library: one video topic for every lesson",
            "description": ("👉 **How to use this:** watch the video for the lesson on today's card (5-15 min), then look at that card again. "
                            "Seeing it explained, then seeing it on a real stock, is how it sticks.\n\n"
                            + scout_videos.library_text([a for a, _ in LESSONS], scout_chartlessons.TITLES))[:4000],
            "footer": {"text": "YouTube links open a search with many videos, so pick one that's 5-15 minutes. Type !videos anytime."}}
