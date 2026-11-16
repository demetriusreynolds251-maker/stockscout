"""
scout_analysis.py — the reasoning engine (no AI needed).

Takes a snapshot of facts and runs a fixed set of cross-checks. Each check
produces a Finding with four parts, so every conclusion shows its work:

    rating     STRENGTH / CONCERN / MIXED / WATCH
    claim      one plain sentence: what we concluded
    facts      the numbers, with the math shown
    reasoning  why those numbers lead to that claim
    counter    the strongest argument AGAINST the claim (honesty check)

The checks deliberately combine numbers instead of judging any one alone.
Example: "sales up 104%" is not good or bad by itself. It is good if profit
and cash keep up, and it is already "paid for" if the stock price assumes
it continues for years. The engine checks both.

It also separates two questions people mix up:
    1. Is this a good BUSINESS?
    2. Is the STOCK a good deal at today's price?
A great business can be a bad buy if the price already expects perfection.
"""
import datetime as dt
import math

STRENGTH, CONCERN, MIXED, WATCH = "STRENGTH", "CONCERN", "MIXED", "WATCH"


def money(x):
    if x is None:
        return "n/a"
    x = float(x)
    sign = "-" if x < 0 else ""
    x = abs(x)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if x >= div:
            return f"{sign}${x/div:.1f}{unit}"
    return f"{sign}${x:,.2f}"


def _pct(x, d=0):
    return "n/a" if x is None else f"{x:.{d}f}%"


def _finding(rating, claim, facts, reasoning, counter, weight):
    return {"rating": rating, "claim": claim, "facts": facts, "reasoning": reasoning,
            "counter": counter, "weight": weight}


# ----------------------------------------------------------------------------
# Individual checks. Each returns a finding or None (when data is missing).
# ----------------------------------------------------------------------------
def check_growth(s):
    g = s.get("revenue_growth_pct")
    q = s.get("quarterly_revenue") or []
    if g is None:
        return None
    trend = ""
    if len(q) >= 3:
        seq = [(q[i][1] / q[i - 1][1] - 1) * 100 for i in range(1, len(q)) if q[i - 1][1]]
        last, prev = seq[-1], seq[-2] if len(seq) >= 2 else None
        trend = (f" Quarter-to-quarter, the latest quarter grew {last:.0f}%"
                 + (f" after {prev:.0f}% the quarter before" if prev is not None else "") + ".")
        # Only call it a change in pace if the move is meaningful (more than 3 points); otherwise it's steady.
        if prev is None or abs(last - prev) <= 3:
            accelerating = None
        else:
            accelerating = last > prev
    else:
        accelerating = None
    rev = s.get("ttm", {}).get("revenue") or s.get("revenue")
    latest = q[-1][1] if q else None
    facts = ((f"Latest quarter's sales: {money(latest)}, up {g:.0f}% from the same quarter a year earlier. " if latest else
              f"Sales up {g:.0f}% in the latest quarter versus the same quarter a year earlier. ")
             + f"Sales over the last 12 months: {money(rev)}.{trend}")
    if g >= 40:
        rating = STRENGTH if accelerating is not False else MIXED
        claim = "Sales are growing very fast" + (" and still speeding up." if accelerating else ", but the pace is clearly slowing." if accelerating is False else " at a steady pace.")
        reasoning = ("Fast growth means customers want more of the product than before. "
                     "The quarter-to-quarter trend matters more than the yearly number: the yearly figure looks backward, "
                     "the latest quarter shows where things are heading now.")
        counter = ("Growth percentages naturally shrink as a company gets bigger: doubling $1B is far harder than doubling $100M. "
                   "Fast growth also attracts competitors. And a big part of the yearly jump can come from one large customer "
                   "placing big orders, which can stop as quickly as it started.")
    elif g >= 10:
        rating, claim = STRENGTH, "Sales are growing at a healthy, steady rate."
        reasoning = "Double-digit growth for an established company usually means it is gaining ground in its market."
        counter = "Check whether growth is coming from selling more, or just raising prices; price increases run out."
    elif g >= 0:
        rating, claim = WATCH, "Sales are barely growing."
        reasoning = "Slow growth is normal for a mature company, but then the stock's value depends on profits and dividends, not expansion."
        counter = "A slow quarter can be timing (orders shifting between quarters), not a real slowdown. One quarter is not a trend."
    else:
        rating, claim = CONCERN, "Sales are shrinking."
        reasoning = "Falling sales mean fewer customers, lower prices, or both. Costs rarely fall as fast, so profits usually drop faster than sales."
        counter = "Some industries are cyclical (chips, autos): sales fall, then recover. The question is whether this is a cycle or a decline."
    return _finding(rating, claim, facts, reasoning, counter, 9)


def check_margins(s):
    gm, om = s.get("gross_margin_pct"), s.get("operating_margin_pct")
    if gm is None or om is None:
        return None
    facts = (f"Gross margin {gm:.0f}%: after the direct cost of making the product, {gm:.0f} cents of each sales dollar is left. "
             f"Operating margin {om:.0f}%: after also paying for research, sales staff and overhead, {om:.0f} cents is left.")
    if gm >= 55 and om >= 15:
        return _finding(STRENGTH, "High margins: customers pay well above what the product costs to make.", facts,
                        "A high gross margin is one of the best signs of pricing power: the product is hard to replace, so the company "
                        "doesn't have to compete on price. The gap between gross and operating margin is spending on research and "
                        "growth; as sales grow faster than that spending, operating margin usually rises.",
                        "Margins this high invite competitors. In chips especially, a rival's cheaper or better design can force price cuts. "
                        "Watch whether gross margin holds steady in the next few reports.", 7)
    if gm < 30 or om < 5:
        return _finding(CONCERN, "Thin margins: little room for error.", facts,
                        "With so little left from each sale, a small price cut or cost increase can wipe out profit.",
                        "Some great businesses run on thin margins at huge volume (retailers). It depends on the industry.", 6)
    return _finding(MIXED, "Margins are average.", facts,
                    "The company earns a normal amount on each sale: not a sign of special pricing power, not a red flag.",
                    "Trend matters more than level: rising margins would be a good sign.", 4)


def check_profit_quality(s):
    t = s.get("ttm", {})
    ni, oi = t.get("net_income"), t.get("operating_income")
    if ni is None or oi is None or ni <= 0:
        return None
    tax, interest = t.get("tax_provision"), t.get("interest_income")
    gap = ni - oi
    share = gap / ni * 100
    parts = []
    if tax is not None and tax < 0:
        parts.append(f"a net tax BENEFIT of {money(-tax)} (the company booked a tax credit instead of paying tax; the data doesn't say whether it repeats)")
    if interest:
        parts.append(f"{money(interest)} of interest earned on its cash pile")
    facts = (f"Profit after everything (net income): {money(ni)}. Profit from the actual business (operating income): {money(oi)}. "
             + (f"Difference: {money(gap)}, which is {share:.0f}% of reported profit. It comes from " + " and ".join(parts) + "." if gap > 0 and parts else ""))
    if share > 20:
        return _finding(CONCERN, "A big slice of reported profit does not come from selling products.", facts,
                        "Tax benefits and interest income are real money, but they are not the business. Tax benefits in particular "
                        "are often one-time or temporary. When they stop, profit drops even if sales keep growing. "
                        "So the P/E ratio (price compared to profit) looks cheaper than the business really is.",
                        "Interest on a large cash pile is fairly reliable while rates stay up. And many young companies get tax credits "
                        "from past losses; that is normal and legal. The core business profit is still positive and growing.", 8)
    if share < -20:
        return _finding(WATCH, "The core business earns more than the final profit shows.", facts,
                        "Something outside the main business (interest on debt, one-time charges, high tax) is pulling profit down. "
                        "The underlying business may be healthier than the headline profit suggests.",
                        "If the drag is interest on debt, it is not one-time: it continues until the debt is paid.", 5)
    return _finding(STRENGTH, "Reported profit comes almost entirely from the core business.", facts,
                    "When final profit and operating profit match closely, there are no big one-time items inflating or hiding results.",
                    "This says the profit is clean, not that it is large enough to justify the stock price.", 4)


def is_lender(s):
    """Banks, lenders, insurers, brokers: making loans/holding client money shows up as 'cash going out', so cash-flow checks mislead."""
    txt = f"{s.get('sector') or ''} {s.get('industry') or ''}".lower()
    return "financial" in txt or any(w in txt for w in ("bank", "credit", "lend", "mortgage", "insurance", "capital markets"))


def check_cash(s):
    if is_lender(s):
        return _finding(WATCH, "Cash-flow checks don't work for lenders and banks, so this one is skipped.",
                        f"{s.get('name') or s['ticker']} is a financial company ({s.get('industry') or 'lender'}).",
                        "When a lender makes a loan, the money it hands out is counted as cash going OUT of the business, so its "
                        "'cash flow' can look hugely negative even when it's healthy and profitable. For lenders, watch loan losses "
                        "(how many borrowers stop paying), deposits, and profit instead.",
                        "Profit and loan growth (shown in the other findings) are the better guide here.", 2)
    t = s.get("ttm", {})
    ni, ocf, fcf, sbc = t.get("net_income"), t.get("operating_cash_flow"), t.get("free_cash_flow"), t.get("stock_comp")
    if ocf is None or ni is None:
        return None
    conv = ocf / ni if ni else None
    facts = f"Cash actually collected from operations: {money(ocf)} vs reported profit {money(ni)}"
    facts += f" (that's {conv:.2f} dollars of cash per $1 of profit)." if conv and ni > 0 else "."
    if fcf is not None:
        facts += f" After buying equipment, free cash flow: {money(fcf)}."
    sbc_share = sbc / ocf * 100 if sbc and ocf and ocf > 0 else None
    if sbc_share is not None:
        facts += f" Stock handed to employees as pay: {money(sbc)}, equal to {sbc_share:.0f}% of operating cash flow."
    if sbc_share is not None and sbc_share > 40:
        return _finding(CONCERN, "Cash flow looks good partly because employees are paid in stock instead of cash.", facts,
                        "Paying people in stock saves cash today, so cash flow looks stronger. But it is still a real cost: every new share "
                        "makes each existing share own a smaller piece of the company. If you removed the stock pay and paid salaries "
                        f"in cash, operating cash flow would be about {money(ocf - sbc)} instead of {money(ocf)}.",
                        "Almost every fast-growing tech company does this to hire talent, and it aligns employees with shareholders. "
                        "What matters is whether the share count grows faster than the business. See the dilution check.", 7)
    if conv is not None and ni > 0 and conv < 0.8:
        rec, inv = t.get("chg_receivables"), t.get("chg_inventory")
        causes = []
        if rec is not None and rec < 0:
            causes.append(f"{money(-rec)} is money customers owe but haven't paid yet")
        if inv is not None and inv < 0:
            causes.append(f"{money(-inv)} went into building up inventory")
        lq = t.get("last_q") or {}
        lq_txt = ""
        if lq.get("net_income"):
            lq_conv = lq["operating_cash_flow"] / lq["net_income"]
            lq_txt = (f" In the latest quarter alone, cash was {lq_conv:.2f} per $1 of profit"
                      + (f", with {money(-lq['chg_receivables'])} of unpaid customer bills added" if lq.get("chg_receivables") and lq["chg_receivables"] < 0 else "") + ".")
        cause_txt = (" Where the gap went: " + "; ".join(causes) + "." if causes else "") + lq_txt
        growth = s.get("revenue_growth_pct") or 0
        explained = causes and growth >= 30
        return _finding(MIXED if explained and conv >= 0.6 else CONCERN,
                        "Profit is running ahead of the cash actually collected." if explained else "Profit is not turning into cash.",
                        facts + cause_txt,
                        "Profit is counted when a sale is booked; cash arrives when the customer pays. "
                        + ("When sales are growing this fast, unpaid bills and inventory naturally pile up, so some gap is expected. "
                           "The question is whether the cash catches up over the next couple of quarters. If unpaid bills keep "
                           "growing faster than sales, that can mean customers are stretching payments, or sales are being pulled "
                           "forward with generous terms." if explained else
                           "A lasting gap can mean customers are slow to pay, inventory is not selling, or profit is being "
                           "booked before the money is real."),
                        "Large, creditworthy customers (big cloud companies, governments) do pay; a temporary gap with them is low-risk. "
                        "Check next quarter: if cash collected jumps, this was timing, not a problem.", 7)
    return _finding(STRENGTH, "Profit is backed by real cash.", facts,
                    "Cash collected roughly matches or beats reported profit, which is the hardest number to fake.",
                    "Strong cash flow today does not guarantee it continues; it reflects the past 12 months.", 5)


def check_dilution(s):
    t = s.get("ttm", {})
    now, ago = t.get("shares_now"), t.get("shares_year_ago")
    if not now or not ago:
        return None
    ch = (now / ago - 1) * 100
    facts = f"Shares outstanding: {now/1e6:,.1f}M now vs {ago/1e6:,.1f}M a year ago ({ch:+.1f}%)."
    if ch > 3:
        return _finding(CONCERN, f"The company is creating new shares: about {ch:.1f}% more than a year ago.", facts,
                        f"If the company's total value stayed flat, each share would be worth about {ch:.1f}% less, because the pie is "
                        "cut into more slices. The business has to grow faster than the share count just for your slice to grow.",
                        "With sales growing far faster than the share count, each share still owns a bigger business than last year. "
                        "This becomes a real problem when growth slows and the dilution keeps going.", 5)
    if ch < -1:
        return _finding(STRENGTH, f"The company is buying back its own shares ({abs(ch):.1f}% fewer than a year ago).", facts,
                        "Fewer shares means each remaining share owns more of the company and more of its profit.",
                        "Buybacks at a very high price can waste money that could have grown the business.", 4)
    return None


def check_valuation(s):
    """Price check. Uses the data-value model (scout_value) when the company has the numbers for it;
    falls back to a simple reverse check otherwise."""
    try:
        import scout_value
        v = None if is_lender(s) else scout_value.estimate(s)
    except Exception:
        v = None
    if v and v.get("gap_pct") is not None:
        sc, price = v["scenarios"], v["price"]
        base = sc["base"]["per_share"]
        facts = (f"Market price ${price:,.2f}. Data value (what the company's own numbers support): "
                 f"bear ${sc['bear']['per_share']:,.0f} · base ${base:,.0f} · bull ${sc['bull']['per_share']:,.0f}. "
                 f"The price is {abs(v['gap_pct']):.0f}% {'above' if v['gap_pct'] > 0 else 'below'} the base value. "
                 + v["verdict"]["text"])
        if price > sc["bull"]["per_share"]:
            return _finding(CONCERN, "The price is above even the optimistic data value: the market is betting on something rare.", facts,
                            "Even if things go about as well as the numbers allow, the stock is still priced higher. For it to work out, "
                            "the company has to beat its own best-case trajectory. That can happen, but it's the exception, and stocks "
                            "priced this way fall hard when growth merely stays good instead of great.",
                            "The model can't see breakthroughs, new markets, or a company changing its whole industry. "
                            "Markets sometimes price those in correctly before they show up in the numbers.", 10)
        if price > base * 1.15:
            return _finding(CONCERN, "The market is more optimistic than the data: the price assumes better-than-base results.", facts,
                            "The price sits between the base and bull cases, so investors are already paying for an above-average future. "
                            "If results land at 'base', the stock has room to fall even though the business is fine.",
                            "Being between base and bull is not crazy for a company growing this fast. If the next few reports keep "
                            "beating expectations, the bull case becomes the realistic one.", 10)
        if price < sc["bear"]["per_share"]:
            return _finding(STRENGTH, "The price is below even the pessimistic data value: the market may be too gloomy.", facts,
                            "Even if things go poorly, the numbers support a higher value than today's price. That's the kind of gap "
                            "where the market may have it wrong, IF the data is right.",
                            "Very cheap stocks are often cheap because the market expects the numbers to get worse. Look for the "
                            "reason in the critical headlines before trusting this.", 10)
        if price < base * 0.85:
            return _finding(STRENGTH, "The market is more pessimistic than the data: the price is below the base value.", facts,
                            "The price assumes worse-than-base results, so ordinary results could lift it.",
                            "The model uses past numbers. If the business is about to slow sharply, the market may be ahead of the data.", 10)
        return _finding(MIXED, "The market price roughly matches what the data supports.", facts,
                        "No big gap either way: the price is in line with a realistic future. The stock will mostly move with actual results.",
                        "Fair price doesn't mean safe: a miss on growth still moves the stock down.", 8)

    mc, rev = s.get("market_cap"), s.get("ttm", {}).get("revenue") or s.get("revenue")
    g, opm = s.get("revenue_growth_pct"), s.get("operating_margin_pct")
    pe, fpe = s.get("pe"), s.get("forward_pe")
    if not mc or not rev:
        return None
    ps = mc / rev
    # Reverse the math: what sales would justify today's price once the company is "grown up"?
    mature_margin = min(max((opm or 20) / 100 * 0.8, 0.20), 0.45)  # after-tax margin assumption, stated below
    mature_pe = 25
    needed_rev = mc / (mature_margin * mature_pe)
    multiple = needed_rev / rev
    years_30 = math.log(multiple) / math.log(1.30) if multiple > 1 else 0
    facts = (f"Company value (market cap): {money(mc)}. Sales: {money(rev)}. So investors pay {ps:.1f} dollars for each $1 of yearly sales"
             + (f"; {pe:.0f} times last year's profit" if pe else "")
             + (f" and {fpe:.0f} times next year's expected profit" if fpe else "") + ".")
    math_txt = (f"Reverse check: if the company eventually earns {mature_margin*100:.0f} cents of profit per sales dollar and trades at "
                f"{mature_pe} times profit (a normal level for a solid company), today's price needs about {money(needed_rev)} in yearly sales, "
                f"which is {multiple:.1f}x current sales.")
    if multiple > 1.2:
        math_txt += f" At 30% growth per year, that takes about {years_30:.1f} years of uninterrupted growth."
    if multiple >= 3:
        return _finding(CONCERN, "The price already assumes years of strong growth with no stumbles.", facts + " " + math_txt,
                        "This is the most important point in the report. The business can keep doing well and the stock can still fall, "
                        "because the price is not paying for today's company; it is paying for the company several years from now. "
                        "Any sign that growth is slowing, even if it is still fast, can cause a sharp drop.",
                        "The market sometimes underestimates winners: companies at the center of a big shift (like AI) have grown into "
                        "prices that looked crazy at the time. The assumptions above (margin, 25x profit) are simple averages and "
                        f"could be too conservative{'; its forward P/E of ' + format(fpe, '.0f') + ' is much lower than the trailing one' if fpe and pe and fpe < pe * 0.6 else ''}.", 10)
    if multiple >= 1.3:
        return _finding(MIXED, "The price expects solid growth, but not a miracle.", facts + " " + math_txt,
                        "The company needs to keep growing for a couple of years to justify today's price. That is a reasonable bet if "
                        "growth holds, and a painful one if it stalls.",
                        "The 25x-profit and margin assumptions are simplifications; a truly dominant company can deserve more.", 8)
    return _finding(STRENGTH, "The price is reasonable for what the company earns today.", facts + " " + math_txt,
                    "Today's sales and margins already roughly support the price, so the stock does not need heroic growth to hold up.",
                    "Cheap stocks are sometimes cheap for a reason: the market may expect profits to fall. Check the growth trend.", 8)


def check_balance_sheet(s):
    cash, debt, cr = s.get("total_cash"), s.get("total_debt"), s.get("current_ratio")
    de = s.get("debt_to_equity")
    if cash is None or debt is None:
        return None
    net = cash - debt
    facts = f"Cash: {money(cash)}. Debt: {money(debt)}. Net: {money(net)}" + (f" ({'more cash than debt' if net > 0 else 'more debt than cash'})." )
    if de is not None:
        facts += f" Debt is {de:.2f}x what shareholders own."
    if net > 0 and (de is None or de < 0.5):
        return _finding(STRENGTH, "Strong balance sheet: more cash than debt.", facts,
                        "A company with net cash can survive a bad year, keep investing when rivals pull back, and does not need to "
                        "sell new shares or borrow at a bad moment.",
                        "Lots of idle cash can also mean management has no better use for it. It does not make the stock cheap.", 4)
    if de is not None and de > 1.5:
        return _finding(CONCERN, "Heavy debt load.", facts,
                        "Debt has to be repaid no matter how business goes. If sales dip, interest payments eat a bigger share of profit.",
                        "Stable businesses (utilities, real estate) carry debt safely. It matters most for companies with uneven sales.", 6)
    return None


def check_volatility(s):
    b = s.get("beta")
    p, hi, lo = s.get("price"), s.get("high_52w"), s.get("low_52w")
    if b is None and not (p and hi):
        return None
    facts = ""
    if b is not None:
        facts += f"Beta: {b:.2f}. "
    if p and hi and lo:
        off = (1 - p / hi) * 100
        facts += f"Price {money(p)}: {off:.0f}% below its 1-year high of {money(hi)} and {(p/lo-1)*100:.0f}% above its low of {money(lo)}."
    ma50, ma200 = s.get("ma50"), s.get("ma200")
    if p and ma50 and ma200:
        facts += f" Average price last 50 days {money(ma50)}, last 200 days {money(ma200)}."
    if b is not None and b >= 1.8:
        drop = b * 10
        if s.get("ipo_recent"):
            facts += " Note: the company has only traded publicly for a short time, so this beta is based on limited history."
        return _finding(WATCH, "This stock swings much harder than the market, in both directions.", facts,
                        f"A beta of {b:.1f} means that when the overall market falls 10%, this stock has historically fallen around {drop:.0f}%. "
                        "That matters a lot for how you'd trade it. With margin (borrowed money), losses are multiplied: a "
                        f"{drop:.0f}% drop on 2x margin wipes out about {min(drop*2,100):.0f}% of your own money and can trigger a forced sale. "
                        "With options, the same move can take an option to zero.",
                        "Big swings work both ways: the same stock tends to rise faster when the market rises. Volatility is a risk to "
                        "manage with position size, not automatically a reason to avoid it.", 6)
    return None


def check_analysts(s):
    p, tgt, lo, hi, n, rm = (s.get("price"), s.get("analyst_target"), s.get("target_low"), s.get("target_high"),
                             s.get("analyst_count"), s.get("rec_mean"))
    if not p or not tgt:
        return None
    gap = (tgt / p - 1) * 100
    facts = (f"{n or 'Several'} analysts. Average 12-month target {money(tgt)} ({gap:+.0f}% from today), "
             f"range {money(lo)} to {money(hi)}.")
    if rm:
        facts += f" Average rating {rm:.1f} on a 1 (strong buy) to 5 (sell) scale."
    return _finding(WATCH, "Wall Street is positive, but treat that as one opinion, not evidence.", facts,
                    "Analyst targets are useful for knowing what the market expects. They are not a forecast you can rely on: "
                    "analysts rarely say 'sell' (their firms often want the company's business), and targets tend to follow the price "
                    "rather than lead it. A very wide range between the lowest and highest target means even experts disagree a lot.",
                    "Analysts do have direct access to management and industry data, so a large gap between price and target can be real "
                    "information. Just weigh it less than the company's own numbers.", 3)


def check_earnings(s, today=None):
    d = s.get("next_earnings")
    if not d:
        return None
    today = today or dt.date.today()
    try:
        days = (dt.date.fromisoformat(str(d)[:10]) - today).days
    except ValueError:
        return None
    if days < 0 or days > 30:
        return None
    facts = f"Next earnings report: {dt.date.fromisoformat(str(d)[:10]).strftime('%B %d, %Y')} ({days} days away)."
    return _finding(WATCH, f"Earnings report in {days} days: expect a big move either way.", facts,
                    "On earnings day the stock reacts to two things: the results versus what Wall Street expected, and the company's "
                    "forecast for next quarter (guidance). Guidance usually matters more. A stock this richly priced can fall on a good "
                    "quarter if the forecast is merely okay. For options: prices rise before earnings because everyone expects a big move, "
                    "then collapse right after (called 'IV crush'). You can be right about the direction and still lose money on an option.",
                    "Earnings are also when the company gives the most new information. Waiting until after the report means paying "
                    "a possibly higher or lower price, but with far less guessing.", 7)


def check_short_interest(s):
    si, now, prior, dtc = s.get("short_pct_float"), s.get("shares_short"), s.get("shares_short_prior"), s.get("short_days_to_cover")
    if si is None:
        return None
    facts = f"{si:.1f}% of tradable shares are sold short (borrowed and sold by people betting the price falls)."
    trend = None
    if now and prior:
        trend = (now / prior - 1) * 100
        facts += f" That bet {'grew' if trend > 0 else 'shrank'} {abs(trend):.0f}% over the last month."
    if dtc:
        facts += f" It would take short sellers about {dtc:.1f} days of normal trading to buy back their shares ('days to cover')."
    if si < 3 and (trend is None or trend < 15):
        return _finding(STRENGTH, "Very few professionals are betting against it.", facts,
                        "Short sellers tend to be skeptical, well-researched investors. When almost none of them bother to bet "
                        "against a stock, they don't see an obvious flaw or overpricing worth the risk.",
                        "Low short interest is common for very large, popular companies simply because betting against them is "
                        "expensive and risky. It shows a lack of doubters, not proof the price is right.", 3)
    rating = CONCERN if si >= 10 or (trend is not None and trend >= 20) else WATCH
    claim = ("Short sellers are betting heavily against it" if si >= 10 else "Some professionals are betting against it") + \
            (", and that bet is growing." if trend is not None and trend >= 10 else ".")
    return _finding(rating, claim, facts,
                    "Short sellers usually do serious homework, and they lose money if they're wrong, so their bet is a signal "
                    "that some professionals think the price is too high or see a specific problem. A rising short bet means "
                    "that view is gaining support.",
                    "Heavy shorting can also push the price UP fast: when good news hits, short sellers must buy shares back to "
                    "cut losses (a 'short squeeze'). The more days to cover, the bigger that risk for them.", 4 if rating == CONCERN else 3)


def check_legal(s):
    items = s.get("legal")
    if items is None:
        return None  # legal check didn't run (e.g. demo or funnel scan)
    cutoff = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    recent = [i for i in items if (i.get("date") or "") >= cutoff and i["source"] != "News"]
    bad = [i for i in recent if i["severity"] in ("CRITICAL", "SERIOUS")]
    mid = [i for i in recent if i["severity"] == "MEDIUM"]
    if bad:
        crit = any(i["severity"] == "CRITICAL" for i in bad)
        facts = "Last 90 days: " + "; ".join(f"{i['date']} {i['title']} ({i['detail']})" for i in bad[:4]) + "."
        return _finding(CONCERN, ("A critical red-flag filing" if crit else "Serious legal or regulatory action") + " in the last 90 days.", facts,
                        "Securities suits, government actions and accounting red flags can mean settlements, fines, management "
                        "distraction, and lost trust. The stock usually reacts most when the problem first becomes public, and again "
                        "when the scale of the damage becomes clear.",
                        "A lawsuit is an accusation, not a verdict. Many securities suits are dismissed or settle for amounts that are "
                        "small next to the company's value. What matters is whether the claim hits the core business.", 6 if crit else 5)
    facts = (f"Checked federal court cases, SEC red-flag filings and legal news for the last 90 days: no serious items found"
             + (f"; {len(mid)} medium item(s) (e.g. {mid[0]['title']})." if mid else "."))
    return _finding(STRENGTH if not mid else WATCH, "No serious lawsuits or red-flag filings found recently.", facts,
                    "No securities-fraud suits, government actions, restatements or auditor changes showed up in the sources checked.",
                    "These sources miss state courts and sealed cases, and a new suit can be filed tomorrow. Absence here is reassuring, not proof.", 2)


CHECKS = [check_valuation, check_growth, check_margins, check_profit_quality, check_cash, check_dilution,
          check_balance_sheet, check_volatility, check_earnings, check_short_interest, check_legal, check_analysts]


# ----------------------------------------------------------------------------
# Putting it together
# ----------------------------------------------------------------------------
# How much each check counts toward "is this a good BUSINESS". Growth and margins matter most;
# dilution matters least because it only bites when growth slows.
BUSINESS_WEIGHTS = {"check_growth": 3, "check_margins": 2, "check_cash": 1.5, "check_profit_quality": 1,
                    "check_balance_sheet": 1, "check_dilution": 0.5}
SIGN = {STRENGTH: 1, CONCERN: -1, MIXED: 0, WATCH: 0}


def analyze(s, today=None):
    findings = []
    for fn in CHECKS:
        try:
            f = fn(s, today) if fn is check_earnings else fn(s)
        except Exception:
            f = None
        if f:
            f["kind"] = fn.__name__
            findings.append(f)
    findings.sort(key=lambda f: -f["weight"])

    biz = [f for f in findings if f["kind"] in BUSINESS_WEIGHTS]
    score = sum(BUSINESS_WEIGHTS[f["kind"]] * SIGN[f["rating"]] for f in biz)
    has_concern = any(f["rating"] == CONCERN for f in biz)
    if len(biz) < 2:
        business = "Not enough data"
    elif score >= 3:
        business = "Strong, with caveats" if has_concern else "Strong"
    elif score >= 0:
        business = "Decent, with real weak spots"
    else:
        business = "Weak"
    val = next((f for f in findings if f["kind"] == "check_valuation"), None)
    price = {CONCERN: "Expensive", MIXED: "Fair if growth holds", STRENGTH: "Reasonable"}.get(val["rating"] if val else None, "Not enough data")
    return {
        "findings": findings,
        "business_view": business,
        "price_view": price,
        "business_score": score,
        "summary": _summary(s, findings, business, price),
        "debate": debate(findings),
        "blind_spots": blind_spots(s),
    }


# ----------------------------------------------------------------------------
# Bull vs bear: whose argument has more evidence behind it?
# ----------------------------------------------------------------------------
# How much each check counts in the debate. The price check counts most: it decides whether
# good news is already paid for. Analyst opinions count least: they lean positive by habit.
DEBATE_WEIGHT = {"check_valuation": 3.0, "check_growth": 2.5, "check_margins": 1.5, "check_cash": 1.5,
                 "check_profit_quality": 1.5, "check_dilution": 0.75, "check_balance_sheet": 1.0,
                 "check_short_interest": 1.0, "check_legal": 1.5, "check_analysts": 0.5}


def debate(findings):
    bull, bear = [], []
    for f in findings:
        w = DEBATE_WEIGHT.get(f["kind"])
        if not w:
            continue  # volatility and earnings timing are risks, not evidence of direction
        if f["kind"] == "check_analysts":
            bull.append((w, f["claim"]))
        elif f["rating"] == STRENGTH:
            bull.append((w, f["claim"]))
        elif f["rating"] == CONCERN:
            bear.append((w, f["claim"]))
        elif f["rating"] == MIXED:
            bull.append((w / 2, f["claim"])); bear.append((w / 2, f["claim"]))
        elif f["rating"] == WATCH and f["kind"] == "check_short_interest":
            bear.append((w / 2, f["claim"]))
    b, r = sum(w for w, _ in bull), sum(w for w, _ in bear)
    total = b + r
    lean = (b - r) / total if total else 0
    if abs(lean) < 0.15:
        side, strength = "SPLIT", "Even"
    else:
        side = "BULL" if lean > 0 else "BEAR"
        strength = "Strong" if abs(lean) >= 0.5 else "Moderate" if abs(lean) >= 0.3 else "Slight"
    n = len([f for f in findings if f["kind"] in DEBATE_WEIGHT])
    confidence = "High" if n >= 8 else "Medium" if n >= 5 else "Low"
    out = {"bull": sorted(bull, reverse=True), "bear": sorted(bear, reverse=True), "bull_weight": round(b, 2),
           "bear_weight": round(r, 2), "lean": round(lean, 2), "side": side, "strength": strength,
           "confidence": confidence, "evidence_count": n}
    out.update(_explain(findings, out))
    return out


def _explain(findings, d):
    """Turn the tally into a plain verdict: who is right about WHAT, and what would change it."""
    by = {f["kind"]: f for f in findings}
    biz_good = [f for f in findings if f["kind"] in BUSINESS_WEIGHTS and f["rating"] == STRENGTH]
    biz_bad = [f for f in findings if f["kind"] in BUSINESS_WEIGHTS and f["rating"] == CONCERN]
    val = by.get("check_valuation")
    price_bad = val is not None and val["rating"] == CONCERN
    price_ok = val is not None and val["rating"] == STRENGTH
    top_bull = d["bull"][0][1] if d["bull"] else None
    top_bear = d["bear"][0][1] if d["bear"] else None

    good_w = sum(BUSINESS_WEIGHTS[f["kind"]] for f in biz_good)
    bad_w = sum(BUSINESS_WEIGHTS[f["kind"]] for f in biz_bad)
    if good_w > bad_w and price_bad:
        why = ("Both sides are right, about different things. The bulls are right about the BUSINESS: "
               + "; ".join(f["claim"].rstrip(".")[0].lower() + f["claim"].rstrip(".")[1:] for f in sorted(biz_good, key=lambda f: -BUSINESS_WEIGHTS[f["kind"]])[:2]) + ". "
               "The bears are right about the PRICE: it already pays for years of that success. "
               "So the real question isn't 'is this a good company' (it is) but 'can it grow fast enough, for long enough, "
               "to justify what people are paying'. That gets answered one earnings report at a time.")
        flip_bull = "Growth keeps speeding up and operating margin rises: the company grows into its price faster than the math assumes."
        flip_bear = "Any quarter where growth slows noticeably or the company's forecast disappoints: at this price there is little cushion."
    elif d["side"] == "BULL":
        why = (f"The evidence favors the bulls. Their strongest point: {top_bull[0].lower() + top_bull[1:] if top_bull else 'n/a'} "
               + (f"The bears' best point ({top_bear.rstrip('.').lower()}) is real but carries less weight in the numbers." if top_bear else
                  "The bears don't have a strong, data-backed point right now.")
               + (" The price doesn't require heroic assumptions, which removes the usual bear argument." if price_ok else ""))
        flip_bull = "Already the leaning side; it strengthens if the next report confirms the trend."
        flip_bear = "Sales growth stalling, margins falling, or cash collection lagging profit for two quarters in a row."
    elif d["side"] == "BEAR":
        why = (f"The evidence favors the bears. Their strongest point: {top_bear[0].lower() + top_bear[1:] if top_bear else 'n/a'} "
               + (f"The bulls' best point ({top_bull.rstrip('.').lower()}) doesn't outweigh it." if top_bull else
                  "The bulls don't have a strong, data-backed point right now."))
        flip_bull = "Faster sales growth, improving margins, or the price falling enough that the valuation math works."
        flip_bear = "Already the leaning side; it strengthens if the weak spots show up again in the next report."
    else:
        why = ("The evidence is genuinely balanced. "
               + (f"Best bull point: {top_bull.rstrip('.').lower()}. " if top_bull else "")
               + (f"Best bear point: {top_bear.rstrip('.').lower()}. " if top_bear else "")
               + "Neither side has a clear data advantage, so the next earnings report is likely to decide it.")
        flip_bull = "A strong report: growth holding up and margins improving."
        flip_bear = "A weak report: slowing growth or a disappointing forecast."
    return {"why": why, "flip_to_bull": flip_bull, "flip_to_bear": flip_bear}


def _summary(s, findings, business, price):
    biz_txt = {"Strong": "A strong business", "Strong, with caveats": "A strong business with some soft spots",
               "Decent, with real weak spots": "A decent business with real weak spots", "Weak": "A weak business"
               }.get(business, "Not enough data to judge the business")
    good_biz = business.startswith("Strong")
    price_txt = {"Expensive": ("but " if good_biz else "and ") + "the stock is priced as if everything keeps going right.",
                 "Fair if growth holds": "and the stock is fairly priced as long as growth holds.",
                 "Reasonable": ("at " if good_biz else "but at ") + "a price that doesn't need heroic assumptions."
                 }.get(price, "; not enough data to judge the price.")
    lead = f"{biz_txt}, {price_txt}" if price in ("Expensive", "Fair if growth holds") else f"{biz_txt} {price_txt}"
    concern = next((f["claim"] for f in findings if f["rating"] == CONCERN), None)
    strength = next((f["claim"] for f in findings if f["rating"] == STRENGTH), None)
    out = [lead]
    if strength:
        out.append(f"Best evidence for it: {strength[0].lower() + strength[1:]}")
    if concern:
        out.append(f"Biggest issue: {concern[0].lower() + concern[1:]}")
    return " ".join(out)


def blind_spots(s):
    out = [
        "Who the customers are. If one or two buyers make up most of sales, one lost contract changes everything. Check the 10-K's customer section.",
        "Competition and new products. Numbers show the past; they can't see a rival's better product coming.",
        "Management's forecast. The next earnings call's guidance will move the stock more than anything in this report.",
    ]
    if s.get("source", "").startswith("Yahoo"):
        out.append("Data freshness. Yahoo's numbers can lag by a day and occasionally contain errors. Confirm anything you act on in the company's own filings.")
    return out
