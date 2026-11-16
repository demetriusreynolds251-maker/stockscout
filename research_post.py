"""Post a research update card to the #research channel (created if missing) using the bot token over plain HTTP.
Usage: python3 research_post.py "Title" "body text (markdown)" [color_hex] [--mention]
   or: python3 research_post.py --file body.md "Title" [color_hex] [--mention]"""
import json, os, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TOK = open(os.path.join(HERE, "discord_bot_token.txt")).read().strip()
H = {"Authorization": f"Bot {TOK}", "Content-Type": "application/json"}
API = "https://discord.com/api/v10"
CH = os.environ.get("CH", "research")
args = [a for a in sys.argv[1:] if a != "--mention"]
mention = "--mention" in sys.argv
if args and args[0] == "--file":
    body = open(args[1]).read(); title = args[2]; color = args[3] if len(args) > 3 else "1F3A5F"
else:
    title, body = args[0], args[1]; color = args[2] if len(args) > 2 else "1F3A5F"

g = requests.get(f"{API}/users/@me/guilds", headers=H, timeout=30).json()[0]
chans = requests.get(f"{API}/guilds/{g['id']}/channels", headers=H, timeout=30).json()
ch = next((c for c in chans if c["name"] == CH and c["type"] == 0), None)
if not ch:
    ch = requests.post(f"{API}/guilds/{g['id']}/channels", headers=H, timeout=30,
                       json={"name": CH, "type": 0, "topic": "🔬 Backtest results and research updates, in plain English"}).json()
owner = requests.get(f"{API}/guilds/{g['id']}", headers=H, timeout=30).json().get("owner_id")
content = f"<@{owner}>" if mention and owner else ""
# split long bodies across several cards (4,000 chars each)
chunks, cur = [], ""
for para in body.split("\n\n"):
    if len(cur) + len(para) + 2 > 3900:
        chunks.append(cur); cur = para
    else:
        cur = (cur + "\n\n" + para) if cur else para
chunks.append(cur)
for i, c in enumerate(chunks):
    emb = {"title": title if i == 0 else f"{title} (cont.)", "description": c, "color": int(color, 16), "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    r = requests.post(f"{API}/channels/{ch['id']}/messages", headers=H, timeout=30,
                      json={"content": content if i == 0 else "", "embeds": [emb]})
    r.raise_for_status()
print("posted to #" + CH)
