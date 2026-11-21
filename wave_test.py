"""Elliott wave-3 entry test, rules fixed before the run.
ZigZag on closes, reversal = K_ATR * ATR(14) (ATR at the bar where the reversal is measured).
A pivot becomes known only on the bar that confirms it.
Long: confirmed L0 < H1 > L2, L2 > L0, retrace (H1-L2)/(H1-L0) in [0.382, 0.786].
Entry: stop order at H1 (fill at max(open, H1)) on a bar after L2 is confirmed, while the setup is valid
(cancelled if price closes below L2 or a new pivot replaces it).  Stop = L2, target = L2 + 1.618*(H1-L0).
Max hold 60 bars, then exit at close.  Short = mirror.  Costs: 0.1% round trip + 0.05% slippage per side.
"""
import csv, glob, os, sys, json, statistics as st
from datetime import datetime

K_ATR, ATR_N = 3.0, 14
RET_LO, RET_HI, EXT = 0.382, 0.786, 1.618
MAX_HOLD = 60
FEE_RT, SLIP = 0.001, 0.0005
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load(path):
    with open(path) as f:
        return [dict(t=r["time"], o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"]))
                for r in csv.DictReader(f)]


def resample4h(bars):
    out, cur = [], None
    for b in bars:
        hh = int(b["t"][11:13]); key = b["t"][:11] + f"{hh - hh % 4:02d}"
        if cur is None or cur["k"] != key:
            if cur: out.append(cur)
            cur = dict(k=key, t=b["t"], o=b["o"], h=b["h"], l=b["l"], c=b["c"])
        else:
            cur["h"] = max(cur["h"], b["h"]); cur["l"] = min(cur["l"], b["l"]); cur["c"] = b["c"]
    if cur: out.append(cur)
    return out


def atrs(b):
    a, trs = [None] * len(b), []
    for i in range(1, len(b)):
        trs.append(max(b[i]["h"] - b[i]["l"], abs(b[i]["h"] - b[i-1]["c"]), abs(b[i]["l"] - b[i-1]["c"])))
        if len(trs) >= ATR_N:
            a[i] = sum(trs[-ATR_N:]) / ATR_N
    return a


def run(b, sym, on_entry=None):
    """Backtest trades of `b`. on_entry(i, setup, fill) is called at every entry (fill = max(open, trigger) for a long,
    min(open, trigger) for a short, before slippage); it only observes, the rules are unchanged."""
    a = atrs(b)
    piv = []                      # confirmed pivots: (idx, price, type)
    direction, ext_i = 0, 0       # current leg: 1 up (tracking high), -1 down
    trades, setup, pos = [], None, None
    for i in range(ATR_N + 1, len(b)):
        c = b[i]["c"]
        # --- manage open position on this bar (entered on an earlier bar)
        if pos:
            s = pos["side"]; hit = None
            if s == 1:
                if b[i]["l"] <= pos["stop"]: hit = min(b[i]["o"], pos["stop"])
                elif b[i]["h"] >= pos["tp"]: hit = max(b[i]["o"], pos["tp"])
            else:
                if b[i]["h"] >= pos["stop"]: hit = max(b[i]["o"], pos["stop"])
                elif b[i]["l"] <= pos["tp"]: hit = min(b[i]["o"], pos["tp"])
            if hit is None and i - pos["i"] >= MAX_HOLD: hit = c
            if hit is not None:
                ex = hit * (1 - s * SLIP)
                r = (s * (ex - pos["entry"]) - FEE_RT * pos["entry"]) / pos["risk"]
                trades.append(dict(sym=sym, t=pos["t"], side=s, r=r))
                pos = None
        # --- pending setup: try to fill at this bar (setup was formed on an earlier bar)
        if setup and not pos:
            s, lvl = setup["side"], setup["trig"]
            if (s == 1 and c < setup["inv"] and b[i]["h"] < lvl) or (s == -1 and c > setup["inv"] and b[i]["l"] > lvl):
                setup = None
            elif (s == 1 and b[i]["h"] >= lvl) or (s == -1 and b[i]["l"] <= lvl):
                fill = (max(b[i]["o"], lvl) if s == 1 else min(b[i]["o"], lvl)) * (1 + s * SLIP)
                risk = s * (fill - setup["inv"])
                if risk > 0 and on_entry:
                    on_entry(i, dict(setup), max(b[i]["o"], lvl) if s == 1 else min(b[i]["o"], lvl))
                if risk > 0:
                    pos = dict(side=s, entry=fill, stop=setup["inv"], tp=setup["tp"], risk=risk, i=i, t=b[i]["t"])
                    # same-bar stop check (conservative): if the bar also crossed the stop after entry, stopped
                    if (s == 1 and b[i]["l"] <= pos["stop"]) or (s == -1 and b[i]["h"] >= pos["stop"]):
                        ex = pos["stop"] * (1 - s * SLIP)
                        trades.append(dict(sym=sym, t=pos["t"], side=s,
                                           r=(s * (ex - fill) - FEE_RT * fill) / risk))
                        pos = None
                setup = None
        # --- zigzag update (pivot known at bar i)
        if a[i] is None: continue
        if direction == 0:
            direction, ext_i = 1, i; continue
        thr = K_ATR * a[i]
        new = False
        if direction == 1:
            if c > b[ext_i]["c"]: ext_i = i
            elif b[ext_i]["c"] - c >= thr:
                piv.append((ext_i, b[ext_i]["c"], "H")); direction, ext_i, new = -1, i, True
        else:
            if c < b[ext_i]["c"]: ext_i = i
            elif c - b[ext_i]["c"] >= thr:
                piv.append((ext_i, b[ext_i]["c"], "L")); direction, ext_i, new = 1, i, True
        if new:
            setup = None
            if len(piv) >= 3:
                (i0, p0, t0), (i1, p1, t1), (i2, p2, t2) = piv[-3:]
                if t2 == "L" and p2 > p0 and p1 > p0:
                    ret = (p1 - p2) / (p1 - p0)
                    if RET_LO <= ret <= RET_HI:
                        setup = dict(side=1, trig=p1, inv=p2, tp=p2 + EXT * (p1 - p0), ret=ret)
                if t2 == "H" and p2 < p0 and p1 < p0:
                    ret = (p2 - p1) / (p0 - p1)
                    if RET_LO <= ret <= RET_HI:
                        setup = dict(side=-1, trig=p1, inv=p2, tp=p2 - EXT * (p0 - p1), ret=ret)
    return trades


def summ(tr):
    if not tr: return "n=0"
    rs = [x["r"] for x in tr]
    return f"n={len(rs):4d}  avg={st.mean(rs):+.3f}R  win={100*sum(r>0 for r in rs)/len(rs):4.1f}%  total={sum(rs):+7.1f}R"


def report(name, tr, cut="2024-11-15"):
    print(f"\n=== {name} ===")
    print(" all        ", summ(tr))
    old, new = [x for x in tr if x["t"] < cut], [x for x in tr if x["t"] >= cut]
    print(" before 2y  ", summ(old))
    print(" last 2y    ", summ(new))
    print("   y1 24/11-25/11", summ([x for x in new if x["t"] < "2025-11-15"]))
    print("   y2 25/11-26/11", summ([x for x in new if x["t"] >= "2025-11-15"]))
    print("   long     ", summ([x for x in new if x["side"] == 1]))
    print("   short    ", summ([x for x in new if x["side"] == -1]))
    by = {}
    for x in new: by[x["sym"]] = by.get(x["sym"], 0) + x["r"]
    top = sorted(by, key=lambda s: -by[s])[:3]
    print("   minus top3", top, summ([x for x in new if x["sym"] not in top]))
    return new


if __name__ == "__main__":
    daily = []
    for p in sorted(glob.glob(f"{D}/*_1d_all.csv")):
        sym = os.path.basename(p).split("_")[0]
        if sym == "paxg": continue
        daily += run(load(p), sym)
    report("DAILY, 75 coins", daily)
    h1, h4 = [], []
    for sym in ("btc", "eth", "bnb", "sol", "xrp"):
        b = load(f"{D}/{sym}_1h_3y.csv")
        h1 += run(b, sym); h4 += run(resample4h(b), sym)
    report("1H, 5 coins (3y)", h1)
    report("4H, 5 coins (3y)", h4)
