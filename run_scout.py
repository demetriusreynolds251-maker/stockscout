#!/usr/bin/env python3
"""
run_scout.py — the one command you run.

  python3 run_scout.py report NVDA          full research brief for one stock
  python3 run_scout.py daily                daily brief for the watchlist + earnings alerts
  python3 run_scout.py calendar             upcoming earnings dates on file
  python3 run_scout.py glossary             every term and its meaning

  --demo   use saved sample data (no internet, canned AI text)
  --post   send to Discord
  --no-ai  skip the written analysis even if a key is present
"""
import argparse
import datetime as dt
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scout_data, scout_calendar, scout_discord, scout_analysis, scout_ai, scout_render, scout_legal  # noqa: E402


def attach_legal(s, demo):
    if demo:
        s.setdefault("legal", [])
        return s
    s["legal"] = scout_legal.check(s["ticker"], s.get("name") or s["ticker"], s.get("market_cap"))
    return s


def load_config():
    with open(os.path.join(HERE, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(HERE, cfg.get("data_dir", "data"))
    cfg["reports_dir"] = os.path.join(HERE, cfg.get("reports_dir", "reports"))
    cfg["webhook"] = scout_discord.load_webhook(os.path.join(HERE, cfg.get("discord_webhook_file", "")))
    cfg["ai_key"] = scout_ai.load_key(os.path.join(HERE, cfg.get("anthropic_key_file", "anthropic_key.txt")))
    cfg["ai_model"] = cfg.get("ai_model") or scout_ai.DEFAULT_MODEL
    wl = os.path.join(HERE, "watchlist.yaml")   # the watchlist lives in its own file so the bot can edit it
    if os.path.exists(wl):
        with open(wl) as f:
            cfg["watchlist"] = (yaml.safe_load(f) or {}).get("watchlist", []) or []
    return cfg


def run_ai(cfg, snap, analysis, demo, no_ai, mode="lookup"):
    if no_ai:
        return None
    if demo:
        return scout_ai.demo(snap)
    try:
        return scout_ai.get_analysis(snap, analysis, cfg, mode)
    except Exception as e:
        print(f"[written analysis skipped for {snap['ticker']}: {type(e).__name__}: {e}]")
        return None


def save(cfg, name, text):
    os.makedirs(cfg["reports_dir"], exist_ok=True)
    path = os.path.join(cfg["reports_dir"], f"{name}_{dt.date.today().isoformat()}.md")
    with open(path, "w") as f:
        f.write(text)
    return path


def cmd_report(cfg, ticker, demo, post, no_ai):
    snap = scout_data.get_snapshot(ticker, demo=demo, news_items=cfg.get("news_items", 8))
    attach_legal(snap, demo)
    scout_data.save_snapshot(snap, cfg["data_dir"])
    scout_calendar.update_calendar([snap], cfg["data_dir"])
    analysis = scout_analysis.analyze(snap)
    ai = run_ai(cfg, snap, analysis, demo, no_ai)
    embeds = scout_render.report_embeds(snap, analysis, ai)
    md = scout_render.report_markdown(snap, analysis, ai)
    print(md)
    print(f"\n[saved -> {save(cfg, ticker, md)}]")
    if post:
        print(f"[posted {scout_discord.post_embeds(embeds, cfg['webhook'], fallback_text=md)} message(s) to Discord]")
    return 0


def cmd_daily(cfg, demo, post, no_ai):
    items, problems, snaps = [], [], []
    use_ai = cfg.get("ai_in_daily", True) and not no_ai
    for w in cfg["watchlist"]:
        try:
            s = scout_data.get_snapshot(w["ticker"], demo=demo, news_items=cfg.get("news_items", 8))
            attach_legal(s, demo)
            scout_data.save_snapshot(s, cfg["data_dir"])
            an = scout_analysis.analyze(s)
            ai = run_ai(cfg, s, an, demo, not use_ai, mode="daily")
            items.append((s, an, ai)); snaps.append(s)
        except Exception as e:  # one bad ticker must not kill the run
            problems.append(f"{w['ticker']}: {type(e).__name__}: {e}")
    scout_calendar.update_calendar(snaps, cfg["data_dir"])
    alerts = scout_calendar.due_alerts(cfg["data_dir"], cfg.get("earnings_alert_days", [14, 7, 3, 1]))
    upcoming = scout_calendar.upcoming(cfg["data_dir"])
    embeds = scout_render.daily_embeds(items, alerts, upcoming, problems)
    md = scout_render.daily_markdown(embeds)
    print(md)
    save(cfg, "daily", md)
    if post:
        print(f"[posted {scout_discord.post_embeds(embeds, cfg['webhook'], fallback_text=md)} message(s) to Discord]")
    return 0 if not problems else 1


def cmd_calendar(cfg):
    up = scout_calendar.upcoming(cfg["data_dir"], within_days=120)
    print("\n".join(up) if up else "No earnings dates on file yet. Run `daily` or `report` first.")
    return 0


def cmd_glossary():
    with open(os.path.join(HERE, "glossary.json")) as f:
        for term, meaning in json.load(f).items():
            print(f"{term}\n    {meaning}\n")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["report", "daily", "calendar", "glossary"])
    p.add_argument("ticker", nargs="?")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--post", action="store_true")
    p.add_argument("--no-ai", action="store_true")
    a = p.parse_args()
    cfg = load_config()
    if a.command == "report":
        if not a.ticker:
            p.error("report needs a ticker, e.g. `report NVDA`")
        return cmd_report(cfg, a.ticker.upper(), a.demo, a.post, a.no_ai)
    if a.command == "daily":
        return cmd_daily(cfg, a.demo, a.post, a.no_ai)
    if a.command == "calendar":
        return cmd_calendar(cfg)
    return cmd_glossary()


if __name__ == "__main__":
    sys.exit(main())
