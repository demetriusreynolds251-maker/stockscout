"""
scout_discord.py — posts messages to your StockScout Discord channel.

The webhook URL lives in a file (default discord_webhook.txt, chmod 600),
never in code or config. If the file is missing, posting is skipped and
the message is printed instead — so the rest of the system still works.

Discord caps a message at 2000 characters, so long reports are split.
"""
import os
import time
import requests

LIMIT = 1900  # leave headroom under Discord's 2000-char cap


def load_webhook(path):
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        url = f.read().strip()
    return url or None


def _chunks(text, limit=LIMIT):
    """Split on line breaks so we never cut a sentence in half."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > limit:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def post(text, webhook_url, dry_run=False):
    """Send text to Discord. Returns number of chunks sent (0 if skipped)."""
    if not webhook_url or dry_run:
        print("---- (not sent to Discord) ----")
        print(text)
        print("-------------------------------")
        return 0
    sent = 0
    for part in _chunks(text):
        r = requests.post(webhook_url, json={"content": part}, timeout=20)
        if r.status_code == 429:  # rate limited — wait and retry once
            time.sleep(float(r.headers.get("Retry-After", "2")))
            r = requests.post(webhook_url, json={"content": part}, timeout=20)
        r.raise_for_status()
        sent += 1
        time.sleep(0.6)
    return sent


def _embed_size(e):
    n = (len(e.get("title", "")) + len(e.get("description", "")) + len((e.get("footer") or {}).get("text", ""))
         + len((e.get("author") or {}).get("name", "")))
    for f in e.get("fields", []):
        n += len(f.get("name", "")) + len(f.get("value", ""))
    return n


def post_embeds(embeds, webhook_url, username="StockScout", fallback_text=""):
    """Send Discord cards. Packs as many as fit per message (limit: 10 cards and 6000 characters)."""
    if not webhook_url:
        print("---- (no webhook: not sent to Discord) ----")
        print(fallback_text)
        return 0
    batches, cur, size = [], [], 0
    for e in embeds:
        es = _embed_size(e)
        if cur and (len(cur) == 10 or size + es > 5800):
            batches.append(cur); cur, size = [], 0
        cur.append(e); size += es
    if cur:
        batches.append(cur)
    for b in batches:
        r = requests.post(webhook_url, json={"username": username, "embeds": b}, timeout=20)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "2")))
            r = requests.post(webhook_url, json={"username": username, "embeds": b}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"Discord rejected the message ({r.status_code}): {r.text[:300]}")
        time.sleep(0.8)
    return len(batches)
