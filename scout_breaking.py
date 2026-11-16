"""Breaking news + "money is moving" watcher.

Two detectors, checked every few minutes:
1. NEWS: market-moving event types (air travel shutdowns, cyberattacks, big tech outages, war, chip bans, bank runs,
   crypto shocks, Fed surprises). An event fires when 4+ different news outlets report it within the last 90 minutes
   (or, for air travel, when the FAA's own live status feed shows a wide ground stop).
2. MONEY: during market hours, sector funds and your 33 that suddenly move 3x their normal day.

Every card says: what happened, what officials say vs what is still unproven (skeptic check), which stocks it can hit
and why, what happened last time, and what to do."""
import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "breaking")
STATE = os.path.join(DATA, "state.json")
CT = ZoneInfo("America/Chicago")
COOLDOWN_H = 24        # one card per event type per day (follow-up stories don't re-trigger it)
MIN_OUTLETS = 4        # different outlets reporting it...
WINDOW_MIN = 90        # ...within this many minutes

# (ticker, direction, why)
AIR = [("DAL", "⬇️", "Delta: every grounded flight is lost money, refunds, crews stuck in the wrong cities"),
       ("UAL", "⬇️", "United: same"), ("AAL", "⬇️", "American: same, and it carries the most debt"),
       ("LUV", "⬇️", "Southwest: same"), ("FDX", "⬇️", "FedEx: packages fly at night; a long stop delays deliveries"),
       ("UPS", "⬇️", "UPS: same as FedEx"), ("BKNG", "⬇️", "Booking: fewer trips, more cancellations"),
       ("HTZ", "⬆️", "Hertz: stranded travelers rent cars and drive"),
       ("RTX", "⬆️", "RTX (Raytheon): builds air traffic control gear; outages push Washington to spend on upgrades"),
       ("LHX", "↕️", "L3Harris: RUNS the FAA's communication network. Up if Washington spends on upgrades; DOWN if its own network caused the outage")]

EVENTS = [
    {"key": "air", "name": "✈️ Air travel shutdown",
     "query": '("ground stop" OR "air traffic control" outage OR "flights grounded") when:1h',
     "rx": r"ground stop|air traffic control|flights? (are )?grounded|FAA.{0,40}(outage|halt)",
     "stocks": AIR,
     "past": "Jan 2023: an FAA computer outage (a damaged file) stopped departures nationwide for about 1.5 hours and delayed 10,000+ flights. "
             "Airlines fell about 1–2.5% the next morning, then recovered. At first nobody knew the cause; it was confirmed accidental days later.",
     "watch": "How LONG it lasts (under 2 hours = small dip; overnight = bigger), and whether the cause turns out to be an attack. "
              "Also check the weather: storms cause delays too, so not every delay number on TV is from the outage.",
     "yours": "None of your 33 are airlines. If it turns out to be a cyberattack, watch CRWD and PANW."},
    {"key": "cyber", "name": "🛡️ Cyberattack",
     "query": '(cyberattack OR "cyber attack" OR ransomware OR hackers) (government OR infrastructure OR outage OR breach) when:1h',
     "rx": r"cyber ?attack|ransomware|hack(ed|ers|ing)\b|breach|state-sponsored|nation-state",
     "stocks": [("CRWD", "⬆️", "CrowdStrike (in your 33): companies spend more on security after big hacks"),
                ("PANW", "⬆️", "Palo Alto (in your 33): same"), ("FTNT", "⬆️", "Fortinet: same"),
                ("ZS", "⬆️", "Zscaler: same"), ("SPY", "⬇️", "Whole market: if it hits banks, power or airports, fear spreads")],
     "past": "Dec 2020 SolarWinds hack of U.S. agencies: cybersecurity stocks rallied for weeks. "
             "But July 2024: CrowdStrike's OWN bad update crashed computers worldwide and CRWD fell hard. A security company can be the victim too.",
     "watch": "Whether it's CONFIRMED (FBI, CISA or the company says 'attack') and who the victim is. If a security company caused it, its stock falls.",
     "yours": "CRWD and PANW are in your 33. Don't buy the first jump; the bot only buys dips in uptrends."},
    {"key": "outage", "name": "💻 Big tech outage",
     "query": '(Microsoft OR AWS OR Azure OR "Google Cloud" OR Cloudflare OR Outlook OR Workday OR Salesforce OR Oracle OR Okta OR Verizon OR AT&T OR "T-Mobile") outage when:1h',
     "rx": r"(microsoft|azure|aws|amazon web services|google cloud|cloudflare|outlook|teams|icloud|workday|salesforce|oracle|okta|verizon|at&t|t-mobile).{0,50}(outage|down\b|disrupt|unavailable)|outage.{0,40}(microsoft|aws|azure|google|cloudflare|workday|salesforce|oracle|okta|verizon|at&t|t-mobile)",
     "stocks": [("MSFT", "⬇️", "Microsoft: small dip unless it keeps happening"), ("AMZN", "⬇️", "Amazon (AWS): same"),
                ("GOOGL", "⬇️", "Google Cloud: same"), ("NET", "⬇️", "Cloudflare: same"), ("WDAY", "⬇️", "Workday: runs payroll/HR for big employers; trust takes a hit"),
                ("CRWD", "⬆️", "CrowdStrike (in your 33): only if it turns out to be a hack"), ("PANW", "⬆️", "Palo Alto (in your 33): same")],
     "past": "Most big outages are mistakes (bad updates, config errors) and cost the company a small, short dip. "
             "Repeated outages or a confirmed hack hurt more.",
     "watch": "Whether the company says 'no sign of attack' and whether it happens AGAIN.",
     "yours": "Only CRWD/PANW matter for you, and only if a hack is confirmed."},
    {"key": "war", "name": "💥 War / military strike",
     "query": '("missile strike" OR airstrike OR "invasion of" OR "military strike" OR "declares war" OR "Strait of Hormuz") when:1h',
     "rx": r"missile (strike|attack|launch)|air ?strikes? (on|against|hit)|invasion of|invades|declares war|military strike|strait of hormuz|naval blockade|attacks? on u\.?s\.",
     "stocks": [("XOM", "⬆️", "Exxon: oil jumps when supply is at risk"), ("CVX", "⬆️", "Chevron: same"),
                ("LMT", "⬆️", "Lockheed: more defense spending"), ("NOC", "⬆️", "Northrop: same"),
                ("PLTR", "⬆️", "Palantir (in your 33): defense software"),
                ("DAL", "⬇️", "Airlines: jet fuel costs more"), ("SPY", "⬇️", "Whole market: fear selling")],
     "past": "Big conflicts usually drop the market for days, rarely weeks (Russia invading Ukraine, Feb 2022: oil spiked, stocks dipped, then bounced within weeks). "
             "Oil and defense move first.",
     "watch": "Whether oil supply is actually hit (shipping lanes, oil fields) and whether the U.S. gets involved.",
     "yours": "PLTR may jump; don't chase. Your other 33 may dip with the market."},
    {"key": "chips", "name": "🇨🇳 Chip ban / China trade",
     "query": '("export controls" OR "export ban" OR "chip ban" OR tariffs) (China OR chips OR semiconductor) when:1h',
     "rx": r"(impose|announce|new|tighten|expand|order|unveil)\w*\b.{0,40}export (control|ban|curb|restriction)|chip (ban|curb)|entity list|(impose|announce|new|raise)\w*\b.{0,30}tariffs?",
     "stocks": [("NVDA", "⬇️", "Nvidia (in your 33): sells lots of chips to China"), ("AMD", "⬇️", "AMD (in your 33): same"),
                ("AVGO", "⬇️", "Broadcom (in your 33)"), ("MU", "⬇️", "Micron (in your 33)"),
                ("AMAT", "⬇️", "Applied Materials (in your 33): sells chip-making machines to China"),
                ("LRCX", "⬇️", "Lam Research (in your 33): same"), ("TSM", "⬇️", "TSMC (in your 33): Taiwan risk")],
     "past": "Oct 2022 chip export rules: chip stocks fell for weeks. Tariff headlines in 2025 swung the whole market 5–10% in days, both ways.",
     "watch": "Whether it's a real rule (official notice) or just a threat/rumor, and whether it gets delayed.",
     "yours": "Up to 7 of your 33 are chip stocks. Don't open new call trades on them until the headline settles."},
    {"key": "bank", "name": "🏦 Bank trouble",
     "query": '("bank run" OR "bank failure" OR FDIC OR "seized by regulators") when:1h',
     "rx": r"bank run|bank (failure|collapse|fails)|fdic|seized by regulators|deposit (flight|outflow)",
     "stocks": [("KRE", "⬇️", "Regional banks fund: falls first"), ("SOFI", "⬇️", "SoFi (in your 33): a bank, gets lumped in"),
                ("HOOD", "⬇️", "Robinhood (in your 33): customers pull money when scared"),
                ("MSTR", "⬆️", "Strategy (in your 33): bitcoin often rises on bank fear"), ("COIN", "⬆️", "Coinbase (in your 33): same")],
     "past": "Mar 2023 Silicon Valley Bank collapse: regional banks fell 25%+ in weeks; bitcoin rose about 40% that month.",
     "watch": "Whether customers are pulling deposits from more than one bank, and what the FDIC/Fed does.",
     "yours": "SOFI and HOOD can drop hard; MSTR/COIN may rise."},
    {"key": "crypto", "name": "🪙 Crypto shock",
     "query": '(bitcoin crash OR bitcoin plunges OR bitcoin soars OR "crypto exchange" hack OR depeg) when:1h',
     "rx": r"bitcoin.{0,20}(crash|plunge|tumble|soar|surge|record)|crypto exchange.{0,30}(hack|collapse|halt)|depeg",
     "stocks": [("MSTR", "↕️", "Strategy (in your 33): moves about 2× bitcoin"), ("MARA", "↕️", "MARA (in your 33): miners move 2–3× bitcoin"),
                ("RIOT", "↕️", "Riot (in your 33): same"), ("COIN", "↕️", "Coinbase (in your 33): trading fees rise and fall with it"),
                ("HOOD", "↕️", "Robinhood (in your 33): crypto trading is a big chunk of its money")],
     "past": "Nov 2022 FTX exchange collapse: bitcoin fell about 25% in a week; COIN and miners fell much more.",
     "watch": "Whether an exchange or stablecoin is in trouble (bad, spreads) or it's just a price swing (usually bounces).",
     "yours": "Five of your 33 move with bitcoin. Expect them all to move together, in the same direction, bigger than bitcoin."},
    {"key": "fed", "name": "🏛️ Fed surprise",
     "query": '("emergency rate" OR "Fed emergency" OR "surprise rate" OR "Powell" fired) when:1h',
     "rx": r"emergency (rate|meeting|cut)|surprise (rate|cut|hike)|fed chair.{0,30}(fired|resign|ousted)|powell.{0,30}(fired|resign|ousted)",
     "stocks": [("SPY", "↕️", "Whole market"), ("QQQ", "↕️", "Tech: moves bigger than the market"),
                ("CVNA", "↕️", "Carvana (in your 33): very sensitive to interest rates"), ("SOFI", "↕️", "SoFi (in your 33): a lender"),
                ("APP", "↕️", "AppLovin (in your 33): high-growth, big swings")],
     "past": "Emergency cut in March 2020 (COVID): the market still fell, because it signaled fear. Surprises usually mean big swings both ways for days.",
     "watch": "WHY the Fed acted: an emergency cut is a warning sign, not just good news.",
     "yours": "Expect bigger swings across your 33. Smaller trades, or none, until it calms down."},
]

# follow-up / aftermath stories don't count as "breaking"
AFTER_RX = r"\b(restored|mostly fixed|is fixed|resolved|back (up|online)|after (a |the )?[\w-]+[- ]hour outage|what caused|what to know about|lessons|weigh in|how the company|the spin|recap|explained)\b"
OFFICIAL_RX = r"no (indication|evidence|sign)|not (a |caused by )?(cyber|attack|hack)|unintentional|technical (issue|glitch|problem)|equipment|glitch|telecommunications"
UNPROVEN_RX = r"\b(possible|possibly|suspected|may have|could be|reportedly|rumou?r|unconfirmed|claims?)\b"

# money-move watch: sector funds (label, why it matters)
SECTORS = {"JETS": "airlines", "CIBR": "cybersecurity", "XLE": "oil & gas", "ITA": "defense", "SMH": "chip stocks",
           "KRE": "regional banks", "IBIT": "bitcoin", "SPY": "the whole market", "QQQ": "big tech"}


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save(s):
    os.makedirs(DATA, exist_ok=True)
    json.dump(s, open(STATE, "w"), indent=1)


def market_open(now=None):
    now = now or dt.datetime.now(CT)
    return now.weekday() < 5 and dt.time(8, 30) <= now.time() <= dt.time(15, 0)


def faa_ground_stops():
    """Airports under a ground stop right now, from the FAA's live status feed."""
    import requests
    import xml.etree.ElementTree as ET
    try:
        r = requests.get("https://nasstatus.faa.gov/api/airport-status-information", timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
    except Exception:
        return None
    out = []
    for d in root.iter("Delay_type"):
        if "ground stop" in (d.findtext("Name") or "").lower():
            for p in d.iter("Program"):
                out.append((p.findtext("ARPT") or "?", p.findtext("Reason") or ""))
    return out


def moves(tickers):
    """{ticker: (today %, normal day %)} using daily bars (today's bar is live during market hours)."""
    import yfinance as yf
    out = {}
    try:
        d = yf.download(sorted(set(tickers)), period="3mo", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    except Exception:
        return out
    for t in set(tickers):
        try:
            c = d[t]["Close"].dropna()
            r = c.pct_change().dropna() * 100
            out[t] = (float(r.iloc[-1]), float(r.iloc[-61:-1].abs().mean()))
        except Exception:
            pass
    return out


def fresh_news(query, limit=30, window_min=None):
    """Google News search with exact publish times; keeps only the last WINDOW_MIN minutes."""
    import requests, urllib.parse
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
    except Exception:
        return []
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=window_min or WINDOW_MIN)
    out = []
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if when < cut:
            continue
        title, src = (it.findtext("title") or "").strip(), it.findtext("source") or ""
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)]
        out.append({"title": title, "publisher": src, "link": it.findtext("link"),
                    "date": when.astimezone(CT).strftime("%b %d %I:%M %p")})
        if len(out) >= limit:
            break
    return out


def check_news(news_fn=None):
    """news_fn(query) -> [{'title','publisher','link','date'}]. Returns events that just broke."""
    state = _load()
    now = dt.datetime.now(CT)
    fired = []
    for ev in EVENTS:
        key = ev["key"]
        if key == "outage":
            pre = [i for i in fresh_news(ev["query"]) if re.search(ev["rx"], i["title"], re.I) and not re.search(AFTER_RX, i["title"], re.I)]
            m = re.search(r"microsoft|azure|aws|amazon|google|cloudflare|workday|salesforce|oracle|okta|verizon|at&t|t-mobile|outlook|teams",
                          " ".join(i["title"] for i in pre), re.I)
            key = "outage:" + (m.group(0).lower() if m else "other")
            if key in ("outage:outlook", "outage:teams", "outage:azure"):
                key = "outage:microsoft"
        last = state.get(key) or (state.get("outage") if key == "outage:microsoft" else None)
        if last and now - dt.datetime.fromisoformat(last) < dt.timedelta(hours=COOLDOWN_H):
            continue
        items = [i for i in fresh_news(ev["query"]) if re.search(ev["rx"], i["title"], re.I) and not re.search(AFTER_RX, i["title"], re.I)]
        outlets = {i["publisher"] for i in items if i.get("publisher")}
        extra = None
        if ev["key"] == "air":
            gs = faa_ground_stops()
            if gs and len(gs) >= 8:
                extra = f"FAA live status: **{len(gs)} airports** under a ground stop right now ({', '.join(a for a, _ in gs[:10])}…)"
        if len(outlets) >= MIN_OUTLETS or extra:
            state[key] = now.isoformat()
            hist = [h for h in state.get("history", []) if now - dt.datetime.fromisoformat(h[0]) < dt.timedelta(days=7)]
            items_top = [i["title"] for i in fresh_news(ev["query"]) if re.search(ev["rx"], i["title"], re.I)][:1]
            hist.append([now.isoformat(), key, (items_top[0] if items_top else ev["name"])[:140]])
            state["history"] = hist
            fired.append((ev, items, outlets, extra))
    _save(state)
    return fired


def event_card(ev, items, outlets, extra=None):
    now = dt.datetime.now(CT)
    official = [i for i in items if re.search(OFFICIAL_RX, i["title"], re.I)]
    unproven = [i for i in items if re.search(UNPROVEN_RX, i["title"], re.I)]
    lines = [f"📌 **What happened:** {items[0]['title'][:200]}" if items else "📌 **What happened:** see below",
             f"🕒 Spotted {now.strftime('%a %b %d, %I:%M %p')} Central · reported by **{len(outlets)} outlets** in the last {WINDOW_MIN} minutes"]
    if extra:
        lines.append("🛫 " + extra)
    for i in items[:3]:
        lines.append(f"• [{i['title'][:110]}]({i['link']}) · {i['publisher']} · {i['date']}")
    # skeptic check
    lines += ["", "🕵️ **Skeptic check (don't trust anyone's first story, officials or social media):**"]
    if official:
        lines.append(f"• Official line so far: \"{official[0]['title'][:140]}\". That's their FIRST explanation, not proof. Wait for details.")
    else:
        lines.append("• No official explanation yet. Early stories often get the cause wrong.")
    if unproven:
        lines.append(f"• Unproven claims are going around (\"{unproven[0]['title'][:100]}\"). Treat them as rumors until confirmed.")
    lines.append(f"• What would change the picture: {ev['watch']}")
    _now = dt.datetime.now(CT)
    recent = [h[1].replace("outage:", "").title() for h in _load().get("history", [])
              if h[1].startswith(("outage", "cyber", "air")) and _now - dt.datetime.fromisoformat(h[0]) < dt.timedelta(hours=48)]
    if len(set(recent)) >= 2:
        lines.append(f"• 🔁 **Pattern check:** big outages in the last 48 hours: {', '.join(dict.fromkeys(recent))}. "
                     "Several at once is worth questioning. Usually it's coincidence or a shared supplier; sometimes it's an attack "
                     "confirmed only later (Microsoft's June 2023 outages were admitted to be cyberattacks more than a week later).")
    # stocks
    mv = moves([t for t, _, _ in ev["stocks"]])
    lines += ["", "📊 **Stocks it can hit, and why:**"]
    for t, d, why in ev["stocks"]:
        m = mv.get(t)
        live = f" · {m[0]:+.1f}% {'today' if market_open() else 'last session'}" if m else ""
        lines.append(f"{d} **{t}**{live} · {why}")
    if not market_open():
        lines.append("_Market is closed: the reaction shows up at the next open (8:30 AM Central)._")
    lines += ["", f"📜 **What happened last time:** {ev['past']}",
              "", f"👉 **What to do:** don't trade the first headline. {ev['yours']} If it's one of our setups, a 📘 card will show up in #options-trades."]
    return {"color": 0xC53030, "title": f"🚨 BREAKING · {ev['name']}", "description": "\n".join(lines)[:4000],
            "footer": {"text": "Breaking-news watch, checked every 5 minutes · research only, not investment advice"}}


def check_money(movers33, news_fn):
    """During market hours: sector funds and your 33 moving 3x their normal day. Each ticker once per day."""
    if not market_open():
        return None
    state = _load()
    today = str(dt.date.today())
    done = set(state.get("money_" + today, []))
    mv = moves(list(SECTORS) + list(movers33))
    hits = []
    for t, (m, avg) in mv.items():
        floor = 2.0 if t in SECTORS else 6.0
        if t not in done and abs(m) >= max(3 * avg, floor):
            hits.append((t, m, avg))
    if not hits:
        return None
    state["money_" + today] = sorted(done | {t for t, _, _ in hits})
    _save(state)
    hits.sort(key=lambda x: (x[0] not in SECTORS, -abs(x[1])))
    lines = ["🤔 **Why it matters:** when a whole group moves this hard, big money is reacting to something, often before the news is clear. "
             "This tells you WHERE the money is moving so you can find out why.", ""]
    for t, m, avg in hits[:8]:
        label = SECTORS.get(t) or movers33.get(t, t)
        lines.append(f"{'🟩' if m > 0 else '🟥'} **{t}** ({label}) **{m:+.1f}%** today · a normal day is ±{avg:.1f}%")
        try:
            news = news_fn(f'"{label}" stocks when:3h' if t in SECTORS else f'"{movers33.get(t, t)}" when:3h')[:2]
        except Exception:
            news = []
        for n in news:
            lines.append(f"   ↳ [{n['title'][:100]}]({n['link']}) · {n['publisher']}")
        if not news:
            lines.append("   ↳ No clear headline yet. That itself is a warning: someone may know something the news doesn't yet.")
    lines += ["", "👉 **What to do:** don't chase a move that already happened. Read the headlines above; if a 🚨 BREAKING card follows, it explains "
                  "which stocks it can hit and why. If one of your 33 dips while still in an uptrend, a 📘 card will show up in #options-trades."]
    return {"color": 0xDD6B20, "title": f"💸 Money is moving · {len(hits)} sudden move{'s' if len(hits) > 1 else ''}",
            "description": "\n".join(lines)[:4000], "footer": {"text": "Checked every 10 minutes while the market is open · research only, not investment advice"}}


# ---------------------------------------------------------------- Monday preview: bitcoin trades all weekend, stocks don't
# From research/btc_weekend.py (96 weekends, ~2 years): Monday opening gap ≈ beta × bitcoin's Fri 4PM→Mon move.
# (ticker, beta, % of Monday gaps it explains, avg gap after a 4%+ bitcoin weekend drop)
WEEKEND_BETA = [("MSTR", 1.14, 71, -6.8), ("MARA", 0.98, 60, -5.9), ("RIOT", 0.89, 51, -5.6), ("COIN", 0.87, 66, -5.1),
                ("HOOD", 0.74, 39, -5.7), ("SOFI", 0.48, 26, -3.6), ("QQQ", 0.20, 26, -1.4), ("SPY", 0.15, 26, -1.2)]


# why-did-bitcoin-move: headline themes -> plain English
BTC_WHY = [
    (r"etf.{0,20}(outflow|withdraw)|outflows?", "💸 **Money leaving bitcoin funds** (ETF outflows): big investors are cashing out."),
    (r"liquidat", "🔥 **Forced selling**: traders who bet with borrowed money got sold out automatically, pushing the price down faster."),
    (r"\bfed\b|rate hike|interest rate|inflation|treasury yield", "🏛️ **Interest-rate fears**: when rates may go up, risky bets like bitcoin get sold first."),
    (r"\bipo\b|listing|liquidity", "🏦 **Money being pulled for other things** (big stock listings, cash needs)."),
    (r"iran|war|missile|strike|geopolit", "💥 **War fears**: people sell risky things when the world looks dangerous."),
    (r"hack|exploit|stolen|breach", "🛡️ **A crypto hack**: stolen funds scare buyers away."),
    (r"\bsec\b|regulat|lawsuit|ban\b", "⚖️ **Government/regulator action** on crypto."),
    (r"nvidia|tech (sell|stock)|nasdaq", "📉 **Tech stocks falling** and dragging crypto with them."),
    (r"whale|miners? sell|selling pressure", "🐋 **Big holders selling**."),
]
# company-specific landmines for the bitcoin-linked stocks
STOCK_DOTS = r"msci|index (removal|exclu|delet)|removed from|offering|dilut|convertible|downgrade|lawsuit|\bsec\b|subpoena|halt|margin call|default"
BTC_STOCKS = {"MSTR": "Strategy MicroStrategy", "COIN": "Coinbase", "MARA": "MARA Holdings", "RIOT": "Riot Platforms", "HOOD": "Robinhood"}


def btc_weekend_move():
    import yfinance as yf
    import pandas as pd
    b = yf.Ticker("BTC-USD").history(period="5d", interval="1h")["Close"].dropna()   # Ticker.history is safe to call from a thread
    b.index = b.index.tz_convert("America/New_York")
    now = pd.Timestamp.now(tz="America/New_York")
    fri = (now - pd.Timedelta(days=(now.weekday() - 4) % 7)).normalize() + pd.Timedelta(hours=16)
    b0, b1 = b[b.index <= fri].iloc[-1], b.iloc[-1]
    wk = b[b.index >= fri - pd.Timedelta(days=4)]
    return float(b0), float(b1), (b1 / b0 - 1) * 100, float(wk.iloc[0]), float(wk.min()), float(wk.max())


def monday_preview(force=False):
    """Bitcoin's weekend move -> expected Monday open, WHY bitcoin moved, hidden dots per stock, and this week's other events."""
    b0, b1, mv, wk0, lo, hi = btc_weekend_move()
    if abs(mv) < (2 if force else 3):
        return None
    lines = [f"📌 **Bitcoin since Friday's stock close:** ${b0:,.0f} → **${b1:,.0f} ({mv:+.1f}%)** · "
             f"this week: ${wk0:,.0f} → ${b1:,.0f} ({(b1 / wk0 - 1) * 100:+.1f}%), low ${lo:,.0f}",
             f"🕒 {dt.datetime.now(CT).strftime('%a %b %d, %I:%M %p')} Central", ""]
    # 1. why it moved
    heads = fresh_news('bitcoin (falls OR drops OR slides OR plunges OR crash OR rises OR surges OR jumps) why', 25, window_min=36 * 60)
    text = " ".join(h["title"] for h in heads).lower()
    reasons = [msg for rx, msg in BTC_WHY if re.search(rx, text)]
    lines.append("🔎 **Why bitcoin moved (what the news is saying):**")
    lines += [f"• {m}" for m in reasons[:5]] or ["• No clear reason in the headlines yet."]
    for h in heads[:3]:
        lines.append(f"   ↳ [{h['title'][:100]}]({h['link']}) · {h['publisher']}")
    # 2. expected Monday open
    lines += ["", "📊 **Expected Monday open if bitcoin stays here** (from 96 past weekends):"]
    for t, beta, r2, big in WEEKEND_BETA:
        lines.append(f"• **{t}** ≈ **{beta * mv:+.1f}%** · bitcoin explains {r2}% of its Monday moves"
                     + (" (strong)" if r2 >= 50 else " (weak)" if r2 < 30 else ""))
    card1 = {"color": 0xD69E2E, "title": f"🪙 Monday preview · bitcoin {mv:+.1f}% this weekend", "description": "\n".join(lines)[:4000]}
    lines = []
    # 3. hidden dots: company-specific news that can make a stock move MORE than bitcoin
    dots = []
    for t, name in BTC_STOCKS.items():
        q = "(" + " OR ".join(f'"{n}"' for n in name.split(" ", 1)) + ")" if t == "MSTR" else f'"{name}"'
        for h in fresh_news(q, 20, window_min=4 * 24 * 60):
            if re.search(STOCK_DOTS, h["title"], re.I):
                dots.append(f"• **{t}**: [{h['title'][:110]}]({h['link']}) · {h['publisher']}")
                break
    if dots:
        lines += ["🧩 **Hidden dots (company news that can make it fall MORE, or less, than bitcoin):**"] + dots
    # 4. other events this week
    st = _load()
    now = dt.datetime.now(CT)
    ev = [h for h in st.get("history", []) if len(h) > 2 and now - dt.datetime.fromisoformat(h[0]) < dt.timedelta(days=7)]
    if ev:
        lines += ["", "🗓️ **Other big events this week (from #breaking):**"]
        lines += [f"• {dt.datetime.fromisoformat(h[0]).strftime('%a')}: {h[2]}" for h in ev[-5:]]
        lines.append("Fear from these can add to selling, but check the reasons above: money flows usually matter more for bitcoin.")
    lines += ["", "🕵️ **Skeptic check:** the first four follow bitcoin closely, HOOD somewhat. For SOFI, SPY and QQQ, bitcoin explains only about "
                  "a quarter of Monday moves; other news matters more. Bitcoin can bounce before 8:30 AM Monday. Headlines explain AFTER the move; "
                  "they're not always the real cause.",
              "", "👉 **What to do:** don't buy the open on these. Big gap-downs often keep sliding the first hour. "
                  "If one of your 33 dips while still in an uptrend, a 📘 card will show up in #options-trades."]
    card2 = {"color": 0xD69E2E, "title": "🧩 Connections & what to do", "description": "\n".join(lines).strip()[:4000],
             "footer": {"text": "Weekend bitcoin watch · research only, not investment advice"}}
    return [card1, card2]


def weekend_check():
    """Hourly on weekends: post when bitcoin crosses a new 3% step from Friday's close (3%, 6%, 9%...)."""
    now = dt.datetime.now(CT)
    if not (now.weekday() >= 5 or (now.weekday() == 4 and now.hour >= 16) or (now.weekday() == 0 and now.hour < 9)):
        return None
    _b0, _b1, mv, *_ = btc_weekend_move()
    step = int(abs(mv) // 3)
    st = _load()
    wkey = "btc_step_" + (now - dt.timedelta(days=(now.weekday() - 4) % 7)).strftime("%Y-%m-%d")
    if step >= 1 and step > st.get(wkey, 0):
        st[wkey] = step
        _save(st)
        return monday_preview()
    return None
