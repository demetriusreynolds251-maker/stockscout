"""
scout_funnel.py — finds NEW stock ideas, scores them, posts the best few.

    Step 1  FIND     supplier chains (from funnel.yaml anchors) + market screens
    Step 2  SCORE    every candidate through the same analysis engine as a report
    Step 3  RANK     best business, sensible price, fewest red flags
    Step 4  POST     top N as idea cards (you decide what goes on the watchlist)

Usage:
  python3 scout_funnel.py              run and print
  python3 scout_funnel.py --post       run and post to Discord (#ideas via webhook/bot)
  python3 scout_funnel.py --refresh    re-run the supplier hunts even if this week's are cached
"""
import datetime as dt
import glob
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scout_data, scout_analysis, scout_render  # noqa: E402
from scout_analysis import money  # noqa: E402

DATA = os.path.join(HERE, "data")
US_EXCHANGES = ["NMS", "NYQ", "NGM", "NCM", "ASE", "NAS"]


def load_funnel_cfg():
    with open(os.path.join(HERE, "funnel.yaml")) as f:
        return yaml.safe_load(f)


def load_watchlist():
    p = os.path.join(HERE, "watchlist.yaml")
    with open(p) as f:
        return (yaml.safe_load(f) or {}).get("watchlist", []) or []


# ---------------------------------------------------------------- step 1: find
def supplier_candidates(anchors, refresh=False, log=print):
    """{ticker: reason}. Uses this week's cached supplier hunt per anchor; re-runs if older than 7 days."""
    import scout_suppliers
    out = {}
    for a in anchors:
        name, tk = a["name"], a.get("ticker")
        files = sorted(glob.glob(os.path.join(DATA, f"suppliers_{name.upper()}_*.json")))
        rows = None
        if files and not refresh:
            age = (dt.date.today() - dt.date.fromisoformat(files[-1][-15:-5])).days
            if age <= 7:
                rows = json.load(open(files[-1]))
        if rows is None:
            log(f"  supplier hunt: {name} (reading filings, can take a few minutes)")
            try:
                rows, _ = scout_suppliers.run(name, tk, max_companies=25, with_context=True)
            except Exception as e:
                log(f"  supplier hunt for {name} failed: {type(e).__name__}: {e}")
                rows = []
        for r in rows:
            if r.get("relation") == "CUSTOMER" and r.get("ticker"):
                out.setdefault(r["ticker"].upper(), []).append(f"names {name} as a customer in its yearly report")
    return out


def screen_candidates(scfg, log=print):
    import yfinance as yf
    from yfinance import EquityQuery as EQ
    out = {}
    try:
        q = EQ("and", [
            EQ("gt", ["intradaymarketcap", scfg["min_market_cap"]]),
            EQ("lt", ["intradaymarketcap", scfg["max_market_cap"]]),
            EQ("gt", ["quarterlyrevenuegrowth.quarterly", scfg["min_quarterly_sales_growth"]]),
            EQ("is-in", ["exchange"] + US_EXCHANGES),
        ])
        res = yf.screen(q, sortField="quarterlyrevenuegrowth.quarterly", sortAsc=False, size=50)
        for x in res.get("quotes", []):
            out.setdefault(x["symbol"], []).append(f"passed the growth screen (sales up {scfg['min_quarterly_sales_growth']}%+, ${scfg['min_market_cap']/1e9:.0f}–{scfg['max_market_cap']/1e9:.0f}B size)")
    except Exception as e:
        log(f"  growth screen failed: {type(e).__name__}: {e}")
    labels = {"growth_technology_stocks": "on Yahoo's growth-tech list", "undervalued_growth_stocks": "on Yahoo's undervalued-growth list",
              "aggressive_small_caps": "on Yahoo's aggressive small-caps list"}
    for name in scfg.get("also_use_yahoo_lists", []):
        try:
            res = yf.screen(name, count=25)
            for x in res.get("quotes", []):
                if x.get("exchange") in US_EXCHANGES:
                    out.setdefault(x["symbol"], []).append(labels.get(name, name))
        except Exception as e:
            log(f"  list {name} failed: {type(e).__name__}: {e}")
    return out


# ---------------------------------------------------------------- step 2+3: score and rank
PRICE_POINTS = {"Reasonable": 2, "Fair if growth holds": 1, "Expensive": -1.5}


def score(s, an, reasons):
    pts = an.get("business_score", 0) + PRICE_POINTS.get(an["price_view"], 0)
    pts -= 0.5 * sum(1 for f in an["findings"] if f["rating"] == "CONCERN")
    if any("customer" in r for r in reasons):
        pts += 1          # a documented link to a big buyer is real evidence of demand
    if len(reasons) > 1:
        pts += 0.5        # found by more than one route
    return round(pts, 2)


def run(refresh=False, log=print):
    cfg = load_funnel_cfg()
    watch = {w["ticker"].upper() for w in load_watchlist()}
    anchors = {a.get("ticker", "").upper() for a in cfg.get("anchors", [])}
    log("Step 1: finding candidates")
    cands = {}
    for src in (supplier_candidates(cfg.get("anchors", []), refresh, log), screen_candidates(cfg["screen"], log)):
        for tk, rs in src.items():
            cands.setdefault(tk, []).extend(rs)
    cands = {t: r for t, r in cands.items() if t not in watch and t not in anchors}
    # supplier-linked first, then the rest, capped
    order = sorted(cands, key=lambda t: (not any("customer" in r for r in cands[t]), -len(cands[t])))
    order = order[: cfg.get("max_candidates_scored", 60)]
    log(f"Step 2: scoring {len(order)} candidates (found {len(cands)})")
    scored, skipped = [], 0
    lo, hi = cfg["screen"]["min_market_cap"] * 0.5, cfg["screen"]["max_market_cap"] * 1.5
    for tk in order:
        try:
            s = scout_data.get_snapshot(tk, news_items=3)
        except Exception:
            skipped += 1; continue
        mc = s.get("market_cap")
        if not mc or not (lo <= mc <= hi) or not s.get("price"):
            skipped += 1; continue
        an = scout_analysis.analyze(s)
        scored.append({"snap": s, "analysis": an, "reasons": cands[tk], "score": score(s, an, cands[tk])})
    scored.sort(key=lambda x: -x["score"])
    top = scored[: cfg.get("top_n", 5)]
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, f"ideas_{dt.date.today().isoformat()}.json"), "w") as f:
        json.dump([{"ticker": x["snap"]["ticker"], "score": x["score"], "reasons": x["reasons"],
                    "business": x["analysis"]["business_view"], "price": x["analysis"]["price_view"]} for x in scored], f, indent=1)
    log(f"Step 3: ranked {len(scored)} (skipped {skipped} outside size range or missing data)")
    return top, {"found": len(cands), "scored": len(scored), "skipped": skipped}


# ---------------------------------------------------------------- step 4: cards
def idea_embeds(top, stats):
    today = dt.date.today().strftime("%B %d, %Y")
    head = {
        "color": scout_render.NAVY,
        "title": "💡 New ideas from the funnel",
        "description": (f"{today}\n\n"
                        f"🔎 Found **{stats['found']}** candidates → scored **{stats['scored']}** → showing the top **{len(top)}**.\n\n"
                        "These are companies worth **understanding**, not tips. Each card says how it was found, "
                        "what's good, and the biggest risk.\n\n"
                        "👉 Type the ticker in **#lookup** for the full report · `!add TICKER` to track it daily"),
    }
    cards = [head]
    for i, x in enumerate(top, 1):
        s, an = x["snap"], x["analysis"]
        good = next((f["claim"] for f in an["findings"] if f["rating"] == "STRENGTH"), None)
        risk = next((f["claim"] for f in an["findings"] if f["rating"] == "CONCERN"), None)
        name = (s.get("name") or s["ticker"])
        lines = [
            f"🧭 **Found because:** {'; '.join(dict.fromkeys(x['reasons']))}",
            f"{scout_render.BIZ_ICON.get(an['business_view'], '🏢')} **Business:** {an['business_view']}   "
            f"{scout_render.PRICE_ICON.get(an['price_view'], '🏷️')} **Price:** {an['price_view']}",
            scout_render.scoreboard(s, short=True),
        ]
        if s.get("summary"):
            lines.insert(0, f"🏭 {scout_render._trim(s['summary'], 240)}")
        if good:
            lines.append(f"✅ **Best point:** {good}")
        if risk:
            lines.append(f"⚠️ **Biggest risk:** {risk}")
        lines.append(f"🏢 {money(s.get('market_cap'))} company · 📅 earnings {scout_render._earnings_txt(s.get('next_earnings'))}")
        cards.append({"color": scout_render.RATING_COLOR["STRENGTH"] if x["score"] >= 2 else scout_render.RATING_COLOR["WATCH"],
                      "author": {"name": f"Idea {i} of {len(top)}  ·  funnel score {x['score']:+.1f}"},
                      "title": scout_render._trim(f"{s['ticker']}  ·  {name}", 250),
                      "description": scout_render._trim("\n".join(lines), 4000)})
    if not top:
        cards.append({"color": scout_render.SLATE, "title": "No ideas passed this time",
                      "description": "Nothing cleared the filters. That's a real result: it means the candidates were too expensive or too risky."})
    cards[-1]["footer"] = {"text": "Funnel score = business quality + price sense − red flags + bonus for a documented big customer. Research only, not advice."}
    return cards


if __name__ == "__main__":
    import argparse
    import scout_discord
    p = argparse.ArgumentParser()
    p.add_argument("--post", action="store_true")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    top, stats = run(refresh=a.refresh)
    for x in top:
        print(f"{x['snap']['ticker']:6} score {x['score']:+.1f}  {x['analysis']['business_view']:<28} {x['analysis']['price_view']:<22} {x['reasons']}")
    if a.post:
        cfg = yaml.safe_load(open(os.path.join(HERE, "config.yaml")))
        hook = scout_discord.load_webhook(os.path.join(HERE, cfg.get("ideas_webhook_file") or cfg.get("discord_webhook_file", "")))
        print(f"[posted {scout_discord.post_embeds(idea_embeds(top, stats), hook)} message(s)]")
