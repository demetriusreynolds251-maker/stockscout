"""Chart-reading lessons drawn on a real stock's chart, with the numbers filled in for that stock.
Seven lessons (the ones with real evidence behind them): trend, support/resistance, volume, candles, gaps, RSI, typical move.
lesson(t, k) -> (title, text, png_path)."""
import datetime as dt
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "lessons")
os.makedirs(OUT, exist_ok=True)
BG, INK, MUTED, GRID = "#2b2d31", "#e6e7ea", "#9aa0a8", "#3a3d44"
GREEN, RED, AMBER, BLUE = "#3fb871", "#ef5b5b", "#e3a33b", "#5b9cf0"
TITLES = ["Trend & the 200-day line", "Support & resistance", "Volume", "Reading candles", "Gaps", "RSI: how stretched is it?", "Typical move: your ruler"]


def _data(t, period="2y"):
    import yfinance as yf
    h = yf.Ticker(t).history(period=period, auto_adjust=True)[["Open", "High", "Low", "Close", "Volume"]].dropna()
    h.index = h.index.tz_localize(None)
    return h


def _fig(rows=1, ratios=None, h=4.6):
    fig, axes = plt.subplots(rows, 1, figsize=(8, h), dpi=150, sharex=True,
                             gridspec_kw={"height_ratios": ratios or [1] * rows, "hspace": 0.08})
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor(BG)
    for a in axes:
        a.set_facecolor(BG); a.tick_params(colors=MUTED, labelsize=8); a.grid(True, color=GRID, lw=0.6)
        for s in a.spines.values():
            s.set_visible(False)
    return fig, axes


def _save(fig, ax, t, k, title):
    ax.set_title(title, color=INK, fontsize=11, fontweight="bold", loc="left")
    p = os.path.join(OUT, f"{t}_{k}_{dt.date.today()}.png")
    fig.savefig(p, facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return p


def _label(ax, x, y, text, color):
    ax.annotate(text, xy=(x, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc=BG, ec=color, lw=0.8))


def _rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, 1e-9))


def trend(t):
    h = _data(t); c = h.Close; ma = c.rolling(200).mean()
    v = c.iloc[-365:]; m = ma.iloc[-365:]
    fig, (ax,) = _fig()
    ax.plot(v.index, v, color=INK, lw=1.5)
    ax.plot(m.index, m, color=AMBER, lw=1.3, ls="--")
    ax.fill_between(v.index, v, m, where=v >= m, color=GREEN, alpha=0.15, lw=0)
    ax.fill_between(v.index, v, m, where=v < m, color=RED, alpha=0.15, lw=0)
    above = (c > ma)
    cross = above.ne(above.shift()) & ma.notna()
    last_cross = cross[cross].index[-1] if cross.any() else None
    _label(ax, m.index[-1], m.iloc[-1], f"200-day avg ${m.iloc[-1]:,.2f}", AMBER)
    if last_cross is not None and last_cross >= v.index[0]:
        ax.axvline(last_cross, color=MUTED, ls=":", lw=1)
    pct = (above.iloc[-252:].mean() * 100)
    state = "ABOVE" if c.iloc[-1] > ma.iloc[-1] else "BELOW"
    p = _save(fig, ax, t, 0, f"{t} · price vs its 200-day average (green = above, red = below)")
    text = (f"The **200-day average** (dashed line) is the average price of the last ~10 months. Above it = long-term **uptrend**, below = **downtrend**.\n"
            f"• {t} is **{state}** it now (${c.iloc[-1]:,.2f} vs ${ma.iloc[-1]:,.2f})" +
            (f"; it last crossed on **{last_cross.date()}** (dotted line)." if last_cross is not None else ".") +
            f"\n• It spent **{pct:.0f}%** of the last year above the line.\n"
            "• Why it matters: our dip trades only buy stocks **above** the line. Dips in uptrends bounced 68% of the time; dips in downtrends often keep falling.")
    return p, text


def support(t):
    h = _data(t, "1y"); c, hi, lo = h.Close, h.High, h.Low
    piv = [lo.iloc[i] for i in range(5, len(lo) - 5) if lo.iloc[i] == lo.iloc[i - 5:i + 6].min()] + \
          [hi.iloc[i] for i in range(5, len(hi) - 5) if hi.iloc[i] == hi.iloc[i - 5:i + 6].max()]
    price = c.iloc[-1]
    tol = c.pct_change().abs().mean() * 1.5
    levels = []
    for p0 in sorted(piv):
        touches = sum(abs(p1 / p0 - 1) < tol for p1 in piv)
        levels.append((touches, p0))
    below = sorted([x for x in levels if x[1] < price * 0.995 and x[0] >= 2], key=lambda x: (-x[0], -x[1]))
    above = sorted([x for x in levels if x[1] > price * 1.005 and x[0] >= 2], key=lambda x: (-x[0], x[1]))
    sup = below[0] if below else None
    res = above[0] if above else None
    fig, (ax,) = _fig()
    v = c.iloc[-180:]
    ax.plot(v.index, v, color=INK, lw=1.5)
    if sup:
        ax.axhline(sup[1], color=GREEN, lw=1.3, ls="--"); _label(ax, v.index[-1], sup[1], f"support ~${sup[1]:,.2f} ({sup[0]} touches)", GREEN)
    if res:
        ax.axhline(res[1], color=RED, lw=1.3, ls="--"); _label(ax, v.index[-1], res[1], f"resistance ~${res[1]:,.2f} ({res[0]} touches)", RED)
    ax.set_xlim(v.index[0], v.index[-1] + (v.index[-1] - v.index[0]) * 0.25)
    p = _save(fig, ax, t, 1, f"{t} · where buyers (green) and sellers (red) showed up before")
    text = ("**Support** = a price where the stock kept bouncing UP (buyers stepped in). **Resistance** = a price where it kept getting stuck (sellers showed up).\n" +
            (f"• Support for {t}: about **${sup[1]:,.2f}** ({(sup[1] / price - 1) * 100:+.1f}% from here), touched {sup[0]} times.\n" if sup else
             f"• No clear support below {t} right now (no price it bounced off twice in the last year). It's in open air: a sign of a weak stock.\n") +
            (f"• Resistance: about **${res[1]:,.2f}** ({(res[1] / price - 1) * 100:+.1f}% from here), touched {res[0]} times.\n" if res else
             f"• No clear resistance above: {t} is near its highs, where there are no old sellers waiting.\n") +
            "• How to use it: these are ZONES, not exact prices. A break through resistance on big volume often means a new leg up; "
            "a break below support often means more selling. For a call spread, resistance is a sensible place for the strike you SELL.")
    return p, text


def volume(t):
    h = _data(t, "1y"); c, vol = h.Close, h.Volume
    v = h.iloc[-180:]
    avg = vol.rolling(50).mean().iloc[-180:]
    top = v.Volume.nlargest(4)
    fig, (ax, axv) = _fig(2, [3, 1.3], 5)
    ax.plot(v.index, v.Close, color=INK, lw=1.4)
    up = v.Close >= v.Close.shift()
    axv.bar(v.index, v.Volume, color=np.where(up, GREEN, RED), width=0.8, alpha=0.8)
    axv.plot(avg.index, avg, color=BLUE, lw=1)
    lines = []
    for d in top.index:
        i = c.index.get_loc(d)
        mv = (c.iloc[i] / c.iloc[i - 1] - 1) * 100
        ax.scatter([d], [c.loc[d]], s=60, color=AMBER, zorder=5)
        lines.append(f"• {d.date()}: **{top[d] / avg.loc[d]:.1f}×** normal volume, stock {mv:+.1f}% that day")
    axv.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y / 1e6:.0f}M"))
    p = _save(fig, ax, t, 2, f"{t} · the 4 heaviest-volume days (orange dots)")
    text = ("**Volume** = how many shares traded. Big moves on **huge volume** are serious (big funds acting); big moves on light volume are flimsy and often fade.\n"
            + "\n".join(lines) +
            f"\n• Normal volume lately: **{vol.iloc[-50:].mean() / 1e6:,.1f}M** shares a day (blue line).\n"
            "• Check: when a stock breaks support or resistance, was volume 2×+ normal? If yes, take the break seriously.")
    return p, text


def candles(t):
    h = _data(t, "3mo").iloc[-30:]
    fig, (ax,) = _fig()
    for d, r in h.iterrows():
        col = GREEN if r.Close >= r.Open else RED
        ax.vlines(d, r.Low, r.High, color=col, lw=1)
        ax.vlines(d, min(r.Open, r.Close), max(r.Open, r.Close), color=col, lw=5)
    rng = (h.High - h.Low) / h.Close
    big = rng.idxmax(); r = h.loc[big]
    ax.annotate("biggest range day", xy=(big, r.High), xytext=(0, 14), textcoords="offset points", ha="center", color=AMBER, fontsize=8.5, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=AMBER))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    p = _save(fig, ax, t, 3, f"{t} · the last 30 days as candles")
    body = abs(r.Close - r.Open); wick_up = r.High - max(r.Open, r.Close); wick_dn = min(r.Open, r.Close) - r.Low
    shape = ("long LOWER wick: sellers pushed it down but buyers bought it back up (often a bullish sign)" if wick_dn > 2 * body and wick_dn > wick_up else
             "long UPPER wick: buyers pushed it up but sellers knocked it back down (often a bearish sign)" if wick_up > 2 * body and wick_up > wick_dn else
             "big body: one side was in control all day")
    text = ("Each **candle** is one day. The thick **body** runs from the open to the close: **green** = closed higher than it opened, **red** = lower. "
            "The thin **wicks** show the day's high and low.\n"
            f"• The biggest-range day ({big.date()}): opened ${r.Open:,.2f}, high ${r.High:,.2f}, low ${r.Low:,.2f}, closed ${r.Close:,.2f}: {shape}.\n"
            f"• Last 30 days: **{(h.Close >= h.Open).sum()} green**, **{(h.Close < h.Open).sum()} red** candles.\n"
            "• Don't over-read single candles; they matter most AT support/resistance levels.")
    return p, text


def gaps(t):
    h = _data(t, "1y"); c, o = h.Close, h.Open
    avg = c.pct_change().abs().rolling(60).mean()
    g = (o / c.shift() - 1)
    big = g[(g.abs() > 2 * avg) & (g.abs() > 0.03)].iloc[-8:]
    v = h.iloc[-180:]
    fig, (ax,) = _fig()
    ax.plot(v.index, v.Close, color=INK, lw=1.4)
    lines = []
    for d, gv in big.items():
        if d < v.index[0]:
            continue
        i = c.index.get_loc(d)
        ax.annotate("", xy=(d, o.iloc[i]), xytext=(d, c.iloc[i - 1]), arrowprops=dict(arrowstyle="->", color=GREEN if gv > 0 else RED, lw=2))
        after = (c.iloc[min(i + 5, len(c) - 1)] / o.iloc[i] - 1) * 100
        filled = (h.Low.iloc[i:i + 10].min() <= c.iloc[i - 1]) if gv > 0 else (h.High.iloc[i:i + 10].max() >= c.iloc[i - 1])
        lines.append(f"• {d.date()}: gapped **{gv * 100:+.1f}%** → next 5 days {after:+.1f}% · gap {'filled' if filled else 'NOT filled'} within 2 weeks")
    p = _save(fig, ax, t, 4, f"{t} · gaps: arrows from yesterday's close to today's open")
    text = ("A **gap** is when a stock opens far from yesterday's close, usually because of news overnight (earnings, deals, scandals). "
            "You can't trade the gap itself; you trade what happens NEXT.\n" + ("\n".join(lines[-5:]) if lines else "• No big gaps in the last 6 months.") +
            "\n• 'Filled' = the price went back to where it was before the gap. Gaps on big news with heavy volume fill less often. "
            "Our earnings signal is a gap rule: CEO upbeat but stock gaps DOWN 3%+ → it tended to keep lagging.")
    return p, text


def rsi(t):
    h = _data(t, "1y"); c = h.Close; r2, r14 = _rsi(c, 2), _rsi(c, 14); ma = c.rolling(200).mean()
    v = c.iloc[-180:]
    fig, (ax, ar) = _fig(2, [3, 1.5], 5)
    ax.plot(v.index, v, color=INK, lw=1.4)
    sig = [d for d in v.index if r2.loc[d] < 10 and c.loc[d] > (ma.loc[d] if not np.isnan(ma.loc[d]) else 1e18)]
    ax.scatter(sig, c.loc[sig], s=40, color=GREEN, zorder=5, marker="^")
    ar.plot(v.index, r14.loc[v.index], color=BLUE, lw=1.2, label="RSI-14")
    ar.plot(v.index, r2.loc[v.index], color=AMBER, lw=0.8, alpha=0.8, label="RSI-2")
    for y, col in ((70, RED), (30, GREEN), (10, GREEN)):
        ar.axhline(y, color=col, ls=":", lw=0.8)
    ar.set_ylim(0, 100)
    ar.legend(loc="upper left", fontsize=7, facecolor=BG, labelcolor=INK, framealpha=0.6)
    p = _save(fig, ax, t, 5, f"{t} · RSI (bottom) and our dip-buy signals (green triangles)")
    text = ("**RSI** measures how stretched a stock is after a run or a drop, from 0 to 100. Above **70** = stretched up (overbought), below **30** = stretched down (oversold).\n"
            f"• Today: RSI-14 = **{r14.iloc[-1]:.0f}** (the usual setting, blue), RSI-2 = **{r2.iloc[-1]:.0f}** (a 2-day version, orange, much jumpier).\n"
            f"• Green triangles = days our dip setup fired on {t} (RSI-2 under 10 while above the 200-day line): **{len(sig)}** in the last 6 months.\n"
            "• RSI is a 'how stretched' gauge, not a 'buy now' button. In strong downtrends it can stay low for weeks. That's why we pair it with the trend rule.")
    return p, text


def typical(t):
    h = _data(t, "1y"); c = h.Close; r = c.pct_change().dropna() * 100
    avg = r.iloc[-60:].abs().mean()
    fig, (ax,) = _fig()
    ax.hist(r.iloc[-250:], bins=40, color=BLUE, alpha=0.8)
    for x, col, lab in ((avg, GREEN, f"+{avg:.1f}% typical up day"), (-avg, RED, f"-{avg:.1f}% typical down day"), (r.iloc[-1], AMBER, f"today {r.iloc[-1]:+.1f}%")):
        ax.axvline(x, color=col, lw=1.5, ls="--")
    ax.set_xlabel("daily move %", color=MUTED)
    p = _save(fig, ax, t, 6, f"{t} · every day of the last year, by size of move")
    big = (r.iloc[-250:].abs() > 3 * avg).sum()
    text = (f"Every stock has its own **normal day**. For {t} it's about **±{avg:.1f}%** (SPY is ~0.7%). That's your ruler.\n"
            f"• Today it moved **{r.iloc[-1]:+.1f}%**, which is **{abs(r.iloc[-1]) / avg:.1f}×** a normal day.\n"
            f"• In the last year it had **{big}** days bigger than 3× normal: those are the news days.\n"
            f"• Use it everywhere: a 'big drop' for {t} is about {2 * avg:.0f}%+. Our call spreads aim for about **3 normal days** of move "
            f"({3 * avg:.0f}%), and the #movers alert fires at 2.5× normal.")
    return p, text


FUNCS = [trend, support, volume, candles, gaps, rsi, typical]


def lesson(t, k):
    k = k % len(FUNCS)
    p, text = FUNCS[k](t)
    return f"Chart lesson #{k + 1}: {TITLES[k]}", text, p
