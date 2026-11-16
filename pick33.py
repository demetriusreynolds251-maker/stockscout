"""Pick 33 'movers' with good weekly options. Scores a candidate pool on:
 move  = average daily move over the last 60 trading days (bigger = more to trade)
 liq   = options liquidity: bid/ask gap of the at-the-money call (smaller = cheaper to get in/out) and open interest
 weekly= has 3+ expirations in the next 30 days (weekly options)
 cost  = price of ONE at-the-money weekly call contract (x100) and of a $1-wide... (reported, used for the 'fits a small account' tag)
Output: data/pick33.csv and a printed table."""
import datetime as dt, math, time
import numpy as np, pandas as pd, yfinance as yf

POOL = """TSLA NVDA AMD AAPL AMZN META MSFT GOOGL NFLX AVGO MU PLTR COIN MSTR HOOD SOFI SMCI ARM INTC QCOM UBER SHOP SNOW CRWD PANW
ORCL CRM ADBE BA DIS NKE BABA PDD JD NIO RIVN LCID F GM AAL CCL UAL DAL MARA RIOT CLSK IONQ RGTI QUBT SOUN BBAI RKLB ASTS OKLO SMR
CVNA AFRM UPST RDDT APP DELL VRT CEG VST GEV LLY NVO UNH XOM OXY GME AMC CHWY PYPL SQ XYZ ROKU DKNG TTD ENPH FSLR LULU TGT WMT COST
JPM BAC WFC C GS SNAP PINS ABNB DASH NU TSM ASML LRCX AMAT MRVL ON WOLF SPY QQQ IWM SMH TQQQ SOXL""".split()
today = dt.date.today()
rows = []
px = yf.download(POOL, period="6mo", auto_adjust=True, progress=False, group_by="ticker", threads=True)
for t in POOL:
    try:
        c = px[t]["Close"].dropna()
        v = px[t]["Volume"].dropna()
    except KeyError:
        continue
    if len(c) < 70:
        continue
    r = c.pct_change().dropna()
    move = r.iloc[-60:].abs().mean() * 100
    dollar_vol = (c * v).iloc[-20:].mean()
    price = float(c.iloc[-1])
    try:
        tk = yf.Ticker(t)
        exps = [e for e in tk.options if (dt.date.fromisoformat(e) - today).days <= 30]
        if not exps:
            continue
        e0 = next((e for e in exps if (dt.date.fromisoformat(e) - today).days >= 5), exps[0])
        ch = tk.option_chain(e0).calls
        ch = ch[(ch.bid > 0) & (ch.ask > 0)]
        atm = ch.iloc[(ch.strike - price).abs().argsort()[:1]]
        bid, ask = float(atm.bid.iloc[0]), float(atm.ask.iloc[0])
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        oi = int(ch.openInterest.fillna(0).sum())
        rows.append({"t": t, "price": round(price, 2), "avg_daily_move_%": round(move, 2), "dollar_vol_$M": round(dollar_vol / 1e6),
                     "weeklies_next30d": len(exps), "expiry_used": e0, "atm_call_cost_$": round(mid * 100), "atm_spread_%": round(spread_pct, 1),
                     "call_open_interest": oi})
    except Exception as ex:
        print("skip", t, str(ex)[:60])
    time.sleep(0.3)
D = pd.DataFrame(rows)
D = D[(D.weeklies_next30d >= 3) & (D["dollar_vol_$M"] >= 200)]
# score: movement (rank) + liquidity (tight spread, big open interest)
D["move_rank"] = D["avg_daily_move_%"].rank(pct=True)
D["spread_rank"] = (-D["atm_spread_%"]).rank(pct=True)
D["oi_rank"] = D["call_open_interest"].rank(pct=True)
D["score"] = 0.5 * D.move_rank + 0.3 * D.spread_rank + 0.2 * D.oi_rank
D = D.sort_values("score", ascending=False)
D.to_csv("data/pick_pool.csv", index=False)
pd.set_option("display.width", 250)
print(D.drop(columns=["move_rank", "spread_rank", "oi_rank"]).to_string(index=False))
