"""Render one sample of every card type to a text file so each can be read the way the user sees it."""
import glob, json, os, sys, traceback
OUT = open("data/card_audit.txt", "w")


def dump(label, cards):
    OUT.write(f"\n\n######## {label} ########\n")
    for c in cards if isinstance(cards, list) else [cards]:
        OUT.write(f"\n=== TITLE: {c.get('title', '')}\n")
        if c.get("author"):
            OUT.write(f"(author) {c['author'].get('name')}\n")
        OUT.write((c.get("description") or "") + "\n")
        for f in c.get("fields", []):
            OUT.write(f"[field] {f['name']}: {f['value']}\n")
        if c.get("footer"):
            OUT.write(f"(footer) {c['footer'].get('text')}\n")


def safe(label, fn):
    try:
        dump(label, fn())
    except Exception:
        OUT.write(f"\n\n######## {label} FAILED ########\n{traceback.format_exc()[-800:]}\n")


import scout_data, scout_analysis, scout_render, scout_heat, scout_plan, scout_dip, scout_movers, scout_links

# #lookup full report
def lookup():
    import stockscout_bot
    return stockscout_bot.build_report("SOFI")
safe("#lookup report (SOFI, no AI)", lookup)

# #signals
res = json.load(open(sorted(glob.glob(scout_heat.DATA + "/scan_*.json"))[-1]))
book = scout_heat._book()
safe("#signals daily (no new)", lambda: scout_heat.signal_embeds(res, [], [], [], book))
safe("#signals streak card", lambda: scout_heat.streak_card(6, scout_heat.risk_stats()))
t = scout_plan.today()
safe("#signals monthly plan ($100)", lambda: scout_plan.card(t, 100, None, monthly=True))
safe("#signals dip practice", lambda: scout_dip.cards([{"t": "QQQ", "price": 600.0, "rsi2": 6.0, "ma5": 610.0}], [], {}, 100))
# #learn
safe("#learn card (even = options lesson)", lambda: scout_movers.learn_card("SOFI", 2))
# #options-trades
e = {"t": "SOFI", "stock": 15.6, "rsi2": 7, "expiry": "2026-11-27", "buy_k": 15.5, "sell_k": 16.5, "debit": 0.4, "natural": 0.45,
     "width": 1.0, "max_loss": 40, "max_gain": 60}
safe("#options-trades entry", lambda: scout_movers.entry_card(e))
x = dict(e, reason="stock bounced above its 5-day average (the setup's exit)", exit_mid=0.62, exit_natural=0.58, stock_exit=16.2, pnl=18, date="2026-11-12")
safe("#options-trades exit", lambda: scout_movers.exit_card(x))
# #watchlist-radar
safe("#watchlist-radar", lambda: scout_heat.embeds(res, [], False))
# #ideas
try:
    import scout_funnel
    p = sorted(glob.glob(os.path.join(scout_funnel.__dict__.get("DATA", "data"), "*idea*")) + glob.glob("data/funnel*/*.json"))
    OUT.write(f"\n\n(ideas cache files: {p[-3:]})\n")
except Exception:
    pass
OUT.close()
print(open("data/card_audit.txt").read()[:200])
