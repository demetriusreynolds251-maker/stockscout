"""Connect the dots between stocks.
1. LINKS: who sells to / buys from / competes with whom, and THEMES: shared risks (China export rules, Bitcoin, data-center buildout...).
2. When a SERIOUS story hits one stock -> a 'ripple check' card: which connected stocks are exposed, why, and how they're moving.
3. HOT NAMES: people/companies named in serious stories (e.g. 'Alice Huang', 'Megaspeed') are remembered; any later headline naming them
   on ANY stock is flagged as connected, and the bot searches the news for those names every hour."""
import datetime as dt
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
HOT = os.path.join(HERE, "data", "movers", "hot_names.json")

THEMES = {
    "China export rules / smuggling": ("NVDA AMD SMCI DELL TSM AMAT LRCX INTC MU ARM QCOM AVGO MRVL".split(),
                                       re.compile(r"china|chinese|export|smuggl|divert|beijing|huawei|sanction|taiwan", re.I)),
    "Bitcoin / crypto prices": ("MSTR MARA RIOT COIN HOOD".split(), re.compile(r"bitcoin|crypto|btc|ether|stablecoin|sec .*crypto", re.I)),
    "AI data-center buildout": ("NVDA AVGO MRVL AMD VRT DELL SMCI ORCL MU AMAT LRCX TSM".split(),
                                re.compile(r"data cent|datacenter|moratorium|power grid|hyperscal|capex|ai spending|openai", re.I)),
    "Interest rates / consumer credit": ("SOFI NU HOOD CVNA".split(), re.compile(r"fed\b|interest rate|rate cut|rate hike|loan|credit|delinquen", re.I)),
    "Space launches": ("RKLB ASTS".split(), re.compile(r"launch|rocket|satellite|spacex|faa", re.I)),
    "Short-seller attack": ("APP SMCI CVNA PLTR MSTR IONQ".split(), re.compile(r"short seller|short report|hindenburg|muddy waters|citron|fraud alleg", re.I)),
    "Cyberattacks / security": ("CRWD PANW".split(), re.compile(r"hack|breach|cyber|ransomware|outage|vulnerab|security incident", re.I)),
    "Company software spending": ("SNOW PLTR CRWD PANW ORCL APP".split(), re.compile(r"software spend|it budget|enterprise spend|cloud spend|seat|subscription|saas", re.I)),
    "Government contracts / defense": ("PLTR RKLB ASTS IONQ".split(), re.compile(r"pentagon|defense|army|navy|air force|government contract|doge|dod\b|nasa", re.I)),
    "Quantum computing": ("IONQ".split(), re.compile(r"quantum", re.I)),
    "Elon Musk / EVs / robotaxi": ("TSLA".split(), re.compile(r"musk|electric vehicle|\bev\b|robotaxi|self-driving|autopilot|ev tax credit", re.I)),
    "Streaming / consumer spending": ("NFLX".split(), re.compile(r"streaming|subscriber|consumer spend|box office|ad tier", re.I)),
    "Retail-trader frenzy": ("HOOD COIN MSTR PLTR IONQ RKLB ASTS SOFI CVNA".split(), re.compile(r"retail trader|meme|wallstreetbets|reddit|short squeeze", re.I)),
    "Elections / politics / tariffs": ("NVDA AMD TSM INTC VRT TSLA PLTR AMAT LRCX".split(), re.compile(r"tariff|election|governor|congress|white house|executive order|\bban(s|ned)?\b", re.I)),
}
LINKS = {
    "NVDA": [("SMCI", "builds servers full of Nvidia chips; its co-founder was charged in March with smuggling them to China"),
             ("DELL", "sells Nvidia-based AI servers"), ("TSM", "manufactures Nvidia's chips"), ("MU", "makes the memory inside Nvidia AI chips"),
             ("AMD", "main rival: money often moves here when Nvidia stumbles"), ("AVGO", "rival AI chips: money rotates here too"),
             ("VRT", "powers/cools Nvidia AI racks"), ("ORCL", "one of Nvidia's biggest buyers (AI cloud)"), ("ARM", "Nvidia uses Arm designs")],
    "SMCI": [("NVDA", "Super Micro's main chip supplier; shared China-export scrutiny"), ("DELL", "direct rival in AI servers")],
    "DELL": [("SMCI", "rival AI-server maker"), ("NVDA", "chip supplier")],
    "TSM": [("NVDA", "biggest AI customer"), ("AMD", "customer"), ("AMAT", "equipment supplier"), ("LRCX", "equipment supplier")],
    "AMD": [("NVDA", "main rival"), ("TSM", "makes AMD's chips")],
    "ORCL": [("NVDA", "buys huge amounts of Nvidia chips"), ("VRT", "data-center supplier")],
    "MSTR": [("COIN", "both move with Bitcoin"), ("MARA", "Bitcoin miner"), ("RIOT", "Bitcoin miner")],
    "COIN": [("HOOD", "rival crypto/trading app"), ("MSTR", "Bitcoin proxy")],
    "HOOD": [("COIN", "rival"), ("SOFI", "rival fintech app")],
    "MARA": [("RIOT", "rival miner"), ("MSTR", "Bitcoin proxy")],
    "RIOT": [("MARA", "rival miner"), ("MSTR", "Bitcoin proxy")],
    "VRT": [("NVDA", "AI racks it powers/cools"), ("ORCL", "data-center customer")],
    "AMAT": [("LRCX", "rival chip-equipment maker, same China rules"), ("TSM", "customer")],
    "LRCX": [("AMAT", "rival, same China rules"), ("MU", "big customer")],
    "MU": [("NVDA", "memory buyer"), ("LRCX", "buys its chip-making machines"), ("AMAT", "equipment supplier")],
    "AVGO": [("NVDA", "rival in AI chips"), ("MRVL", "rival in custom AI chips"), ("TSM", "makes its chips")],
    "MRVL": [("AVGO", "rival in custom AI chips"), ("NVDA", "AI networking partner/rival"), ("TSM", "makes its chips")],
    "ARM": [("NVDA", "Nvidia builds on Arm designs"), ("QCOM", "uses Arm designs; legal fights between them"), ("AMD", "rival chip designs")],
    "QCOM": [("ARM", "uses Arm designs; past lawsuits"), ("TSM", "makes its chips"), ("INTC", "rival in PC chips")],
    "INTC": [("AMD", "main rival in PC/server chips"), ("TSM", "rival chip factory"), ("NVDA", "Nvidia invested in Intel")],
    "PLTR": [("ORCL", "partners on government/cloud AI"), ("SNOW", "company data/AI software peer"), ("CRWD", "software peer, same buyers")],
    "CRWD": [("PANW", "main cybersecurity rival"), ("SNOW", "software peer")],
    "PANW": [("CRWD", "main cybersecurity rival")],
    "SNOW": [("ORCL", "rival in company data"), ("PLTR", "data/AI software peer"), ("CRWD", "software peer")],
    "APP": [("NFLX", "ad-supported apps peer"), ("PLTR", "AI software favorite with retail traders")],
    "NFLX": [("APP", "advertising peer")],
    "SOFI": [("HOOD", "rival fintech app"), ("NU", "digital-bank peer"), ("CVNA", "consumer-loan exposure")],
    "NU": [("SOFI", "digital-bank peer"), ("HOOD", "fintech peer")],
    "CVNA": [("SOFI", "consumer-loan exposure"), ("TSLA", "car market")],
    "RKLB": [("ASTS", "space peer"), ("PLTR", "defense-contract peer")],
    "ASTS": [("RKLB", "space peer")],
    "IONQ": [("PLTR", "hype/government-tech peer"), ("RKLB", "speculative-tech peer")],
    "TSLA": [("NVDA", "buys Nvidia chips for self-driving AI"), ("CVNA", "car market")],
}
STOP = set("""The A An And Or Of In On At To For With From After Before Over Under Amid As By Is Are Was Were Be Says Said New Report Reports Exclusive
US U.S. DOJ SEC FBI CEO CFO AI Inc Corp Co Ltd Group Holdings Stock Stocks Shares Market Markets Wall Street Why How What Who This That
Nvidia Super Micro Supermicro Microsoft Apple Amazon Google Meta Tesla Intel Oracle China Chinese Taiwan Washington Trump Justice Department Times India
Probe Probes Charges Charged Alleged Chips Chip Servers Server
Resigns Resign Resigned Steps Step Down Quits Quit Ousted Fired Leaves Exits Named Appointed Takes Over Sues Sued Rises Falls Jumps Drops
Surges Plunges Slides Soars Tumbles Nov Oct Dec Jan Feb Mar Apr May Jun Jul Aug Sep""".split())


def _names(title):
    """Pull 'Firstname Lastname' or distinctive capitalized names out of a headline."""
    out = set()
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", title):
        words = m.group(1).split()
        if not all(w in STOP for w in words) and not any(w in ("The", "A") for w in words[:1]):
            words = [w for w in words if w not in STOP]
            if len(words) >= 1 and len(" ".join(words)) >= 6:
                out.add(" ".join(words))
    for m in re.finditer(r"\b([A-Z][a-z]+[A-Z][a-z]+|[A-Z]{2,}[a-z]+)\b", title):   # CamelCase company names like MegaSpeed
        if m.group(1) not in STOP:
            out.add(m.group(1))
    return out


def seed(ticker, name, headline):
    hot = load_hot()
    hot.setdefault(name, {"from": ticker, "first_seen": str(dt.date.today()), "headline": headline})
    json.dump(hot, open(HOT, "w"), indent=1)


def load_hot():
    try:
        return json.load(open(HOT))
    except Exception:
        return {}


def remember(ticker, title):
    """Store names from a serious headline. Returns the new names."""
    hot = load_hot()
    new = []
    for n in _names(title):
        if n not in hot:
            hot[n] = {"from": ticker, "first_seen": str(dt.date.today()), "headline": title[:200]}
            new.append(n)
    # forget names older than 60 days
    cut = str(dt.date.today() - dt.timedelta(days=60))
    hot = {k: v for k, v in hot.items() if v["first_seen"] >= cut}
    json.dump(hot, open(HOT, "w"), indent=1)
    return new


def connected_names(ticker, title):
    """Hot names (from OTHER stocks' stories) that appear in this headline."""
    hot = load_hot()
    return [(n, v) for n, v in hot.items() if v["from"] != ticker and n.lower() in title.lower()]


def themes_in(title):
    return [name for name, (_, rx) in THEMES.items() if rx.search(title)]


def ripple(ticker, title, movers):
    """Which other stocks are exposed to this story, and why. Returns list of (ticker, why)."""
    out, seen = [], {ticker}
    for t, why in LINKS.get(ticker, []):
        if t in movers and t not in seen:
            out.append((t, why)); seen.add(t)
    for th in themes_in(title):
        for t in THEMES[th][0]:
            if t in movers and t not in seen:
                out.append((t, f"shares the '{th}' risk")); seen.add(t)
    return out


def moves_today(tickers):
    import yfinance as yf
    if not tickers:
        return {}
    d = yf.download(tickers, period="3mo", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            c = d[t]["Close"].dropna() if len(tickers) > 1 else d["Close"].dropna()
            r = c.pct_change().dropna()
            out[t] = (float(r.iloc[-1] * 100), float(r.iloc[-61:-1].abs().mean() * 100), float((c.iloc[-1] / c.iloc[-6] - 1) * 100))
        except Exception:
            pass
    return out


def ripple_card(ticker, title, movers, names_linked=None, when=None):
    """Plain-English card: what happened, why it matters, what to do, then only the few stocks that matter."""
    exposed = ripple(ticker, title, movers)
    if not exposed and not names_linked:
        return None
    mv = moves_today([ticker] + [t for t, _ in exposed[:12]])
    why = dict(exposed)
    hurt, helped, calm = [], [], []
    for t, _ in exposed[:12]:
        m = mv.get(t)
        if not m:
            continue
        today, normal, five = m
        if today <= -1.5 * normal or (five <= -8 and today < 0):
            hurt.append(t)
        elif today >= 1.5 * normal:          # only stocks reacting TODAY count as catching the money
            helped.append(t)
        else:
            calm.append(t)
    src = mv.get(ticker)
    th = themes_in(title)
    # 1. what happened
    lines = [f"📌 **What happened:** {title[:200]}"]
    if when:
        lines.append(f"📅 **News date:** {when}")
    if names_linked:
        n, v = names_linked[0]
        lines.append(f"🧩 It's tied to the earlier **{v['from']}** story: the same person/company (**{n}**) is in both.")
    if src:
        lines.append(f"📉 **{ticker}** today: **{src[0]:+.1f}%** (a normal day is about ±{src[1]:.1f}%)")
    # 2. why it matters
    lines += ["", "🤔 **Why it matters:** bad news rarely stays with one company. It spreads to the companies that work with it, "
                  + (f"and to others with the same risk (**{th[0].lower()}**). " if th else "")
                  + "Partners usually get dragged down; rivals sometimes catch the money."]
    # 3. what to do
    lines += ["", "👉 **What to do:**"]
    avoid = [ticker] + [t for t in hurt if t != ticker]
    lines.append(f"• ⛔ **Don't open new call trades on {', '.join(avoid[:4])}** for now. Stocks under a cloud keep swinging on every headline. "
                 "(If you already have a practice trade on one, the bot will tell you when to close it.)")
    if helped:
        lines.append(f"• 👀 **Money is moving into {', '.join(helped[:3])}.** Don't chase a stock that already jumped; "
                     "if it dips while still in an uptrend, a 📘 trade card will show up in #options-trades.")
    if not hurt and not helped:
        lines.append("• ✅ The connected stocks aren't reacting much yet. Nothing to do; this is a heads-up in case the story grows.")
    lines.append("• No trade is needed from this card. It's a warning, not a buy or sell signal.")
    # 4. only the stocks that matter
    if hurt or helped:
        lines += ["", "**The connected stocks that are moving:**"]
        for t in hurt[:4]:
            m = mv[t]; lines.append(f"📉 **{t}** {m[0]:+.1f}% today, {m[2]:+.1f}% this week · {why[t]}")
        for t in helped[:4]:
            m = mv[t]; lines.append(f"📈 **{t}** {m[0]:+.1f}% today, {m[2]:+.1f}% this week · {why[t]}")
    if calm:
        lines.append(f"\n😐 Not reacting (yet): {', '.join(calm[:8])}")
    return {"color": 0x6B46C1, "title": f"🔗 Ripple warning · {ticker} news could spread", "description": "\n".join(lines)[:4000],
            "footer": {"text": "Research only, not investment advice."}}


NAME_RX = {
    "MSTR": r"MicroStrategy|Strategy Inc|\bMSTR\b|Michael Saylor", "MARA": r"MARA Holdings|Marathon Digital", "RIOT": r"Riot Platforms|Riot Blockchain",
    "COIN": r"Coinbase", "NVDA": r"Nvidia", "AMD": r"\bAMD\b|Advanced Micro", "AVGO": r"Broadcom", "MRVL": r"Marvell", "ARM": r"\bArm Holdings|\bArm's\b",
    "MU": r"Micron", "QCOM": r"Qualcomm", "INTC": r"\bIntel\b", "TSM": r"\bTSMC\b|Taiwan Semiconductor", "SMCI": r"Super ?Micro|Supermicro",
    "DELL": r"\bDell\b", "VRT": r"Vertiv", "AMAT": r"Applied Materials", "LRCX": r"Lam Research", "PLTR": r"Palantir", "ORCL": r"Oracle",
    "CRWD": r"CrowdStrike", "PANW": r"Palo Alto Networks", "SNOW": r"Snowflake", "APP": r"AppLovin", "NFLX": r"Netflix", "HOOD": r"Robinhood",
    "SOFI": r"\bSoFi\b", "NU": r"Nubank|Nu Holdings", "CVNA": r"Carvana", "RKLB": r"Rocket Lab", "ASTS": r"AST SpaceMobile", "IONQ": r"IonQ",
    "TSLA": r"Tesla|Elon Musk"}


def hot_name_search(movers_names=None):
    """Search the news for each hot name; return (ticker, title, link, name, info) for headlines that name one of the 33 companies."""
    import scout_data
    hot = load_hot()
    hits = []
    for n, v in list(hot.items())[:12]:
        try:
            items = scout_data._google_news(n, "", 10, query=f'"{n}"')
        except Exception:
            continue
        cut = str(dt.date.today() - dt.timedelta(days=3))
        for it in items:
            title = it.get("title", "")
            if it.get("date") and it["date"] < cut:
                continue                      # old news, not a new connection
            for t, rx in NAME_RX.items():
                # skip if the original story already named this company: that's the same story, not a new link
                if t != v["from"] and re.search(rx, title, re.I) and not re.search(rx, v.get("headline", ""), re.I):
                    hits.append((t, title, it.get("link", ""), n, v, it.get("date", "")))
    return hits
