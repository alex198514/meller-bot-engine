"""Gerchik-style false breakout of a level, rules fixed before the run (see message to user)."""
import glob, os
from wave_test import load, resample4h, atrs, summ, report, D, FEE_RT, SLIP

FR, MIN_AGE, LOOKBACK = 5, 10, 200
STOP_PAD, MAX_RISK_ATR, TP_R, MAX_HOLD = 0.1, 1.0, 3.0, 30


def run(b, sym):
    a = atrs(b)
    highs, lows = [], []          # active levels: [price, idx]
    trades, pos, pend = [], None, None
    for i in range(len(b)):
        # fill pending entry at this bar's open
        if pend and not pos:
            s = pend["side"]; e = b[i]["o"] * (1 + s * SLIP); risk = s * (e - pend["stop"])
            if risk > 0:
                pos = dict(side=s, entry=e, stop=pend["stop"], tp=e + s * TP_R * risk, risk=risk, i=i, t=b[i]["t"])
            pend = None
        if pos:
            s, hit = pos["side"], None
            if s == 1:
                if b[i]["l"] <= pos["stop"]: hit = min(b[i]["o"], pos["stop"])
                elif b[i]["h"] >= pos["tp"]: hit = max(b[i]["o"], pos["tp"])
            else:
                if b[i]["h"] >= pos["stop"]: hit = max(b[i]["o"], pos["stop"])
                elif b[i]["l"] <= pos["tp"]: hit = min(b[i]["o"], pos["tp"])
            if hit is None and i - pos["i"] >= MAX_HOLD: hit = b[i]["c"]
            if hit is not None:
                ex = hit * (1 - s * SLIP)
                trades.append(dict(sym=sym, t=pos["t"], side=s, r=(s * (ex - pos["entry"]) - FEE_RT * pos["entry"]) / pos["risk"]))
                pos = None
        # new fractal confirmed at i (pivot at j = i - FR)
        j = i - FR
        if j >= FR:
            win = b[j - FR:j + FR + 1]
            if b[j]["h"] == max(x["h"] for x in win): highs.append([b[j]["h"], j])
            if b[j]["l"] == min(x["l"] for x in win): lows.append([b[j]["l"], j])
        if a[i] is None:
            continue
        c = b[i]["c"]
        sig = None
        if not pos and not pend:
            for lv, j in highs:
                if i - j >= MIN_AGE and b[i]["h"] > lv and c < lv:
                    stop = b[i]["h"] + STOP_PAD * a[i]
                    if stop - c <= MAX_RISK_ATR * a[i]: sig = dict(side=-1, stop=stop)
                    break
            if not sig:
                for lv, j in lows:
                    if i - j >= MIN_AGE and b[i]["l"] < lv and c > lv:
                        stop = b[i]["l"] - STOP_PAD * a[i]
                        if c - stop <= MAX_RISK_ATR * a[i]: sig = dict(side=1, stop=stop)
                        break
        pend = sig
        # levels die when a close goes through them, or when too old
        highs = [l for l in highs if c <= l[0] and i - l[1] <= LOOKBACK]
        lows = [l for l in lows if c >= l[0] and i - l[1] <= LOOKBACK]
    return trades


if __name__ == "__main__":
    daily = []
    for p in sorted(glob.glob(f"{D}/*_1d_all.csv")):
        s = os.path.basename(p).split("_")[0]
        if s != "paxg": daily += run(load(p), s)
    report("GERCHIK DAILY, 75 coins", daily)
    h1, h4 = [], []
    for s in ("btc", "eth", "bnb", "sol", "xrp"):
        b = load(f"{D}/{s}_1h_3y.csv"); h1 += run(b, s); h4 += run(resample4h(b), s)
    report("GERCHIK 1H, 5 coins", h1)
    report("GERCHIK 4H, 5 coins", h4)
    for y in range(2018, 2027):
        for sd, nm in ((1, "L"), (-1, "S")):
            tr = [x for x in daily if x["t"][:4] == str(y) and x["side"] == sd]
            if tr: print(y, nm, summ(tr))
