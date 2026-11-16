"""
scout_render.py — turns facts + findings + AI analysis into
  (a) Discord embeds (clean cards with labeled sections), and
  (b) a matching Markdown file for the reports/ folder.
No emojis. Ratings appear as plain labels.
"""
import datetime as dt

from scout_analysis import money

NAVY = 0x1F3A5F
SLATE = 0x4A5568
RATING_COLOR = {"STRENGTH": 0x2F6F4E, "CONCERN": 0x9B2C2C, "WATCH": 0x975A16, "MIXED": 0x975A16}
FOOTER = "Data: Yahoo Finance (incl. last 4 quarterly statements) · Research only, not investment advice"

TERMS = {
    "Market value (market cap)": "Share price x number of shares. What the whole company is priced at.",
    "P/E": "Price divided by yearly profit per share. How many dollars you pay for $1 of profit.",
    "Operating income": "Profit from the actual business, before interest, taxes and one-off items.",
    "Net income": "Final profit after everything, including taxes and interest.",
    "Free cash flow": "Cash from operations minus spending on equipment. Money the company can actually use.",
    "Stock-based pay": "Paying employees in shares instead of cash. Saves cash, but adds new shares.",
    "Dilution": "New shares being created, so each existing share owns a smaller slice.",
    "Beta": "How much the stock moves versus the market. 2.0 = about twice as much, both up and down.",
    "Guidance": "The company's own forecast for next quarter. Often moves the stock more than the results.",
    "IV crush": "Option prices dropping right after earnings once the uncertainty is gone.",
}


RATING_ICON = {"STRENGTH": "✅", "CONCERN": "⚠️", "WATCH": "👀", "MIXED": "⚖️"}
BIZ_ICON = {"Strong": "💪", "Strong, with caveats": "💪", "Decent, with real weak spots": "🤏", "Weak": "🥀"}
PRICE_ICON = {"Expensive": "🔥", "Fair if growth holds": "⚖️", "Reasonable": "🏷️"}


# ---------------------------------------------------------------- color scoreboard
_SHORT = {"on": False}


def _row(label, value, good=None, bad=None, note=""):
    """One scoreboard line. Discord colors '+' lines green and '-' lines red inside a ```diff block."""
    mark = "+" if good else "-" if bad else " "
    if _SHORT["on"]:
        note = ""
    return f"{mark} {label:<16}{value:>8}  {note}".rstrip()


def scoreboard(s, short=False):
    _SHORT["on"] = short
    t = s.get("ttm") or {}
    rows = []
    g = s.get("revenue_growth_pct")
    if g is not None:
        rows.append(_row("Sales growth", f"{g:+.0f}%", g >= 15, g < 0, "latest qtr vs yr ago"))
    gm, om = s.get("gross_margin_pct"), s.get("operating_margin_pct")
    if gm is not None:
        rows.append(_row("Gross margin", f"{gm:.0f}%", gm >= 50, gm < 30, "pricing power"))
    if om is not None and not short:
        rows.append(_row("Operating margin", f"{om:.0f}%", om >= 15, om < 5, "core profit"))
    ni, ocf = t.get("net_income"), t.get("operating_cash_flow")
    if ni and ocf and ni > 0:
        c = ocf / ni
        rows.append(_row("Cash/$1 profit", f"${c:.2f}", c >= 0.9, c < 0.75, "cash backing"))
    cash, debt = s.get("total_cash"), s.get("total_debt")
    if cash is not None and debt is not None and not short:
        net = cash - debt
        rows.append(_row("Net cash", money(net), net > 0, net < 0, "cash minus debt"))
    now, ago = t.get("shares_now"), t.get("shares_year_ago")
    if now and ago and not short:
        ch = (now / ago - 1) * 100
        rows.append(_row("Share count", f"{ch:+.1f}%", ch <= 0, ch > 3, "dilution"))
    mc, rev = s.get("market_cap"), t.get("revenue") or s.get("revenue")
    if mc and rev:
        ps = mc / rev
        rows.append(_row("Price / sales", f"{ps:.1f}x", ps < 5, ps > 15, "valuation"))
    try:
        import scout_value
        v = scout_value.estimate(s)
    except Exception:
        v = None
    if v and v.get("gap_pct") is not None:
        base = v["scenarios"]["base"]["per_share"]
        rows.append(_row("Data value", money(base), base > v["price"] * 1.15, base < v["price"] * 0.85, "base case vs price"))
    pe = s.get("pe")
    if pe and not short:
        rows.append(_row("P/E", f"{pe:.0f}x", pe < 20, pe > 50, "price per $1 profit"))
    b = s.get("beta")
    if b is not None:
        rows.append(_row("Beta (swings)", f"{b:.1f}", b < 1, b >= 1.8, "vs market"))
    p, hi = s.get("price"), s.get("high_52w")
    if p and hi and not short:
        rows.append(_row("From 1-yr high", f"{(p/hi-1)*100:+.0f}%", None, None, ""))
    if not rows:
        return ""
    legend = "" if short else "\nGreen = good sign · Red = warning · Grey = neutral"
    return "```diff\n" + "\n".join(rows) + "\n```" + legend


# ---------------------------------------------------------------- helpers
def _trim(text, limit):
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > limit * 0.6 else cut.rstrip()) + "…"


def _days_until(d):
    try:
        return (dt.date.fromisoformat(str(d)[:10]) - dt.date.today()).days
    except (TypeError, ValueError):
        return None


def _earnings_txt(d):
    if not d:
        return "Not announced"
    n = _days_until(d)
    when = dt.date.fromisoformat(str(d)[:10]).strftime("%b %d")
    return f"{when} ({n} days)" if n is not None and n >= 0 else when


def _price_txt(s):
    p, c = s.get("price"), s.get("day_change_pct")
    return money(p) + (f"  ({c:+.2f}% today)" if c is not None else "")


def _finding_value(f, limit=1020):
    # give the facts first claim on space; reasoning and counterpoint share the rest
    facts = _trim(f["facts"], 560)
    room = limit - len(facts) - 60
    parts = [("Facts", facts, 560), ("Why it matters", f["reasoning"], int(room * 0.58)),
             ("The other side", f["counter"], int(room * 0.42))]
    out = "\n".join(f"**{label}:** {_trim(text, n)}" for label, text, n in parts)
    return _trim(out, limit)


def _case_lists(analysis, ai):
    if ai:
        return ai.get("bull_case", []), ai.get("bear_case", [])
    fs = analysis["findings"]
    bull = [f["claim"] for f in fs if f["rating"] == "STRENGTH"][:3]
    bear = [f["claim"] for f in fs if f["rating"] == "CONCERN"][:3]
    return bull, bear


def _bullets(items, limit=1020, mark="•"):
    return _trim("\n".join(f"{mark} {x}" for x in items), limit) or "None identified."


# ---------------------------------------------------------------- report: Discord embeds
def _how_to_use(s, analysis):
    """Plain 'what do I do with this report' block, built from the report's own verdicts."""
    biz, price = analysis["business_view"], analysis["price_view"]
    p, ma = s.get("price"), s.get("ma200")
    trend = None
    if p and ma:
        trend = "up" if p > ma else "down"
    lines = ["👉 **How to use this report:**"]
    if biz.startswith("Strong") and price == "Expensive":
        lines.append("• Good company, pricey stock. The business is fine; the risk is that the price already assumes years of success.")
    elif biz.startswith("Strong"):
        lines.append("• Good company at a price the numbers can support. Worth knowing well.")
    elif biz.startswith("Weak"):
        lines.append("• The business itself has real problems. Treat any trade as a short-term bet, not a long-term hold.")
    else:
        lines.append("• Mixed picture: some real strengths, some real weak spots. Read the ⚠️ findings below first.")
    if trend == "down":
        lines.append("• It's in a **downtrend** (below its 200-day average), so our dip-buy trades skip it for now.")
    elif trend == "up":
        lines.append("• It's in an **uptrend** (above its 200-day average), so it's eligible for our dip-buy trade cards.")
    ne = s.get("next_earnings")
    if ne:
        lines.append(f"• Next big event: **earnings {_earnings_txt(ne)}**. Options get expensive right before it; avoid buying options just before earnings.")
    lines.append("• This report is for *understanding* the stock. Trade ideas only come from the 📘/🟢 cards in #options-trades and #signals.")
    return "\n".join(lines)


def report_embeds(s, analysis, ai=None):
    name = (s.get("name") or s["ticker"]).replace(" (SAMPLE DATA)", "")
    today = dt.date.today().strftime("%B %d, %Y")
    summary = ai.get("short_version") if ai else analysis["summary"]
    embeds = []

    embeds.append({
        "color": NAVY,
        "title": _trim(f"📊 {name} ({s['ticker']})", 250),
        "description": _trim(f"**Research brief · {today}**\n\n{summary}\n\n" + _how_to_use(s, analysis), 4000),
        "fields": [
            {"name": "💵 Price", "value": _price_txt(s), "inline": True},
            {"name": "🏢 Market value", "value": money(s.get("market_cap")), "inline": True},
            {"name": "📅 Next earnings", "value": _earnings_txt(s.get("next_earnings")), "inline": True},
            {"name": f"{BIZ_ICON.get(analysis['business_view'], '🏢')} The business", "value": analysis["business_view"], "inline": True},
            {"name": f"{PRICE_ICON.get(analysis['price_view'], '🏷️')} The stock price", "value": analysis["price_view"], "inline": True},
            {"name": "📏 1-year range", "value": f"{money(s.get('low_52w'))} to {money(s.get('high_52w'))}", "inline": True},
            {"name": "🎯 Key numbers", "value": _trim(scoreboard(s), 1020) or "n/a", "inline": False},
        ],
    })

    vcard = value_embed(s)
    if vcard:
        embeds.append(vcard)

    if ai and ai.get("how_it_fits_together"):
        embeds.append({"color": NAVY, "title": "🧠 How the pieces fit together",
                       "description": _trim(ai["how_it_fits_together"], 4000)})

    if ai and ai.get("corrections"):
        embeds.append({"color": SLATE, "title": "🔍 Analyst check on the automated findings",
                       "description": _bullets(ai["corrections"], 4000)})

    fs = analysis["findings"][:9]
    for i, f in enumerate(fs):
        embeds.append({
            "color": RATING_COLOR.get(f["rating"], SLATE),
            "author": {"name": f"{RATING_ICON.get(f['rating'], '')} Finding {i + 1} of {len(fs)}  ·  {f['rating']}"},
            "title": _trim(f["claim"], 250),
            "description": _trim(f"📌 **Facts:** {f['facts']}\n\n💡 **Why it matters:** {f['reasoning']}\n\n🔄 **The other side:** {f['counter']}", 4000),
        })

    lcard = legal_embed(s)
    if lcard:
        embeds.append(lcard)
    embeds += debate_embeds(s, analysis, ai)

    embeds.append({"color": SLATE, "title": "📘 Terms used in this report",
                   "description": _trim("\n".join(f"**{k}:** {v}" for k, v in TERMS.items()), 4000),
                   "footer": {"text": FOOTER + (f" · Analysis: {ai['_usage']['model']}" if ai and ai.get('_usage') else
                                                (" · Written analysis: off (no AI key)" if not ai else ""))}})
    return embeds


def value_embed(s):
    try:
        import scout_analysis
        if scout_analysis.is_lender(s):
            return {"color": SLATE, "title": "💰 Data value vs market price: not used for lenders",
                    "description": "The data-value model is built on cash flow, and for banks and lenders cash flow is distorted "
                                   "(every new loan counts as cash going out). So it's switched off here. "
                                   f"Use the P/E instead: **{s.get('pe'):.0f}×** profit" if s.get("pe") else
                                   "The data-value model is built on cash flow, and for banks and lenders cash flow is distorted, so it's switched off here."}
        import scout_value
        v = scout_value.estimate(s)
    except Exception:
        v = None
    if not v or v.get("gap_pct") is None:
        return None
    sc, price = v["scenarios"], v["price"]

    def line(label, val):
        # green when the data value is ABOVE today's price (price looks cheap), red when below (price looks rich)
        mark = "+" if val > price * 1.05 else "-" if val < price * 0.95 else " "
        diff = (val / price - 1) * 100
        return f"{mark} {label:<13}{money(val):>9}  {diff:+.0f}% vs price"
    board = "\n".join([f"  {'Market price':<13}{money(price):>9}",
                        line("Bear value", sc["bear"]["per_share"]),
                        line("Base value", sc["base"]["per_share"]),
                        line("Bull value", sc["bull"]["per_share"])])
    icon = "🔥" if "OPTIMISTIC" in v["verdict"]["label"] else "🧊" if "PESSIMISTIC" in v["verdict"]["label"] else "🎯"
    desc = (f"**{icon} {v['verdict']['label'].title()}**\n"
            f"```diff\n{board}\n```"
            "Green = the numbers support MORE than today's price · Red = LESS\n\n"
            f"📈 **What the market is betting on:** {v['verdict']['text']}")
    cagr = v.get("implied_cagr")
    fields = []
    if cagr is not None:
        fields.append({"name": "📊 Growth: market's bet vs reality", "inline": False, "value": _trim(
            f"Market needs: **{cagr*100:.0f}%/yr for 10 yrs**\n"
            f"Company's latest quarter vs a year ago: **{v['growth_actual']*100:.0f}%**\n"
            f"Data model assumes: starts at {sc['base']['g0']*100:.0f}%, slows to 4% by year 10", 1020)})
    fields.append({"name": "🧮 Assumptions (change these and the value changes)", "inline": False,
                   "value": _trim("\n".join(f"• {a}" for a in v["assumptions"]), 1020)})
    return {"color": 0x9B2C2C if "OPTIMISTIC" in v["verdict"]["label"] else 0x2F6F4E if "PESSIMISTIC" in v["verdict"]["label"] else NAVY,
            "title": "💰 Data value vs market price", "description": _trim(desc, 4000), "fields": fields,
            "footer": {"text": "Data value = a discounted cash flow model from the company's own numbers. It's an estimate built on the "
                               "assumptions shown, not a fact. The market isn't proven wrong until results come in."}}


def legal_embed(s):
    items = s.get("legal")
    if items is None:
        return None
    import scout_legal as L
    c = L.summary_counts(items)
    head = "  ".join(f"{L.SEV_ICON[k]} {k.title()} {c[k]}" for k in ("CRITICAL", "SERIOUS", "MEDIUM", "LOW"))
    show = [i for i in items if i["severity"] != "LOW"][:6] or items[:3]
    lines = []
    for i in show:
        lines.append(f"{L.SEV_ICON[i['severity']]} **{i['severity']}** · {i['date']} · {i['source']}\n"
                     f"**{_trim(i['title'], 140)}** · {_trim(i['detail'], 80)}\n↳ {_trim(i['plain'], 260)}\n[Open]({i['link']})")
    worst = min((L.SEV_ORDER[i["severity"]] for i in items), default=3)
    color = {0: 0x9B2C2C, 1: 0x9B2C2C, 2: 0x975A16}.get(worst, 0x2F6F4E)
    body = (head + "\n\n" + ("\n\n".join(lines) if lines else "✅ Nothing found in federal courts, SEC red-flag filings, or legal news.")
            + f"\n\n_{len(items) - len(show)} more low-severity item(s) not shown._" if len(items) > len(show) else
            head + "\n\n" + ("\n\n".join(lines) if lines else "✅ Nothing found in federal courts, SEC red-flag filings, or legal news."))
    return {"color": color, "title": "⚖️ Lawsuits & red-flag filings (last 120 days)", "description": _trim(body, 4000),
            "footer": {"text": "Sources: federal courts (CourtListener), SEC 8-K event codes, legal news. Not covered: state courts, sealed cases. "
                               "A lawsuit is an accusation, not a verdict."}}


def meter(bull_w, bear_w, width=10):
    total = bull_w + bear_w
    g = round(width * bull_w / total) if total else width // 2
    return "🐂 " + "🟩" * g + "🟥" * (width - g) + " 🐻"


def _weight_dots(w):
    return "●●●" if w >= 2.5 else "●●○" if w >= 1.5 else "●○○"


SIDE_TXT = {"BULL": "🐂 Data leans BULL", "BEAR": "🐻 Data leans BEAR", "SPLIT": "⚖️ Data is SPLIT"}


def debate_embeds(s, analysis, ai=None):
    d = analysis["debate"]
    pct = round(100 * d["bull_weight"] / (d["bull_weight"] + d["bear_weight"])) if (d["bull_weight"] + d["bear_weight"]) else 50
    verdict = f"**{SIDE_TXT[d['side']]}**" + (f" ({d['strength'].lower()})" if d["side"] != "SPLIT" else "")
    desc = (f"{meter(d['bull_weight'], d['bear_weight'])}\n"
            f"{verdict} · evidence weight {pct}% bull / {100 - pct}% bear · confidence {d['confidence'].lower()} "
            f"({d['evidence_count']} checks)\n\n"
            f"🧑‍⚖️ **Why:** {d['why']}")
    fields = [
        {"name": "🐂 Bull case (people expecting the price to rise)", "value": _trim("\n".join(f"{_weight_dots(w)} {c}" for w, c in d["bull"]) or "No data-backed points.", 1020), "inline": False},
        {"name": "🐻 Bear case (people expecting it to fall)", "value": _trim("\n".join(f"{_weight_dots(w)} {c}" for w, c in d["bear"]) or "No data-backed points.", 1020), "inline": False},
    ]
    short = next((f for f in analysis["findings"] if f["kind"] == "check_short_interest"), None)
    if short:
        fields.append({"name": "🩳 What short sellers are doing", "value": _trim(short["facts"], 1020), "inline": False})
    fields += [
        {"name": "🔀 What would make the bulls right", "value": _trim(d["flip_to_bull"], 1020), "inline": False},
        {"name": "🔀 What would make the bears right", "value": _trim(d["flip_to_bear"], 1020), "inline": False},
    ]
    if ai and ai.get("judge"):
        j = ai["judge"]
        agree = "agrees" if str(j.get("leans", "")).upper() == d["side"] else "DISAGREES"
        fields.append({"name": f"🧠 Analyst judgment ({agree} with the scorecard)",
                       "value": _trim(f"**Leans {j.get('leans','?')} ({j.get('strength','')})** · {j.get('why','')}", 1020), "inline": False})
    fields.append({"name": "🕳️ What these numbers cannot tell you", "value": _bullets(analysis["blind_spots"]), "inline": False})
    cards = [{"color": NAVY, "title": "⚖️ Bull vs Bear: who has the data?", "description": _trim(desc, 4000),
              "fields": fields,
              "footer": {"text": "●●● = carries a lot of weight · ●○○ = minor. The meter weighs evidence, not opinions or hype. "
                                 "It says which argument the facts support today, not what the price will do."}}]

    gen, bear_news = _headline_lines(s, ai), s.get("bear_news") or []
    if gen or bear_news:
        parts = []
        if gen:
            parts.append("**📰 General coverage** (tends to lean positive)\n" + "\n".join(gen[:5]))
        if bear_news:
            parts.append("**🐻 Critical coverage** (searched for on purpose: downgrades, short reports, lawsuits, sell-offs)\n"
                         + "\n".join(f"🔻 {n.get('title')} ({n.get('publisher','')}, {n.get('date','')})" for n in bear_news[:5]))
        cards.append({"color": SLATE, "title": "📰 Headlines from both sides", "description": _trim("\n\n".join(parts), 4000)})
    return cards


def _headline_lines(s, ai):
    if ai and ai.get("headlines"):
        dot = {"Positive": "🟢", "Negative": "🔴", "Mixed": "🟡"}
        return [f"{dot.get(h.get('effect'), '⚪')} **{h.get('effect','')}** · {h.get('title','')} ({h.get('source','')}, {h.get('date','')})\n{h.get('reason','')}"
                for h in ai["headlines"] if h.get("title")]
    return [f"▫️ {n.get('title')} ({n.get('publisher','')}, {n.get('date','')})" for n in (s.get("news") or [])[:5]]


# ---------------------------------------------------------------- report: Markdown file
def report_markdown(s, analysis, ai=None):
    L = []
    for e in report_embeds(s, analysis, ai):
        if e.get("author"):
            L.append(f"#### {e['author']['name']}")
        L.append(f"## {e.get('title','')}")
        if e.get("description"):
            L.append(e["description"])
        for f in e.get("fields", []):
            if f.get("inline"):
                L.append(f"- **{f['name']}:** {f['value']}")
            else:
                L.append(f"\n**{f['name']}**\n\n{f['value']}")
        if e.get("footer"):
            L.append(f"\n_{e['footer']['text']}_")
        L.append("")
    L[0] = "# " + L[0][3:]
    return "\n".join(L)


# ---------------------------------------------------------------- daily digest
def _move_icon(c):
    if c is None:
        return "▫️"
    return "🟢 ▲" if c > 0 else "🔴 ▼" if c < 0 else "▫️"


def daily_embeds(items, alerts, upcoming, problems):
    """items: list of (snap, analysis, ai_or_None). One card per stock so each gets its own color bar."""
    today = dt.date.today().strftime("%A, %B %d, %Y")
    desc = []
    if alerts:
        desc.append("🔔 **Earnings alerts**\n" + "\n".join(f"• {a}" for a in alerts))
    desc.append("📅 **Earnings in the next 45 days:** " + (", ".join(upcoming) if upcoming else "none on file"))
    embeds = [{"color": NAVY, "title": "☀️ StockScout Daily Brief", "description": _trim(f"{today}\n\n" + "\n\n".join(desc), 4000)}]
    for s, an, ai in items:
        f0 = an["findings"][0] if an["findings"] else None
        c = s.get("day_change_pct")
        color = RATING_COLOR.get(f0["rating"], SLATE) if f0 else SLATE
        lines = [
            f"{BIZ_ICON.get(an['business_view'], '🏢')} **Business:** {an['business_view']}   "
            f"{PRICE_ICON.get(an['price_view'], '🏷️')} **Price:** {an['price_view']}",
            scoreboard(s, short=True),
        ]
        if f0:
            lines.append(f"{RATING_ICON.get(f0['rating'], '')} **Key point:** {f0['claim']}")
        if ai and ai.get("short_version"):
            lines.append(f"🧠 {_trim(ai['short_version'], 420)}")
        h = (ai or {}).get("headlines") or []
        dot = {"Positive": "🟢", "Negative": "🔴", "Mixed": "🟡"}
        if h and h[0].get("title"):
            lines.append(f"📰 {dot.get(h[0].get('effect'), '⚪')} {_trim(h[0]['title'], 160)}")
        elif s.get("news"):
            lines.append(f"📰 {_trim(s['news'][0]['title'], 160)}")
        lines.append(f"📅 Next earnings: {_earnings_txt(s.get('next_earnings'))}")
        embeds.append({
            "color": color,
            "title": _trim(f"{s['ticker']}  ·  {money(s.get('price'))}  {_move_icon(c)} {abs(c):.2f}%" if c is not None else f"{s['ticker']}  ·  {money(s.get('price'))}", 250),
            "description": _trim("\n".join(lines), 4000),
        })
    if problems:
        embeds.append({"color": 0x9B2C2C, "title": "⚠️ Problems this run", "description": _trim("\n".join(problems), 4000)})
    embeds[-1]["footer"] = {"text": FOOTER + " · Full report: run_scout.py report TICKER"}
    return embeds


def daily_markdown(embeds):
    L = []
    for e in embeds:
        L += [f"## {e['title']}", e.get("description", ""), ""]
    L.append(f"_{embeds[-1]['footer']['text']}_")
    L[0] = "# " + L[0][3:]
    return "\n".join(L)
