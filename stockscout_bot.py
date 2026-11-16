#!/usr/bin/env python3
"""
stockscout_bot.py — the StockScout Discord bot. Separate from every other bot on this machine.

In the #lookup channel:
    ALAB  or  $ALAB          full research report
    !add ALAB                add to the daily watchlist
    !remove ALAB             take it off
    !list                    show the watchlist
    !suppliers NVIDIA NVDA   who names NVIDIA as a customer (ticker optional)
    !ideas                   run the discovery funnel now (posts to #ideas)
    !anchors                 show which companies the funnel hunts suppliers for
    !anchor add Tesla TSLA   / !anchor remove TSLA
    !help                    this list

Token: discord_bot_token.txt (chmod 600). Never in code.
On start it creates #lookup and #ideas in the server if they don't exist.
"""
import asyncio
import os
import re
import sys
import traceback

import discord
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scout_data, scout_analysis, scout_render, scout_funnel, scout_ai, scout_legal, scout_heat, scout_plan, scout_dip, scout_movers, scout_links  # noqa: E402
import datetime as _dt

# every card gets a time stamp (Discord shows it at the bottom in your own time zone)
_orig_from_dict = discord.Embed.from_dict.__func__


def _from_dict_stamped(cls, data):
    data = dict(data)
    data.setdefault("timestamp", _dt.datetime.now(_dt.timezone.utc).isoformat())
    return _orig_from_dict(cls, data)


discord.Embed.from_dict = classmethod(_from_dict_stamped)
from zoneinfo import ZoneInfo  # noqa: E402
from discord.ext import tasks  # noqa: E402

LOOKUP, IDEAS, ALERTS, SIGNALS, RADAR = "lookup", "ideas", "alerts", "signals", "watchlist-radar"
MOVERS_CH, LEARN_CH, TRADES_CH = "movers", "learn", "options-trades"
BREAKING_CH = "breaking"
CH_TOPICS = {MOVERS_CH: "⚡ Your 33 movers: news (grouped per story) and unusual moves",
             LEARN_CH: "🎓 Stock of the Day (one of your 33) + an options lesson, weekdays 7:30 AM Central",
             BREAKING_CH: "🚨 Breaking events that move money (shutdowns, hacks, war, bans, bank runs) + sudden sector moves: what, why, which stocks",
             TRADES_CH: "📘 Option trade alerts on the 33 movers: exact inputs, when to buy and sell (PRACTICE until proven)"}
SIGNALS_TOPIC = "🟢 Buy-ready stocks only (7+ signals, rising market, not already run up): when to buy, when to sell, tracked until they close"
HEAT_TIME = _dt.time(hour=17, minute=30, tzinfo=ZoneInfo("America/Chicago"))   # after the close, weekdays
PLAN_TIME = _dt.time(hour=17, minute=45, tzinfo=ZoneInfo("America/Chicago"))   # monthly SPY plan, last trading day
DIP_TIME = _dt.time(hour=14, minute=45, tzinfo=ZoneInfo("America/Chicago"))    # dip boost check, 15 min before the close
LEARN_TIME = _dt.time(hour=7, minute=30, tzinfo=ZoneInfo("America/Chicago"))
TRADE_TIME = _dt.time(hour=14, minute=40, tzinfo=ZoneInfo("America/Chicago"))
BIGMOVE_TIME = _dt.time(hour=15, minute=10, tzinfo=ZoneInfo("America/Chicago"))
PREVIEW_TIMES = [_dt.time(hour=19, minute=0, tzinfo=ZoneInfo("America/Chicago")), _dt.time(hour=7, minute=0, tzinfo=ZoneInfo("America/Chicago"))]
LEGAL_CHECK_MINUTES = 15
PING_LEVELS = ("CRITICAL", "SERIOUS")      # these @mention the server owner (phone notification)
POST_LEVELS = ("CRITICAL", "SERIOUS", "MEDIUM")
TICKER_RE = re.compile(r"^\$?([A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,2})?)$")
NAVY = scout_render.NAVY

HELP = (
    "**How to use StockScout** 📊\n"
    "• Type a ticker like `ALAB` or `$NVDA` → full research report\n"
    "• `!add ALAB` / `!remove ALAB` / `!list` → your daily watchlist\n"
    "• `!suppliers NVIDIA NVDA` → smaller companies that name NVIDIA as a customer (takes a few minutes)\n"
    "• `!ideas` → run the discovery funnel now; results go to #ideas (takes several minutes)\n"
    "• `!anchors` / `!anchor add Tesla TSLA` / `!anchor remove TSLA` → which big companies the funnel hunts suppliers for\n"
    "• `!legal ALAB` → lawsuits and red-flag filings right now\n"
    "• `!cost` → AI spending over the last 30 days\n"
    "• `!heat ALAB` → its stage and which of the 13 signals it hits (from the latest scan)\n"
    "• `!scan` → run the scan now (takes ~5–15 minutes)\n"
    "• `!movers` → your 33 movers · `!learn TSLA` → a learning card now · `!options` → options basics · `!videos` → a video for every lesson · `!chart TSLA 1` → a chart lesson (1–7) · `!trades` → check the practice option trades now\n"
    "• `!dip` → check the SPY/QQQ dip-boost signal right now (it also checks itself weekdays at 2:45 PM Central)\n"
    "• `!plan 10000` → the monthly SPY plan with exact shares for a $10,000 account (`!plan 10000 12` if you hold 12 shares now; `!plan set 10000` saves it)\n"
    "• **#watchlist-radar**: every stock's heat stage, weekdays 5:30 PM Central\n"
    "• **#signals**: buy-ready stocks only, with the plan, tracked until they sell (you get @mentioned)\n"
    "• **#alerts**: new lawsuits/red flags for watchlist stocks, checked every 30 min (serious ones @mention you)\n"
    "Research only, not investment advice."
)


# ---------------------------------------------------------------- yaml helpers
def _yload(name):
    with open(os.path.join(HERE, name)) as f:
        return yaml.safe_load(f) or {}


def _ysave(name, data, header):
    path = os.path.join(HERE, name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(header + "\n")
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


WL_HEADER = "# Stocks tracked in the daily brief. Edit here or use bot commands: !add TICKER / !remove TICKER"
FN_HEADER = "# The discovery funnel settings. Bot commands: !anchor add NAME TICKER / !anchor remove TICKER"


def _cfg():
    c = _yload("config.yaml")
    c["ai_key"] = scout_ai.load_key(os.path.join(HERE, c.get("anthropic_key_file", "anthropic_key.txt")))
    c["ai_model"] = c.get("ai_model") or scout_ai.DEFAULT_MODEL
    return c


# ---------------------------------------------------------------- blocking work (runs in a thread)
def build_report(ticker):
    s = scout_data.get_snapshot(ticker)
    if not s.get("price") or not s.get("market_cap"):
        return None
    s["legal"] = scout_legal.check(s["ticker"], s.get("name") or s["ticker"], s.get("market_cap"))
    scout_data.save_snapshot(s, os.path.join(HERE, "data"))
    an = scout_analysis.analyze(s)
    c, ai = _cfg(), None
    try:
        ai = scout_ai.get_analysis(s, an, c, "lookup")
    except Exception as e:
        print(f"AI step skipped for {ticker}: {e}")
    return scout_render.report_embeds(s, an, ai)


def build_suppliers(name, ticker):
    import scout_suppliers
    rows, _ = scout_suppliers.run(name, ticker, max_companies=15, with_context=True)
    cards = [{"color": NAVY, "title": f"🔎 Who names {name} as a customer",
              "description": "From yearly reports (10-K) filed with the SEC in the last 2 years. Smallest companies first. "
                             "🟢 = under $50B. Type any ticker here for the full report."}]
    for r in rows[:12]:
        tag = "🟢" if r.get("market_cap") and r["market_cap"] < 50e9 else "🔵"
        rel = {"CUSTOMER": "✅ names it as a CUSTOMER", "COMPETITOR": "⚔️ calls it a COMPETITOR",
               "SUPPLIER": "↩️ BUYS from it", "PARTNER": "🤝 PARTNERS with it", "MENTIONS": "📝 mentions it"}[r["relation"]]
        quote = scout_render._trim(r["sentences"][0], 300) if r.get("sentences") else ""
        cards.append({"color": scout_render.RATING_COLOR["STRENGTH"] if r["relation"] == "CUSTOMER" else scout_render.SLATE,
                      "title": scout_render._trim(f"{tag} {r['ticker']} · {r['name']}", 250),
                      "description": scout_render._trim(f"{rel} · {scout_analysis.money(r.get('market_cap'))} company\n"
                                                        + (f"> {quote}\n" if quote else "") + f"[Filing]({r['url']})", 4000)})
    return cards


# ---------------------------------------------------------------- bot
class StockScout(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.busy = asyncio.Lock()

    async def on_ready(self):
        print(f"StockScout bot online as {self.user}")
        for g in self.guilds:
            marker = os.path.join(scout_heat.DATA, "renamed_radar.txt")
            old = discord.utils.get(g.text_channels, name=SIGNALS)
            if old and not discord.utils.get(g.text_channels, name=RADAR) and not os.path.exists(marker):
                try:
                    await old.edit(name=RADAR, topic="🌡️ Watchlist Radar: every stock's heat stage, weekdays after the close")
                    open(marker, "w").write("done")
                    print(f"renamed #{SIGNALS} -> #{RADAR}")
                except discord.Forbidden:
                    print("no permission to rename channel")
            for ch in (LOOKUP, IDEAS, ALERTS, RADAR, SIGNALS, MOVERS_CH, LEARN_CH, TRADES_CH, BREAKING_CH):
                if not discord.utils.get(g.text_channels, name=ch):
                    try:
                        topic = (SIGNALS_TOPIC if ch == SIGNALS else CH_TOPICS.get(ch, "StockScout · research only, not investment advice"))
                        new = await g.create_text_channel(ch, topic=topic)
                        print(f"created #{ch} in {g.name}")
                        if ch == LOOKUP:
                            await new.send(HELP)   # only when the channel is first created, not on every restart
                    except discord.Forbidden:
                        print(f"no permission to create #{ch} in {g.name}; create it by hand")
        if not self.legal_watch.is_running():
            self.legal_watch.start()
        for g in self.guilds:
            sch = discord.utils.get(g.text_channels, name=SIGNALS)
            if sch and sch.topic != SIGNALS_TOPIC:
                try:
                    await sch.edit(topic=SIGNALS_TOPIC)
                except discord.Forbidden:
                    pass
        if not self.heat_daily.is_running():
            self.heat_daily.start()
        if not self.plan_monthly.is_running():
            self.plan_monthly.start()
        if not self.dip_daily.is_running():
            self.dip_daily.start()
        for loop in (self.learn_daily, self.trades_daily, self.bigmove_daily, self.hotname_watch, self.breaking_watch, self.money_watch, self.monday_preview, self.weekend_btc):
            if not loop.is_running():
                loop.start()
        asyncio.create_task(self.post_cached_heat())

    # --- background: lawsuits and red-flag filings for every watchlist stock
    @tasks.loop(minutes=LEGAL_CHECK_MINUTES)
    async def legal_watch(self):
        wl = _yload("watchlist.yaml").get("watchlist", []) or []
        targets = [(w["ticker"].upper(), w.get("name") or w["ticker"], ALERTS) for w in wl]
        have = {t for t, _, _ in targets}
        targets += [(t, scout_movers.MOVERS[t][0], MOVERS_CH) for t in scout_movers.ORDER if t not in have]
        for tk, name, chan in targets:
            try:
                items = await asyncio.to_thread(scout_legal.check, tk, name, None, 30, lambda *_: None)
                fresh = [i for i in await asyncio.to_thread(scout_legal.new_items, tk, items) if i["severity"] in POST_LEVELS]
            except Exception as e:
                print(f"legal watch failed for {tk}: {e}")
                continue
            if not fresh:
                await asyncio.sleep(2)
                continue
            fresh.sort(key=lambda i: scout_legal.SEV_ORDER[i["severity"]])
            top = fresh[0]["severity"]
            lines = []
            for i in fresh[:6]:
                lines.append(f"{scout_legal.SEV_ICON[i['severity']]} **{scout_render._trim(i['title'], 160)}**\n"
                             f"📅 {i['date']} · {i['source']} · {i['detail']} · [open]({i['link']})")
            lines.append("\n🤔 **Why it matters:** " + fresh[0]["plain"])
            if top in ("CRITICAL", "SERIOUS"):
                lines.append(f"👉 **What to do:** don't open new trades on **{tk}** for a day or two while the story plays out. "
                             "If you have a trade on it, the bot will tell you when to close. If a 🔗 Ripple warning follows, it shows which other stocks are affected.")
            else:
                lines.append(f"👉 **What to do:** nothing. Just be aware of it if you trade **{tk}**.")
            if len(fresh) > 6:
                lines.append(f"…and {len(fresh) - 6} more related headlines.")
            card = {"color": 0x9B2C2C if top in PING_LEVELS else 0x975A16,
                    "author": {"name": f"{scout_legal.SEV_ICON[top]} {top} · {tk} · {len(fresh)} new item{'s' if len(fresh) > 1 else ''}"},
                    "title": f"{tk} · {name}",
                    "description": scout_render._trim("\n\n".join(lines), 4000),
                    "footer": {"text": f"Type {tk} in #lookup for the full report." + ("" if fresh[0]["plain"].startswith("LEADERSHIP") else " A lawsuit is an accusation, not a verdict.")}}
            for g in self.guilds:
                ch = discord.utils.get(g.text_channels, name=chan) or discord.utils.get(g.text_channels, name=ALERTS)
                if not ch:
                    continue
                ping = f"<@{g.owner_id}> " if top in PING_LEVELS else ""
                await ch.send(content=f"{ping}📰 New for **{tk}**", embeds=[discord.Embed.from_dict(card)])
            # connect the dots: names from earlier stories, connected stocks, shared themes
            try:
                linked = []
                for i in fresh:
                    linked += scout_links.connected_names(tk, i["title"])
                    if i["severity"] in PING_LEVELS:
                        scout_links.remember(tk, i["title"])
                if top in PING_LEVELS or linked:
                    rc = await asyncio.to_thread(scout_links.ripple_card, tk, fresh[0]["title"], set(scout_movers.ORDER), linked or None, fresh[0].get("date"))
                    if rc:
                        await self._post(MOVERS_CH, [rc], ("{owner} 🧩 This story connects to an earlier one" if linked else None))
            except Exception as e:
                print("ripple failed:", e)
            await asyncio.sleep(2)

    @legal_watch.before_loop
    async def _before_legal(self):
        await self.wait_until_ready()

    # --- heat scan: weekdays after the close, posted to #signals
    async def run_heat(self, reply_to=None):
        if self.busy.locked():
            if reply_to:
                await reply_to.send("⏳ Another long job is running; try again in a few minutes.")
            return
        async with self.busy:
            try:
                res = await asyncio.to_thread(scout_heat.scan, lambda *a: print(*a, flush=True))
                def build():
                    changed, had_state = scout_heat.changes(res)
                    cards = scout_heat.embeds(res, changed, not had_state)
                    new, updates, closed, book = scout_heat.update_signals(res)
                    return cards, new, closed, scout_heat.signal_embeds(res, new, updates, closed, book)
                cards, new, closed, sig_cards = await asyncio.to_thread(build)
            except Exception as e:
                traceback.print_exc()
                if reply_to:
                    await reply_to.send(f"⚠️ Heat scan failed: `{type(e).__name__}: {str(e)[:200]}`")
                return
            self.last_heat = res
            for g in self.guilds:
                radar = discord.utils.get(g.text_channels, name=RADAR)
                if radar:
                    warn = [r["t"] for r in res["rows"] if r["stage"] == 4 and r["t"] in self._watch()]
                    if warn:
                        await radar.send(f"<@{g.owner_id}> ⚠️ top warning on your watchlist: " + ", ".join(warn))
                    await self.send_embeds(radar, cards)
                sch = discord.utils.get(g.text_channels, name=SIGNALS)
                if sch:
                    if new or closed:
                        await sch.send(f"<@{g.owner_id}> " + " · ".join(
                            [f"🟢 BUY {s['t']}" for s, _ in new] + [f"{'✅' if c['result_pct'] > 0 else '🔴'} SELL {c['t']}" for c in closed]))
                    await self.send_embeds(sch, sig_cards)
            open(os.path.join(scout_heat.DATA, "posted.txt"), "w").write(res["date"])
            if reply_to:
                await reply_to.send("✅ Scan posted in #watchlist-radar and #signals.")

    async def post_cached_heat(self):
        """Post today's scan if it was run outside the bot (e.g. the first warm-up run) and hasn't been posted yet."""
        import glob, json
        files = sorted(glob.glob(os.path.join(scout_heat.DATA, "scan_*.json")))
        if not files:
            return
        res = json.load(open(files[-1]))
        marker = os.path.join(scout_heat.DATA, "posted.txt")
        if os.path.exists(marker) and open(marker).read().strip() == res["date"]:
            return
        self.last_heat = res
        def build():
            changed = scout_heat.changes(res)[0] if not os.path.exists(os.path.join(scout_heat.DATA, "state.json")) else []
            cards = scout_heat.embeds(res, changed, True)
            new, updates, closed, book = scout_heat.update_signals(res)
            return cards, scout_heat.signal_embeds(res, new, updates, closed, book)
        cards, sig_cards = await asyncio.to_thread(build)
        for g in self.guilds:
            ch = discord.utils.get(g.text_channels, name=RADAR)
            if ch:
                await self.send_embeds(ch, cards)
            sch = discord.utils.get(g.text_channels, name=SIGNALS)
            if sch:
                await self.send_embeds(sch, sig_cards)
        open(marker, "w").write(res["date"])

    def _watch(self):
        return {w["ticker"].upper() for w in (_yload("watchlist.yaml").get("watchlist", []) or [])}

    @tasks.loop(time=HEAT_TIME)
    async def heat_daily(self):
        if _dt.datetime.now(ZoneInfo("America/Chicago")).weekday() < 5:
            await self.run_heat()

    @heat_daily.before_loop
    async def _before_heat(self):
        await self.wait_until_ready()

    # --- monthly SPY plan: last trading day of the month, after the close, @mention in #signals
    @tasks.loop(time=PLAN_TIME)
    async def plan_monthly(self):
        if not scout_plan.is_last_trading_day():
            return
        st = scout_plan.load()
        try:
            t = await asyncio.to_thread(scout_plan.today)
        except Exception as e:
            print("plan failed:", e); return
        c = scout_plan.card(t, st.get("account"), None, monthly=True)
        for g in self.guilds:
            sch = discord.utils.get(g.text_channels, name=SIGNALS)
            if sch:
                await sch.send(content=f"<@{g.owner_id}> 📅 Monthly SPY rebalance: place it tomorrow morning",
                               embeds=[discord.Embed.from_dict(c)])

    @plan_monthly.before_loop
    async def _before_plan(self):
        await self.wait_until_ready()

    # --- dip boost: weekdays 2:45pm Central, buy/sell cards in #signals before the close
    @tasks.loop(time=DIP_TIME)
    async def dip_daily(self):
        if _dt.datetime.now(ZoneInfo("America/Chicago")).weekday() >= 5:
            return
        await self.run_dip()

    async def run_dip(self, reply_to=None):
        try:
            core = await asyncio.to_thread(scout_plan.today)
            entries, exits, status = await asyncio.to_thread(scout_dip.check, core["weight"])
        except Exception as e:
            traceback.print_exc()
            if reply_to:
                await reply_to.send(f"⚠️ Dip check failed: `{type(e).__name__}: {str(e)[:200]}`")
            return
        cards = scout_dip.cards(entries, exits, status, scout_plan.load().get("account"))
        for g in self.guilds:
            sch = discord.utils.get(g.text_channels, name=SIGNALS)
            if sch and cards:
                await sch.send(f"<@{g.owner_id}> " + " · ".join([f"🟢 DIP BUY {e['t']}" for e in entries] + [f"🔴 SELL {x['t']}" for x in exits]))
                await self.send_embeds(sch, cards)
        if reply_to:
            lines = [f"**{t}** ${v['price']:.2f} · RSI-2 {v['rsi2']:.0f} (buy zone < 10) · {'above' if v['above200'] else 'BELOW'} 200-day avg"
                     + (f" · 🟢 holding a boost, day {v['holding']['days']}, {v['holding']['pct']:+.2f}%" if v.get('holding') else "")
                     for t, v in status.items()]
            await reply_to.send("📉 **Dip boost check**\n" + "\n".join(lines) + ("\n✅ New cards posted in #signals." if cards else "\nNo buy or sell right now."))

    @dip_daily.before_loop
    async def _before_dip(self):
        await self.wait_until_ready()

    # --- 33 movers: learning card (mornings), practice option trades (before close), unusual moves (after close)
    def _weekday(self):
        return _dt.datetime.now(ZoneInfo("America/Chicago")).weekday() < 5

    async def _post(self, chan, cards, content=None):
        for g in self.guilds:
            ch = discord.utils.get(g.text_channels, name=chan)
            if ch and cards:
                if content:
                    await ch.send(content.replace("{owner}", f"<@{g.owner_id}>"))
                await self.send_embeds(ch, cards)

    @tasks.loop(time=LEARN_TIME)
    async def learn_daily(self):
        if not self._weekday():
            return
        await self.run_learn()

    async def run_learn(self, ticker=None, reply_to=None):
        path = os.path.join(scout_movers.DATA, "learn_n.txt")
        n = int(open(path).read()) if os.path.exists(path) else 0
        t = ticker or scout_movers.ORDER[n % len(scout_movers.ORDER)]
        card = await asyncio.to_thread(scout_movers.learn_card, t, n)
        if reply_to:
            await self.send_embeds(reply_to, [card]); return
        await self._post(LEARN_CH, [card])
        open(path, "w").write(str(n + 1))

    @tasks.loop(time=TRADE_TIME)
    async def trades_daily(self):
        if not self._weekday():
            return
        await self.run_trades()

    async def run_trades(self, reply_to=None):
        try:
            entries, exits = await asyncio.to_thread(scout_movers.scan_trades)
        except Exception as e:
            traceback.print_exc()
            if reply_to:
                await reply_to.send(f"⚠️ Trade scan failed: `{type(e).__name__}: {str(e)[:200]}`")
            return
        cards = [scout_movers.entry_card(e) for e in entries] + [scout_movers.exit_card(x) for x in exits]
        if cards:
            await self._post(TRADES_CH, cards, "{owner} " + " · ".join([f"📘 BUY {e['t']} spread" for e in entries] + [f"📘 CLOSE {x['t']}" for x in exits]))
        if reply_to:
            b = scout_movers.load_book()
            opn = ", ".join(f"{t} ({v['date']})" for t, v in b["open"].items()) or "none"
            await reply_to.send(f"📘 Trade scan done: {len(entries)} new, {len(exits)} closed · open practice trades: {opn}\n{scout_movers.record()}")

    @tasks.loop(time=BIGMOVE_TIME)
    async def bigmove_daily(self):
        if not self._weekday():
            return
        moves = await asyncio.to_thread(scout_movers.big_moves)
        if moves:
            await self._post(MOVERS_CH, [scout_movers.big_move_card(moves)])

    @tasks.loop(minutes=60)
    async def hotname_watch(self):
        """One card per (stock, name) per 3 days, listing every new headline, instead of one card per headline."""
        import json as _j
        seen_p = os.path.join(scout_movers.DATA, "hotname_seen2.json")
        seen = _j.load(open(seen_p)) if os.path.exists(seen_p) else {}
        first_run = not os.path.exists(seen_p)
        try:
            hits = await asyncio.to_thread(scout_links.hot_name_search)
        except Exception as e:
            print("hot-name search failed:", e); return
        groups = {}
        for t, title, link, n, v, when in hits:
            groups.setdefault((t, n), {"v": v, "items": []})["items"].append((title, link, when))
        today = _dt.date.today()
        for (t, n), g in groups.items():
            key = t + "|" + n
            last = seen.get(key)
            if last and (today - _dt.date.fromisoformat(last)).days < 3:
                continue
            seen[key] = str(today)
            if first_run:
                continue   # first run only records what's already out there
            v, items = g["v"], g["items"]
            title, link, when = items[0]
            rc = await asyncio.to_thread(scout_links.ripple_card, t, title, set(scout_movers.ORDER), [(n, v)], when)
            if rc:
                heads = "\n".join(f"• [{h[:110]}]({l}) · {w or 'date unknown'}" for h, l, w in items[:3])
                more = f"\n…and {len(items) - 3} more headlines on the same story." if len(items) > 3 else ""
                rc["description"] = (f"**Headlines** ({len(items)}):\n{heads}{more}\n\n" + rc["description"])[:4000]
                rc["title"] = f"🧩 Connected story · {t} ↔ {v['from']} (through {n})"
                await self._post(MOVERS_CH, [rc], "{owner} 🧩 " + f"**{t}** showed up in news about **{n}** (first seen in a {v['from']} story)")
        _j.dump(seen, open(seen_p, "w"))

    # --- breaking events that move money, every 5 minutes, all day every day
    @tasks.loop(minutes=5)
    async def breaking_watch(self):
        import scout_breaking
        news = lambda q: scout_data._google_news("", "", 15, query=q)
        try:
            fired = await asyncio.to_thread(scout_breaking.check_news, news)
        except Exception as e:
            print("breaking watch failed:", e); return
        for ev, items, outlets, extra in fired:
            try:
                card = await asyncio.to_thread(scout_breaking.event_card, ev, items, outlets, extra)
                await self._post(BREAKING_CH, [card], "{owner} 🚨 **Breaking:** " + ev["name"])
            except Exception as e:
                print("breaking card failed:", e)

    # --- sudden money moves in sector funds and your 33, every 10 minutes while the market is open
    @tasks.loop(minutes=10)
    async def money_watch(self):
        import scout_breaking
        news = lambda q: scout_data._google_news("", "", 5, query=q)
        try:
            card = await asyncio.to_thread(scout_breaking.check_money, {t: scout_movers.MOVERS[t][0] for t in scout_movers.ORDER}, news)
        except Exception as e:
            print("money watch failed:", e); return
        if card:
            await self._post(BREAKING_CH, [card], "{owner} 💸 Money is moving")

    # --- Sunday 7 PM and Monday 7 AM: what bitcoin's weekend move says about Monday's open
    @tasks.loop(time=PREVIEW_TIMES)
    async def monday_preview(self):
        now = _dt.datetime.now(ZoneInfo("America/Chicago"))
        if not ((now.weekday() == 6 and now.hour >= 18) or (now.weekday() == 0 and now.hour < 9)):
            return
        import scout_breaking
        try:
            card = await asyncio.to_thread(scout_breaking.monday_preview, True)
        except Exception as e:
            print("monday preview failed:", e); return
        if card:
            await self._post(BREAKING_CH, card, "{owner} 🪙 Monday preview")

    # --- every hour on weekends: alert when bitcoin crosses a new 3% step since Friday's close
    @tasks.loop(minutes=60)
    async def weekend_btc(self):
        import scout_breaking
        try:
            card = await asyncio.wait_for(asyncio.to_thread(scout_breaking.weekend_check), timeout=300)
        except Exception as e:
            print("weekend btc failed:", repr(e)); return
        print("weekend btc check done:", "posted" if card else "nothing new", flush=True)
        if card:
            await self._post(BREAKING_CH, card, "{owner} 🪙 Bitcoin moved big this weekend")

    @weekend_btc.before_loop
    async def _wb(self):
        await self.wait_until_ready()

    @breaking_watch.before_loop
    async def _bw(self):
        await self.wait_until_ready()

    @money_watch.before_loop
    async def _mw(self):
        await self.wait_until_ready()

    @hotname_watch.before_loop
    async def _b0(self):
        await self.wait_until_ready()

    @learn_daily.before_loop
    async def _b1(self):
        await self.wait_until_ready()

    @trades_daily.before_loop
    async def _b2(self):
        await self.wait_until_ready()

    @bigmove_daily.before_loop
    async def _b3(self):
        await self.wait_until_ready()

    async def send_embeds(self, channel, embeds):
        """Send cards in batches (10 cards / ~5,800 characters per message). Cards with a '_file' carry a chart image."""
        def size(e):
            return (sum(len(str(v)) for v in (e.get("title", ""), e.get("description", ""), (e.get("author") or {}).get("name", ""),
                                               (e.get("footer") or {}).get("text", "")))
                    + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", [])))

        async def flush(batch):
            files = [discord.File(e["_file"], filename=os.path.basename(e["_file"])) for e in batch if e.get("_file")]
            embeds_ = [discord.Embed.from_dict({k: v for k, v in e.items() if k != "_file"}) for e in batch]
            await channel.send(embeds=embeds_, files=files)

        batch, total = [], 0
        for e in embeds:
            es = size(e)
            if batch and (len(batch) == 10 or total + es > 5800):
                await flush(batch); batch, total = [], 0
            batch.append(e); total += es
        if batch:
            await flush(batch)

    async def on_message(self, msg):
        if msg.author.bot or not isinstance(msg.channel, discord.TextChannel) or msg.channel.name != LOOKUP:
            return
        text = msg.content.strip()
        try:
            if text.lower() in ("!help", "help"):
                await msg.channel.send(HELP)
            elif text.lower() == "!list":
                await self.cmd_list(msg)
            elif text.lower().startswith("!add "):
                await self.cmd_add(msg, text[5:].strip())
            elif text.lower().startswith("!remove "):
                await self.cmd_remove(msg, text[8:].strip())
            elif text.lower().startswith("!suppliers"):
                await self.cmd_suppliers(msg, text[10:].strip())
            elif text.lower() == "!ideas":
                await self.cmd_ideas(msg)
            elif text.lower().startswith("!legal "):
                await self.cmd_legal(msg, text[7:].strip().upper().lstrip("$"))
            elif text.lower() == "!scan":
                await msg.channel.send("🌡️ Running the scan on ~1,200 stocks under $5… results post in #watchlist-radar and #signals.")
                asyncio.create_task(self.run_heat(reply_to=msg.channel))
            elif text.lower().startswith("!heat "):
                await self.cmd_heat(msg, text[6:].strip().upper().lstrip("$"))
            elif text.lower() == "!cost":
                total, calls, reused = scout_ai.spend_summary(30)
                await msg.channel.send(f"💵 **AI spend, last 30 days:** ${total:.2f} across {calls} paid analyses · {reused} reused for free")
            elif text.lower() == "!movers":
                lines = [f"**{t}** · {v[0]} · {v[1]}" for t, v in scout_movers.MOVERS.items()]
                await msg.channel.send("⚡ **Your 33 movers**\n" + "\n".join(lines))
            elif text.lower().startswith("!learn"):
                arg = text[6:].strip().upper().lstrip("$")
                if arg and arg not in scout_movers.MOVERS:
                    await msg.channel.send(f"{arg} isn't one of the 33. Type `!movers` for the list.")
                else:
                    await msg.channel.send("🎓 Building the card…")
                    await self.run_learn(ticker=arg or None, reply_to=msg.channel)
            elif text.lower().startswith("!chart"):
                parts = text[6:].strip().upper().lstrip("$").split()
                if not parts or parts[0] not in scout_movers.MOVERS:
                    await msg.channel.send("Usage: `!chart TSLA 1` (lessons 1–7: trend, support/resistance, volume, candles, gaps, RSI, typical move). Ticker must be one of your 33.")
                else:
                    k = int(parts[1]) - 1 if len(parts) > 1 and parts[1].isdigit() else 0
                    card = await asyncio.to_thread(scout_movers.chart_lesson_card, parts[0], k)
                    await self.send_embeds(msg.channel, [card])
            elif text.lower() == "!options":
                await msg.channel.send(embeds=[discord.Embed.from_dict(scout_movers.options_basics_card())])
            elif text.lower() == "!videos":
                await msg.channel.send(embeds=[discord.Embed.from_dict(scout_movers.videos_card())])
            elif text.lower() == "!trades":
                await self.run_trades(reply_to=msg.channel)
            elif text.lower() == "!dip":
                await self.run_dip(reply_to=msg.channel)
            elif text.lower().startswith("!plan"):
                await self.cmd_plan(msg, text[5:].strip())
            elif text.lower() == "!anchors":
                await self.cmd_anchors(msg)
            elif text.lower().startswith("!anchor "):
                await self.cmd_anchor(msg, text[8:].strip())
            elif TICKER_RE.match(text):
                await self.cmd_report(msg, TICKER_RE.match(text).group(1).upper())
        except Exception as e:
            traceback.print_exc()
            await msg.channel.send(f"⚠️ Something went wrong: `{type(e).__name__}: {str(e)[:200]}`")

    # --- commands
    async def cmd_plan(self, msg, arg):
        parts = arg.replace("$", "").replace(",", "").split()
        st = scout_plan.load()
        if parts and parts[0].lower() == "set" and len(parts) > 1:
            st["account"] = float(parts[1]); scout_plan.save(st)
            await msg.channel.send(f"✅ Saved: monthly plan cards will size for **${st['account']:,.0f}**.")
            return
        account = float(parts[0]) if parts else st.get("account")
        shares = int(parts[1]) if len(parts) > 1 else None
        t = await asyncio.to_thread(scout_plan.today)
        await msg.channel.send(embeds=[discord.Embed.from_dict(scout_plan.card(t, account, shares))])

    async def cmd_report(self, msg, tk):
        note = await msg.channel.send(f"🔎 Researching **{tk}**… (about a minute with the written analysis)")
        async with msg.channel.typing():
            embeds = await asyncio.to_thread(build_report, tk)
        if not embeds:
            await note.edit(content=f"❓ Couldn't find a stock with ticker **{tk}**. Check the spelling (e.g. `ALAB`, `NVDA`).")
            return
        await note.delete()
        await self.send_embeds(msg.channel, embeds)

    async def cmd_legal(self, msg, tk):
        note = await msg.channel.send(f"⚖️ Checking courts, SEC filings and legal news for **{tk}**…")
        s = await asyncio.to_thread(scout_data.get_snapshot, tk, False, 0)
        if not s.get("price"):
            await note.edit(content=f"❓ Couldn't find **{tk}**."); return
        s["legal"] = await asyncio.to_thread(scout_legal.check, tk, s.get("name") or tk, s.get("market_cap"))
        await note.delete()
        await self.send_embeds(msg.channel, [scout_render.legal_embed(s)])

    async def cmd_heat(self, msg, tk):
        res = getattr(self, "last_heat", None)
        if res is None:
            import glob, json
            files = sorted(glob.glob(os.path.join(scout_heat.DATA, "scan_*.json")))
            res = json.load(open(files[-1])) if files else None
        if res is None:
            await msg.channel.send("No heat scan yet. Type `!scan` to run one."); return
        r = scout_heat.heat_for(tk, res)
        if r is None:
            await msg.channel.send(f"**{tk}** isn't in the heat universe (US stocks under $5 with real trading volume) as of {res['date']}."); return
        await self.send_embeds(msg.channel, [await asyncio.to_thread(scout_heat.card, r, res)])

    async def cmd_list(self, msg):
        wl = _yload("watchlist.yaml").get("watchlist", []) or []
        lines = [f"• **{w['ticker']}** — {w.get('name', '')}" for w in wl] or ["(empty)"]
        await msg.channel.send("📋 **Daily watchlist**\n" + "\n".join(lines))

    async def cmd_add(self, msg, tk):
        tk = tk.upper().lstrip("$")
        data = _yload("watchlist.yaml"); wl = data.get("watchlist", []) or []
        if any(w["ticker"].upper() == tk for w in wl):
            await msg.channel.send(f"**{tk}** is already on the watchlist."); return
        s = await asyncio.to_thread(scout_data.get_snapshot, tk, False, 0)
        if not s.get("price"):
            await msg.channel.send(f"❓ Couldn't find **{tk}**."); return
        wl.append({"ticker": tk, "name": s.get("name") or tk, "why": f"Added from Discord by {msg.author.display_name}"})
        data["watchlist"] = wl
        _ysave("watchlist.yaml", data, WL_HEADER)
        await msg.channel.send(f"✅ Added **{tk}** ({s.get('name')}) to the daily watchlist. Earnings alerts are on for it too.")

    async def cmd_remove(self, msg, tk):
        tk = tk.upper().lstrip("$")
        data = _yload("watchlist.yaml"); wl = data.get("watchlist", []) or []
        new = [w for w in wl if w["ticker"].upper() != tk]
        if len(new) == len(wl):
            await msg.channel.send(f"**{tk}** isn't on the watchlist."); return
        data["watchlist"] = new
        _ysave("watchlist.yaml", data, WL_HEADER)
        await msg.channel.send(f"🗑️ Removed **{tk}** from the watchlist.")

    async def cmd_suppliers(self, msg, args):
        parts = args.split()
        if not parts:
            await msg.channel.send("Usage: `!suppliers NVIDIA NVDA` (company name as written in filings, then its ticker)"); return
        name, tk = (" ".join(parts[:-1]), parts[-1].upper()) if len(parts) > 1 and parts[-1].isupper() and len(parts[-1]) <= 5 else (args, None)
        if self.busy.locked():
            await msg.channel.send("⏳ Another long job is running; try again in a few minutes."); return
        async with self.busy:
            note = await msg.channel.send(f"🔎 Reading yearly reports that mention **{name}**… (a few minutes)")
            cards = await asyncio.to_thread(build_suppliers, name, tk)
            await note.delete()
            await self.send_embeds(msg.channel, cards)

    async def cmd_ideas(self, msg):
        if self.busy.locked():
            await msg.channel.send("⏳ Another long job is running; try again in a few minutes."); return
        async with self.busy:
            await msg.channel.send("💡 Running the discovery funnel… results will post in **#ideas** (several minutes).")
            top, stats = await asyncio.to_thread(scout_funnel.run, False, lambda *_: None)
            ch = discord.utils.get(msg.guild.text_channels, name=IDEAS) or msg.channel
            await self.send_embeds(ch, scout_funnel.idea_embeds(top, stats))
            if ch != msg.channel:
                await msg.channel.send(f"✅ Done. {len(top)} ideas posted in {ch.mention}.")

    async def cmd_anchors(self, msg):
        a = _yload("funnel.yaml").get("anchors", [])
        await msg.channel.send("⚓ **Funnel anchors** (it hunts for smaller companies that sell to these):\n"
                               + "\n".join(f"• {x['name']} ({x.get('ticker','')})" for x in a))

    async def cmd_anchor(self, msg, args):
        parts = args.split()
        data = _yload("funnel.yaml"); anchors = data.get("anchors", []) or []
        if len(parts) >= 3 and parts[0].lower() == "add":
            name, tk = " ".join(parts[1:-1]), parts[-1].upper()
            anchors.append({"name": name, "ticker": tk})
            reply = f"⚓ Added **{name} ({tk})** as an anchor. It'll be included in the next funnel run."
        elif len(parts) == 2 and parts[0].lower() == "remove":
            tk = parts[1].upper()
            anchors = [a for a in anchors if a.get("ticker", "").upper() != tk]
            reply = f"🗑️ Removed **{tk}** from the anchors."
        else:
            await msg.channel.send("Usage: `!anchor add Tesla TSLA` or `!anchor remove TSLA`"); return
        data["anchors"] = anchors
        _ysave("funnel.yaml", data, FN_HEADER)
        await msg.channel.send(reply)


def main():
    path = os.path.join(HERE, "discord_bot_token.txt")
    if not os.path.exists(path):
        sys.exit("Missing discord_bot_token.txt — see README (Discord bot setup).")
    token = open(path).read().strip()
    StockScout().run(token, log_handler=None)


if __name__ == "__main__":
    main()
