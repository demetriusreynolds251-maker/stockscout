"""
scout_ai.py — the written analysis (Claude Sonnet).

Input: the facts snapshot, the rule-based findings from scout_analysis, and
recent headlines. Output: a structured analysis that connects the findings,
argues both sides, rates each headline, states its confidence, and points out
anywhere the rule-based checks look wrong.

Key: anthropic_key.txt (chmod 600). No key = this step is skipped; the report
still contains every rule-based finding.
"""
import json
import os
import re

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
DAILY_MODEL = "claude-haiku-5-5"

SYSTEM = """You are an equity research analyst writing for a smart reader who is new to investing.
Your job is critical thinking, not cheerleading.

Rules:
1. Separate the BUSINESS (is it a good company?) from the STOCK (is today's price a good deal?). Say which you are talking about.
2. Connect the facts. The value is in how findings interact: e.g. fast growth matters less if the price already assumes it; profit padded by tax credits makes the P/E look cheaper than it is; stock-based pay inflates cash flow and dilutes owners. Explain the chain of logic step by step.
3. Run a fair debate. First argue as a bull analyst, then as a short seller who has done serious homework. Give each side its strongest honest case.
   News coverage leans positive (many sites profit when readers buy); short sellers rarely get headlines. Treat promotional headlines ("could soar", "best stock to buy") as near-zero evidence, and weigh the critical coverage and short-interest data seriously.
   Then act as a judge: decide which side the DATA supports more, using only measurable evidence (financial statements, valuation math, short interest, documented events). Ignore tone, hype, and fear. If both sides are right about different things (e.g. great business, too-high price), say exactly that.
4. Check the rule-based findings you are given. If a number or conclusion looks wrong, misleading, or missing context, say so in "corrections". If they look right, return an empty list.
5. Say what you do NOT know and how confident you are. Data is from a free feed and can be stale or wrong.
6. Plain English. When you must use a finance term, explain it in the same sentence. No emojis. No hype words.
7. Never tell the reader to buy, sell, or hold, and never suggest a price target.

Return ONLY a JSON object, no other text, exactly this shape:
{
 "short_version": "3-4 sentences: the business, the price, and the single most important question",
 "how_it_fits_together": "one paragraph (5-8 sentences) explaining how the key findings interact and which matter most, with the logic chain",
 "bull_case": ["3 points, each 1-2 sentences, strongest honest arguments FOR, each tied to a specific number"],
 "bear_case": ["3 points, each 1-2 sentences, the case a careful short seller would make, each tied to a specific number"],
 "short_seller_view": "2-3 sentences: what the people betting against it most likely believe, based on the short-interest data and critical coverage",
 "judge": {"leans": "BULL|BEAR|SPLIT", "strength": "Slight|Moderate|Strong", "why": "3-4 sentences: which side the measurable evidence supports and why the other side's best point does not outweigh it", "what_would_flip_it": "the specific, observable result that would prove the other side right"},
 "what_would_change_the_view": ["2-3 specific, observable things (e.g. a number in the next earnings report) that would strengthen or break the thesis"],
 "headlines": [{"n": 1, "effect": "Positive|Negative|Mixed|Not material", "reason": "one sentence on why, for THIS company's stock; say if it is promotional rather than news"}],
 "confidence": "Low|Medium|High, then one sentence on why",
 "corrections": ["anything in the rule-based findings that looks wrong or misleading, or empty list"]
}"""


def load_key(path):
    if path and os.path.exists(path):
        with open(path) as f:
            k = f.read().strip()
        return k or None
    return None


def _facts_for_prompt(s):
    keep = ["ticker", "name", "sector", "industry", "summary", "price", "day_change_pct", "high_52w", "low_52w",
            "market_cap", "beta", "pe", "forward_pe", "eps", "revenue", "revenue_growth_pct", "earnings_growth_pct",
            "net_income", "gross_margin_pct", "operating_margin_pct", "profit_margin_pct", "total_cash", "total_debt",
            "debt_to_equity", "current_ratio", "price_to_sales", "roe_pct", "short_pct_float", "institutional_pct",
            "insider_pct", "analyst_target", "target_low", "target_high", "rec_mean", "analyst_count",
            "next_earnings", "ma50", "ma200", "ttm", "quarterly_revenue", "employees",
            "shares_short", "shares_short_prior", "short_days_to_cover"]
    out = {k: s.get(k) for k in keep}
    out["legal_items"] = [{k: i.get(k) for k in ("date", "source", "title", "detail", "severity")} for i in (s.get("legal") or [])[:12]]
    return out


def _parse(text):
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


# $ per million tokens (input, output). Used to log real cost.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


def cost_of(usage):
    pi, po = PRICES.get(usage.get("model"), (2.0, 10.0))
    return (usage.get("input_tokens") or 0) * pi / 1e6 + (usage.get("output_tokens") or 0) * po / 1e6


# ---------------------------------------------------------------- cost control: cache + "did anything change?"
import datetime as _dt
import hashlib as _hl

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ai_cache")


def fingerprint(snap, analysis):
    """What would make a new analysis worth paying for: different findings, new legal items, new headlines, earnings date."""
    parts = [f["claim"] for f in analysis["findings"]]
    parts += sorted(i["id"] for i in (snap.get("legal") or []) if i.get("severity") in ("CRITICAL", "SERIOUS", "MEDIUM"))
    parts += [h.get("title", "") for h in (snap.get("news") or [])[:3]]
    parts += [h.get("title", "") for h in (snap.get("bear_news") or [])[:3]]
    parts.append(str(snap.get("next_earnings")))
    return _hl.sha256("|".join(parts).encode()).hexdigest()[:16]


def _cache_path(ticker):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{ticker.upper()}.json")


def cached(snap, analysis, mode, move_pct=5.0, max_age_days=7):
    """Return a saved analysis if it can be reused, else None.
    mode 'lookup': reuse anything from today (same-day repeat lookups are free).
    mode 'daily':  reuse unless something changed, the price moved > move_pct, or it's older than max_age_days."""
    p = _cache_path(snap["ticker"])
    if not os.path.exists(p):
        return None
    try:
        c = json.load(open(p))
    except Exception:
        return None
    age = (_dt.date.today() - _dt.date.fromisoformat(c["date"])).days
    if mode == "lookup":
        return c["ai"] if age == 0 else None
    price, old = snap.get("price"), c.get("price")
    moved = price and old and abs(price / old - 1) * 100 > move_pct
    if age <= max_age_days and not moved and c.get("fp") == fingerprint(snap, analysis):
        out = c["ai"]; out["_reused_from"] = c["date"]
        return out
    return None


def save_cache(snap, analysis, ai):
    with open(_cache_path(snap["ticker"]), "w") as f:
        json.dump({"date": _dt.date.today().isoformat(), "price": snap.get("price"), "fp": fingerprint(snap, analysis), "ai": ai}, f)


def analyze(snap, analysis, key, model=DEFAULT_MODEL, timeout=150, think=False):
    """think=False turns off the model's long internal reasoning: about half the cost, nearly the same quality."""
    if not key:
        return None
    findings = [{k: f[k] for k in ("rating", "claim", "facts", "reasoning", "counter")} for f in analysis["findings"]]
    heads = [{"n": i, "date": h.get("date"), "title": h.get("title"), "source": h.get("publisher")}
             for i, h in enumerate(snap.get("news", [])[:8], 1)]
    prompt = ("FACTS (from Yahoo Finance; dollar amounts in USD; 'ttm' = sum of last 4 quarters from the financial statements; "
              "debt_to_equity is a plain ratio):\n" + json.dumps(_facts_for_prompt(snap), default=str)
              + "\n\nRULE-BASED FINDINGS (check these):\n" + json.dumps(findings)
              + f"\n\nRULE-BASED VERDICT: business = {analysis['business_view']}; price = {analysis['price_view']}"
              + f"\n\nSCORECARD DEBATE: leans {analysis['debate']['side']} ({analysis['debate']['strength']}), "
              f"bull weight {analysis['debate']['bull_weight']} vs bear weight {analysis['debate']['bear_weight']}. Judge independently; you may disagree."
              + "\n\nGENERAL HEADLINES (rate these by n):\n" + json.dumps(heads)
              + "\n\nCRITICAL COVERAGE (searched for on purpose):\n"
              + json.dumps([{"title": h.get("title"), "source": h.get("publisher"), "date": h.get("date")} for h in snap.get("bear_news", [])[:6]]))
    r = requests.post(API_URL, timeout=timeout,
                      headers={"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"},
                      json=dict({"model": model, "max_tokens": 12000, "system": SYSTEM,
                                 "messages": [{"role": "user", "content": prompt}]},
                                **({} if think or "haiku" in model else {"thinking": {"type": "between_tools"}})))
    if r.status_code == 404 and "model" in r.text.lower():
        raise RuntimeError(f"Model '{model}' not recognized. Update ai_model_lookup or ai_model_daily in config.yaml. API said: {r.text[:200]}")
    r.raise_for_status()
    body = r.json()
    if body.get("stop_reason") == "max_tokens":
        raise RuntimeError("the analysis ran out of room before finishing (raise max_tokens in scout_ai.py)")
    out = _parse("".join(b.get("text", "") for b in body.get("content", [])))
    usage = body.get("usage", {})
    out["_usage"] = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"), "model": model,
                     "think": think}
    out["_usage"]["cost"] = round(cost_of(out["_usage"]), 4)
    # attach headline titles back
    by_n = {h["n"]: h for h in heads}
    for h in out.get("headlines", []):
        src = by_n.get(h.get("n"), {})
        h["title"], h["source"], h["date"] = src.get("title", ""), src.get("source", ""), src.get("date", "")
    return out


# Canned reply for --demo so layout can be tested without a key.
DEMO = {
    "short_version": ("SAMPLE AI TEXT. The business is growing very fast with strong margins and no debt. The stock price, though, "
                      "already assumes that pace continues for years. The single most important question is whether growth holds "
                      "up next quarter, because a richly priced stock is punished hard for any slowdown."),
    "how_it_fits_together": ("SAMPLE AI TEXT. Start with growth: sales roughly doubled, which is real. But the reverse check shows "
                             "the price needs several more years of that. Then look at profit quality: part of reported profit came "
                             "from tax credits, which makes the P/E look lower than the business alone would justify. Cash flow "
                             "looks healthy, but much of it exists because employees are paid in stock, which adds new shares. "
                             "Put together: a strong company whose stock has very little room for disappointment."),
    "bull_case": ["SAMPLE. Demand is accelerating and margins are high, which suggests real pricing power.",
                  "SAMPLE. A net cash balance sheet lets it keep investing through a downturn.",
                  "SAMPLE. It sits inside the fastest-growing part of chip spending."],
    "bear_case": ["SAMPLE. The price needs years of near-perfect execution.",
                  "SAMPLE. Some profit came from tax credits that won't repeat.",
                  "SAMPLE. Stock-based pay is large and keeps adding shares."],
    "what_would_change_the_view": ["SAMPLE. Next quarter's sales growth staying above 20% quarter-over-quarter.",
                                   "SAMPLE. Operating margin rising toward the gross margin as the company scales."],
    "headlines": [{"n": 1, "effect": "Positive", "reason": "SAMPLE. New product extends its lead in its main market."},
                  {"n": 2, "effect": "Not material", "reason": "SAMPLE. Routine planned insider sale."}],
    "short_seller_view": "SAMPLE. Short sellers likely believe the price runs years ahead of the business.",
    "judge": {"leans": "SPLIT", "strength": "Slight", "why": "SAMPLE. Bulls are right about the business, bears about the price.",
              "what_would_flip_it": "SAMPLE. Next quarter's growth and guidance."},
    "confidence": "Medium. SAMPLE: numbers are clear, but the outcome depends on next quarter's guidance.",
    "corrections": [],
}


def demo(snap):
    out = json.loads(json.dumps(DEMO))
    for h in out["headlines"]:
        src = (snap.get("news") or [{}] * 8)[h["n"] - 1] if h["n"] <= len(snap.get("news") or []) else {}
        h["title"], h["source"], h["date"] = src.get("title", ""), src.get("publisher", ""), src.get("date", "")
    return out


# ---------------------------------------------------------------- the one entry point everything uses
def _log(usage, ticker, mode, note=""):
    p = os.path.join(os.path.dirname(CACHE_DIR), "ai_usage.csv")
    new = not os.path.exists(p)
    with open(p, "a") as f:
        if new:
            f.write("time,ticker,mode,model,think,input_tokens,output_tokens,cost_usd,note\n")
        f.write(f"{_dt.datetime.now().isoformat(timespec='seconds')},{ticker},{mode},{usage.get('model','')},{usage.get('think','')},"
                f"{usage.get('input_tokens',0)},{usage.get('output_tokens',0)},{usage.get('cost',0)},{note}\n")


def get_analysis(snap, analysis, cfg, mode="lookup"):
    """mode 'lookup' (you asked) or 'daily' (automatic). Applies every cost rule; returns the analysis or None."""
    key = cfg.get("ai_key")
    if not key:
        return None
    tk = snap["ticker"]
    # Week before earnings: one deep analysis (Sonnet, thinking on), reused for the rest of that week.
    deep_days = cfg.get("ai_deep_before_earnings_days", 7)
    days_to_earn = None
    try:
        days_to_earn = (_dt.date.fromisoformat(str(snap.get("next_earnings"))[:10]) - _dt.date.today()).days
    except (TypeError, ValueError):
        pass
    earnings_week = days_to_earn is not None and 0 <= days_to_earn <= deep_days

    reuse = cached(snap, analysis, mode, cfg.get("ai_rerun_on_move_pct", 5.0))
    if reuse and mode == "lookup" and reuse.get("_usage", {}).get("model") == cfg.get("ai_model_daily", DAILY_MODEL):
        reuse = None  # you asked for it yourself: don't hand you the cheaper daily version
    if reuse and (not earnings_week or reuse.get("_usage", {}).get("think")):
        _log({"model": reuse.get("_usage", {}).get("model", "")}, tk, mode, f"reused {reuse.get('_reused_from', 'today')} ($0)")
        return reuse

    if earnings_week and cfg.get("ai_deep_before_earnings", True):
        model, think, note = cfg.get("ai_model_lookup", DEFAULT_MODEL), True, f"earnings in {days_to_earn}d: deep"
    elif mode == "daily":
        model, think, note = cfg.get("ai_model_daily", DAILY_MODEL), False, "daily"
    else:
        model, think, note = cfg.get("ai_model_lookup", DEFAULT_MODEL), False, "lookup"
    out = analyze(snap, analysis, key, model, think=think)
    save_cache(snap, analysis, out)
    _log(out["_usage"], tk, mode, note)
    return out


def spend_summary(days=30):
    p = os.path.join(os.path.dirname(CACHE_DIR), "ai_usage.csv")
    if not os.path.exists(p):
        return 0.0, 0, 0
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).isoformat()
    total, calls, reused = 0.0, 0, 0
    with open(p) as f:
        next(f, None)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 8 or parts[0] < cutoff:
                continue
            try:
                c = float(parts[7] or 0)
            except ValueError:
                continue  # old-format row
            if "reused" in line:
                reused += 1
            else:
                calls += 1; total += c
    return total, calls, reused
