"""
scout_calendar.py — earnings-date alerts.

Keeps a small file (data/earnings_calendar.json) of each watched stock's
next earnings date, and tells you when one is N days away (N comes from
config: earnings_alert_days, e.g. 14, 7, 3, 1).

It also remembers which alerts it already sent, so you don't get the
same "7 days out" message twice.
"""
import json
import os
import datetime as dt


def _load(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"dates": {}, "sent": []}


def _save(path, cal):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cal, f, indent=2)


def update_calendar(snapshots, data_dir):
    """Record each stock's next earnings date. Returns the calendar dict."""
    path = os.path.join(data_dir, "earnings_calendar.json")
    cal = _load(path)
    for s in snapshots:
        if s.get("next_earnings"):
            cal["dates"][s["ticker"]] = str(s["next_earnings"])[:10]
    _save(path, cal)
    return cal


def due_alerts(data_dir, alert_days, today=None):
    """Return a list of alert strings that haven't been sent yet, and mark them sent."""
    path = os.path.join(data_dir, "earnings_calendar.json")
    cal = _load(path)
    today = today or dt.date.today()
    alerts = []
    for ticker, date_str in cal["dates"].items():
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        days_out = (d - today).days
        if days_out in alert_days:
            key = f"{ticker}|{date_str}|{days_out}"
            if key in cal["sent"]:
                continue
            cal["sent"].append(key)
            label = "TOMORROW" if days_out == 1 else f"in {days_out} days"
            alerts.append(
                f"📅 **{ticker} reports earnings {label}** ({d.strftime('%a %b %d')}). "
                f"{'Options prices are already inflated this close in.' if days_out <= 3 else 'Good time to read the latest report before the noise starts.'}"
            )
    _save(path, cal)
    return alerts


def upcoming(data_dir, within_days=45, today=None):
    """Plain list of upcoming dates, for the daily digest."""
    cal = _load(os.path.join(data_dir, "earnings_calendar.json"))
    today = today or dt.date.today()
    rows = []
    for ticker, date_str in sorted(cal["dates"].items(), key=lambda kv: kv[1]):
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        days_out = (d - today).days
        if 0 <= days_out <= within_days:
            rows.append(f"{ticker}: {d.strftime('%b %d')} ({days_out}d)")
    return rows
