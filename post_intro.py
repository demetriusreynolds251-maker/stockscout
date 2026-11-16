"""One-off: post the welcome cards for #movers, #learn, #options-trades, and today's first Stock of the Day."""
import json, os, requests
import scout_movers as M

TOK = open("discord_bot_token.txt").read().strip()
H = {"Authorization": f"Bot {TOK}"}
API = "https://discord.com/api/v10"
g = requests.get(f"{API}/users/@me/guilds", headers=H, timeout=30).json()[0]
owner = requests.get(f"{API}/guilds/{g['id']}", headers=H, timeout=30).json()["owner_id"]
chans = {c["name"]: c["id"] for c in requests.get(f"{API}/guilds/{g['id']}/channels", headers=H, timeout=30).json()}


def send(chan, content="", embeds=(), file=None):
    payload = {"content": content, "embeds": [{k: v for k, v in e.items() if k != "_file"} for e in embeds]}
    if file:
        r = requests.post(f"{API}/channels/{chans[chan]}/messages", headers=H, timeout=60,
                          data={"payload_json": json.dumps(payload)}, files={"files[0]": (os.path.basename(file), open(file, "rb"), "image/png")})
    else:
        r = requests.post(f"{API}/channels/{chans[chan]}/messages", headers=dict(H, **{"Content-Type": "application/json"}), timeout=60, json=payload)
    print(chan, r.status_code)


send("movers", f"<@{owner}>", [{"color": 0x975A16, "title": "⚡ Welcome to #movers",
     "description": "This channel watches your **33 movers** all day:\n"
                    "• **News, lawsuits, CEO changes**: one card per stock per batch of news (no more floods). CEO exits are always 🔴 SERIOUS now.\n"
                    "• **Unusual moves**: weekdays at 3:10 PM Central, any of the 33 that moved 2.5× its normal day.\n\n"
                    "Type `!movers` in #lookup for the list."}])
send("options-trades", "", [{"color": 0x4A5568, "title": "📘 Welcome to #options-trades",
     "description": "Weekdays at **2:40 PM Central** (20 minutes before the close) the bot scans the 33 movers for the tested dip setup "
                    "(uptrend + sharp 2-day drop: won **68%** of the time on these stocks, 2013–now).\n\n"
                    "When one hits, you get a card with the **exact Webull inputs**: expiration, which call to buy, which to sell, the limit price, "
                    "what it costs, the most you can lose and make. Then a **close card** when it's time to sell.\n\n"
                    "⚠️ Every card is **PRACTICE** for now: the option version hasn't been proven on past prices, so the bot records the real "
                    "quoted prices and keeps score. Once the record shows it makes money, we switch to real cards.\n\n"
                    "Type `!trades` in #lookup to check open practice trades and the score."}])
card = M.learn_card("MSTR", 0)
send("learn", f"<@{owner}> 🎓 Your first Stock of the Day. A new one of your 33 every weekday at 7:30 AM Central.", [card], card.get("_file"))
send("learn", "", [M.options_basics_card()])
open(os.path.join(M.DATA, "learn_n.txt"), "w").write("1")
