"""
scout_charts.py — chart images for Discord cards.

One picture per card: the last ~6 months of price (top) and volume (bottom), with
  🟢 the buy price and date (for signals)
  🔴 the sell-below line (the 35% trailing stop as it stands today)
  🟡 the stock's typical run-peak zone (from its own history)
  ⚪ its 90-day low (where a typical run is measured from)
  ❌ the exit, for closed signals
Dark background so it sits naturally inside a Discord embed.
"""
import datetime as dt
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "heat", "charts")
os.makedirs(OUT, exist_ok=True)

BG, PANEL, INK, MUTED, GRID = "#2b2d31", "#2b2d31", "#e6e7ea", "#9aa0a8", "#3a3d44"
GREEN, RED, AMBER, BLUE, UP, DOWN = "#3fb871", "#ef5b5b", "#e3a33b", "#5b9cf0", "#3fb871", "#ef5b5b"


def _history(ticker, start):
    import yfinance as yf
    h = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=True)
    h = h[["Close", "Volume"]].dropna()
    h.index = h.index.tz_localize(None) if h.index.tz is not None else h.index
    return h


def _label(ax, y, text, color, x):
    ax.annotate(text, xy=(x, y), xytext=(6, 0), textcoords="offset points", va="center", ha="left",
                fontsize=8.5, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc=BG, ec=color, lw=0.8))


def make_chart(ticker, title=None, entry=None, entry_date=None, stop=None, exit_price=None, exit_date=None, hist=None, days=180):
    """Returns a PNG path, or None if there's no data. Cached per ticker/day/inputs."""
    key = f"{ticker}_{dt.date.today()}_{entry}_{stop}_{exit_price}".replace("/", "-")
    path = os.path.join(OUT, f"{abs(hash(key)) % 10**10}_{ticker}.png")
    if os.path.exists(path):
        return path
    start = dt.date.today() - dt.timedelta(days=days)
    if entry_date:
        start = min(start, dt.date.fromisoformat(entry_date) - dt.timedelta(days=45))
    h = _history(ticker, start)
    if len(h) < 10:
        return None
    x, c, v = h.index, h.Close.values, h.Volume.values

    fig, (ax, axv) = plt.subplots(2, 1, figsize=(8, 4.6), dpi=150, sharex=True,
                                  gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.06})
    fig.patch.set_facecolor(BG)
    for a in (ax, axv):
        a.set_facecolor(PANEL)
        a.tick_params(colors=MUTED, labelsize=8)
        for s in a.spines.values():
            s.set_visible(False)
        a.grid(True, color=GRID, lw=0.6, alpha=0.8)

    lo, hi = float(np.nanmin(c)), float(np.nanmax(c))
    extras = [p for p in (entry, stop, exit_price, (hist or {}).get("typical_peak_from_low")) if p]
    lo, hi = min([lo] + extras), max([hi] + extras)
    ymin, ymax = lo * 0.88, hi * 1.12
    if hi / max(lo, 1e-9) > 4:
        ax.set_yscale("log")
    ax.set_ylim(ymin, ymax)
    nice = [b * m for m in (0.01, 0.1, 1, 10, 100) for b in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5)]
    ticks = [t for t in nice if ymin <= t <= ymax]
    while len(ticks) > 7:
        ticks = ticks[::2]
    if len(ticks) >= 3:
        ax.set_yticks(ticks)

    xr = x[-1]
    # typical run-peak zone from the stock's own history
    if hist and hist.get("typical_peak_from_low"):
        tp = hist["typical_peak_from_low"]
        ax.axhspan(tp * 0.9, tp * 1.1, color=AMBER, alpha=0.13, lw=0)
        ax.axhline(tp, color=AMBER, lw=0.9, ls=(0, (4, 3)), alpha=0.9)
        _label(ax, tp, f"typical run peak ~${tp:.2f}", AMBER, xr)
        if hist.get("low_90d"):
            ax.axhline(hist["low_90d"], color=MUTED, lw=0.8, ls=":", alpha=0.9)
            _label(ax, hist["low_90d"], f"90-day low ${hist['low_90d']:.2f}", MUTED, xr)

    ax.plot(x, c, color=INK, lw=1.6, solid_capstyle="round", zorder=3)
    ax.scatter([x[-1]], [c[-1]], s=28, color=INK, zorder=4, edgecolor=BG, lw=1.5)

    if entry:
        ed = np.datetime64(entry_date) if entry_date else x[-1]
        ax.axhline(entry, color=GREEN, lw=1.0, ls=(0, (2, 2)), alpha=0.9)
        ax.scatter([ed], [entry], s=70, color=GREEN, zorder=5, edgecolor=BG, lw=1.5, marker="^")
        _label(ax, entry, f"BUY ${entry:.2f}", GREEN, xr)
    if stop:
        ax.axhline(stop, color=RED, lw=1.3, ls=(0, (5, 2)), zorder=2)
        _label(ax, stop, f"SELL below ${stop:.2f}", RED, xr)
    if exit_price:
        xd = np.datetime64(exit_date) if exit_date else x[-1]
        ax.scatter([xd], [exit_price], s=80, color=RED, zorder=6, marker="X", edgecolor=BG, lw=1.2)
        _label(ax, exit_price, f"SOLD ${exit_price:.2f}", RED, xr)

    # volume: up days green, down days red, plus the 50-day average
    colors = [UP if i == 0 or c[i] >= c[i - 1] else DOWN for i in range(len(c))]
    width = max(0.6, (x[-1] - x[0]).days / len(x) * 0.7)
    axv.bar(x, v, color=colors, width=width, alpha=0.75, lw=0)
    if len(v) >= 50:
        ma = np.convolve(v, np.ones(50) / 50, mode="valid")
        axv.plot(x[49:], ma, color=BLUE, lw=1.0, alpha=0.9)
    axv.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda y, _: f"{y / 1e6:.0f}M" if y >= 1e6 else f"{y / 1e3:.0f}K" if y >= 1e3 else f"{y:.0f}"))
    axv.set_ylabel("volume", color=MUTED, fontsize=8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"${y:.2f}" if y < 10 else f"${y:.0f}"))
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    axv.xaxis.set_major_locator(mdates.MonthLocator())
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%b"))

    # leave room on the right for the line labels
    pad = (x[-1] - x[0]) * 0.22
    ax.set_xlim(x[0], x[-1] + pad)
    import re as _re
    clean = _re.sub(r"[^\x00-\u2FFF]", "", title or f"{ticker}  ${c[-1]:.2f}").strip()
    ax.set_title(clean, color=INK, fontsize=11, fontweight="bold", loc="left", pad=8)
    fig.text(0.99, 0.01, "StockScout · Yahoo daily data", color=MUTED, fontsize=6.5, ha="right", va="bottom")
    fig.savefig(path, facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return path
