"""
scout_value.py — "real data value" vs "market value".

Two questions, same math run in opposite directions:

  1. DATA VALUE: what is the company worth if it keeps doing roughly what its
     numbers say it can do? (a discounted cash flow, "DCF", in three scenarios)
  2. MARKET-IMPLIED GROWTH: what would the company have to achieve for today's
     price to be fair? (the same model solved backwards)

Comparing the two tells you whether the market is betting on something
realistic or something rare. Every assumption is returned so the report can
show it. This is an estimate, never a fact.

The model, in plain words:
  - Sales grow at a starting rate that fades in a straight line to 4% by year 10
    (fast growth always slows as a company gets big).
  - Free cash flow margin (cash kept per $1 of sales, AFTER subtracting stock
    paid to employees, because that's a real cost) moves from today's level to
    a "grown-up" level by year 5.
  - Each future year's cash is discounted (a dollar in 10 years is worth less
    than a dollar today) at 10% a year, and after year 10 the company is
    assumed to grow 3% a year forever.
  - Add cash, subtract debt, divide by the number of shares.
"""

YEARS, FADE_TO, TERMINAL_G = 10, 0.04, 0.03


def _growth_path(g0, years=YEARS):
    return [g0 - (g0 - FADE_TO) * i / (years - 1) for i in range(years)]


def _equity_value(rev0, g0, m0, m_mature, r, net_cash):
    rev, pv = rev0, 0.0
    fcf = 0.0
    for t, g in enumerate(_growth_path(g0), 1):
        rev *= 1 + g
        m = m0 + (m_mature - m0) * min(t, 5) / 5
        fcf = rev * m
        pv += fcf / (1 + r) ** t
    terminal = fcf * (1 + TERMINAL_G) / (r - TERMINAL_G)
    pv += terminal / (1 + r) ** YEARS
    return pv + net_cash, rev


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def estimate(s):
    t = s.get("ttm") or {}
    rev = t.get("revenue") or s.get("revenue")
    fcf, sbc = t.get("free_cash_flow"), t.get("stock_comp") or 0
    shares = t.get("shares_now") or s.get("shares_out")
    price, mc = s.get("price"), s.get("market_cap")
    growth = s.get("revenue_growth_pct")
    if not all([rev, shares, price, mc]) or fcf is None or growth is None or rev <= 0:
        return None
    net_cash = (s.get("total_cash") or 0) - (s.get("total_debt") or 0)
    g_actual = growth / 100

    # Starting growth: anchored on actual growth, capped by size (a $300B company can't grow like a $1B one).
    cap = 0.50 if rev < 5e9 else 0.35 if rev < 50e9 else 0.25
    m_now = (fcf - sbc) / rev                     # cash margin after paying for stock-based pay
    om = (s.get("operating_margin_pct") or 0) / 100
    m_mature = _clamp(max(m_now, om * 0.75), 0.05, 0.40)

    scenarios = {
        "bear": {"g0": _clamp(min(g_actual, cap) * 0.6, -0.05, cap), "m": m_mature * 0.75, "r": 0.11},
        "base": {"g0": _clamp(min(g_actual, cap), -0.05, cap), "m": m_mature, "r": 0.10},
        "bull": {"g0": _clamp(min(g_actual, cap * 1.4), -0.05, cap * 1.4), "m": min(m_mature * 1.3, 0.45), "r": 0.09},
    }
    out = {"scenarios": {}, "price": price, "net_cash": net_cash, "shares": shares, "margin_now": m_now,
           "growth_actual": g_actual, "assumptions": []}
    for name, sc in scenarios.items():
        eq, rev10 = _equity_value(rev, sc["g0"], m_now, sc["m"], sc["r"], net_cash)
        out["scenarios"][name] = {"per_share": max(eq, 0) / shares, "equity": eq, "g0": sc["g0"], "margin": sc["m"],
                                  "r": sc["r"], "rev_year10": rev10}

    # Market-implied: solve the base model for the starting growth that makes value = market cap.
    lo, hi = -0.10, 3.0
    m_impl, r_impl = scenarios["base"]["m"], scenarios["base"]["r"]
    if _equity_value(rev, hi, m_now, m_impl, r_impl, net_cash)[0] < mc:
        g_impl = None  # even absurd growth doesn't get there at these margins
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            if _equity_value(rev, mid, m_now, m_impl, r_impl, net_cash)[0] < mc:
                lo = mid
            else:
                hi = mid
        g_impl = (lo + hi) / 2
    out["implied_g0"] = g_impl
    if g_impl is not None:
        path = _growth_path(g_impl)
        prod = 1.0
        for g in path:
            prod *= 1 + g
        out["implied_cagr"] = prod ** (1 / YEARS) - 1
        out["implied_rev10"] = rev * prod
    else:
        out["implied_cagr"], out["implied_rev10"] = None, None

    base = out["scenarios"]["base"]["per_share"]
    out["gap_pct"] = (price / base - 1) * 100 if base > 0 else None
    out["verdict"] = _verdict(out)
    out["assumptions"] = [
        f"Starting sales growth {scenarios['base']['g0']*100:.0f}% (bear {scenarios['bear']['g0']*100:.0f}%, bull {scenarios['bull']['g0']*100:.0f}%), "
        f"fading to {FADE_TO*100:.0f}% by year 10. Actual growth, latest quarter vs a year earlier: {g_actual*100:.0f}%.",
        f"Cash kept per $1 of sales (after stock pay): {m_now*100:.0f}% today, rising/falling to {m_mature*100:.0f}% by year 5 "
        f"(bear {scenarios['bear']['m']*100:.0f}%, bull {scenarios['bull']['m']*100:.0f}%).",
        "Future cash discounted at 10% a year (bear 11%, bull 9%); 3% growth forever after year 10.",
        f"Net cash of ${net_cash/1e9:,.1f}B added; {shares/1e6:,.0f}M shares.",
    ]
    return out


def _verdict(v):
    gap, cagr, ga = v["gap_pct"], v.get("implied_cagr"), v["growth_actual"]
    bear, bull = v["scenarios"]["bear"]["per_share"], v["scenarios"]["bull"]["per_share"]
    price = v["price"]
    if gap is None:
        return {"label": "CAN'T ESTIMATE", "text": "The company doesn't generate enough cash yet for this method to give a meaningful value."}
    if price > bull:
        label = "MARKET MORE OPTIMISTIC THAN EVEN THE BULL CASE"
    elif price > v["scenarios"]["base"]["per_share"] * 1.15:
        label = "MARKET MORE OPTIMISTIC THAN THE DATA"
    elif price < bear:
        label = "MARKET MORE PESSIMISTIC THAN EVEN THE BEAR CASE"
    elif price < v["scenarios"]["base"]["per_share"] * 0.85:
        label = "MARKET MORE PESSIMISTIC THAN THE DATA"
    else:
        label = "MARKET PRICE MATCHES THE DATA"
    parts = []
    if cagr is not None:
        parts.append(f"Today's price only makes sense if sales grow about {cagr*100:.0f}% a year, every year, for 10 years "
                     f"(ending around ${v['implied_rev10']/1e9:,.0f}B in yearly sales).")
        if cagr >= 0.20:
            parts.append("Historically, only a few percent of companies have ever kept up 20%+ yearly growth for a full decade, "
                         "so the market is betting this is one of the rare ones.")
        elif cagr >= 0.12:
            parts.append("That's demanding but has been done by strong companies in growing markets.")
        else:
            parts.append("That's a modest bar for a company with its track record.")
        r10 = v.get("implied_rev10") or 0
        if r10 > 700e9:
            parts.append(f"Size check: ${r10/1e12:,.2f} trillion a year in sales would be more than any company in the world sells today "
                         "(the biggest are around $0.7 trillion). That's the real size of the bet.")
        elif r10 > 300e9:
            parts.append(f"Size check: ${r10/1e9:,.0f}B a year in sales would put it among the ~10 biggest companies in the world by sales.")
        if ga > cagr * 1.5:
            parts.append(f"Its latest quarter grew {ga*100:.0f}% versus a year earlier, well above that bar, which supports the bull side, as long as growth doesn't fade faster than assumed.")
    else:
        parts.append("Even extreme growth doesn't reach today's price at these margins: the market is betting margins will be far higher than today.")
    return {"label": label, "text": " ".join(parts)}
