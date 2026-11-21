"""Confluence setup test (a friend's spec). Research only: nothing in the bot or the app is changed.
All parameters in config/confluence.json; candles cached in data/cf/; every candidate in data/cf/journal.csv.

Everything is evaluated at the close of a 15m candle k, with only candles closed by then (1h / 4h: closed by the
close of k). LONG described, SHORT is the mirror.

A structure  fractal swings (fractal_n candles on each side, known fractal_n candles later) on 1h and 15m.
B waves      ZigZag on 1h closes, reversal k_atr x ATR(14) (wave_test.py's zigzag: a pivot is known on the bar that
             confirms it). The wave end may be the running extreme of the current leg (known, not yet confirmed).
             impulse5 (long): 5 waves down H L H L H L ending at the latest low: wave 2 not above the start of
             wave 1, wave 3 not the shortest of 1 / 3 / 5, wave 4 not into wave 1 (wave_test.py's three rules),
             waves 3 and 5 make new lows.
             abc (long): a 5-wave impulse up (same rules) then A down, B up (below the impulse top), C down below A,
             C = the latest low.
C Fibonacci  C ends within fib lo..hi (± tol) of the impulse (0.45 .. 0.668 retracement).
D trendline  15m line through the last 2 confirmed swing highs of the final move (from the last 1h pivot before
             the low), the 2nd lower than the 1st; break = the 15m close above the line after a close at / below it.
E RSI div    RSI(14) 1h: the lowest 1h low of the final move vs the previous confirmed 1h swing low: lower price,
             RSI higher by >= min_diff.
F volume     the break candle's volume >= mult x the mean of the previous avg_n 15m candles.
G liquidity  in the last `lookback` 15m candles one went below the last confirmed 15m swing low and closed above it.
H CCI        CCI(20) 15m below -level on a candle within `around` candles of the final move's lowest 15m candle.
Signal: (impulse5 OR (abc AND fib)) AND D, plus at least min_confirmations of E F G H. 4h context (close vs
SMA50) is only written to the journal.
Trade: entry at the next 15m open; stop = the final move's lowest 15m low - 0.1 x ATR(14) 15m; TP1 1.5R (half,
then stop to breakeven), TP2 3R, exit at the close after 48 h. Stop and a target in the same candle: stop; the
candle that takes TP1 and also touches the entry: breakeven. Fee 0.06% round trip, slippage 0.05% per side.
At most one open trade per coin.
Pass (fixed in advance): >= 100 trades, avg R > +0.10, every quarter plus, plus without the 3 best coins.

v2 (config "variants.v2", same everything else): stop beyond the last confirmed 15m swing (low for a long) before
the break + 0.1 x ATR(14) 15m, skipped when the risk is above 1.5 x ATR(14) 1h; entry only with the 4h structure
(long: the last confirmed 4h swing low above the previous one; short: the last swing high below the previous one;
4h fractals with fractal_n candles on each side, known fractal_n candles later). v1 is the original run.
Output: data/cf/journal.csv + summary.json (v1), journal_v2.csv + summary_v2.json (v2).

v3 (config "variants.v3", no 4h filter): entry on the retest. After the break candle k (the close beyond the line),
within the next retest_bars 15m candles: a candle closing back beyond the line cancels the setup; the first candle
that comes back to the line (long: low <= line + retest_atr x ATR(14) 15m) and closes on the break side is the
retest; entry at the next candle's open. No retest in time: cancelled. Stop beyond the lower of (the retest
candle's low, the last confirmed 15m swing low before the break) - 0.1 x ATR 15m (short mirrored), skipped when the
risk is above 2 x ATR(14) 1h. Targets, exit, costs as in v1.

v4 / v4h (config "variants.v4", "variants.v4h", no 4h filter): the v3 setup, executed as on HashHedge. At the close
of the break candle a limit order is placed on the line (its price follows the line every candle) for limit_bars
candles; filled when price touches the line (long: low <= line; at the open if the candle opens beyond it).
Not filled in time: cancelled. The stop is set with the order: beyond the last confirmed swing before the break
+ 0.1 x ATR(14) of the entry timeframe; skipped when the planned risk (line - stop) is above 2 x ATR(14) of the
structure timeframe. The fill candle counts only for the stop (stop touched there: stopped). TP1 1.5R half
(limit), then the stop to breakeven, TP2 3R (limit). Costs: entry and targets maker 0.01%, no slippage; stop,
breakeven stop and time exit taker 0.03% + 0.05% slippage. A pending order also blocks the coin.
v4: structure 1h, entry 15m, context 4h, exit after 48 h. v4h: one step up: structure 4h (waves, Fibonacci,
RSI divergence), entry 1h (trendline, volume, liquidity, CCI, stop), context 1d (the "4h struct" split is the
1d swing structure there), exit after 96 h.

Live use (paper.py, type "friend", config "live_friend"): set_variant("v4"), live_candles() and live_scan() find
new breaks on the latest closed candles with the same run_coin() code, live_track() follows a pending order / open
trade with the same order_outcome() + simulate() code.

usage: python3 confluence_test.py [v1|v2|v3|v4|v4h]
"""
import bisect, csv, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import paper as P
from fetch_history import fetch_candles, INTERVALS_MS

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config", "confluence.json")))
DIR = os.path.join("data", "cf")
ms = lambda d: int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
iso = lambda t: datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
T0, T1 = ms(CFG["period"]["start"]), ms(CFG["period"]["end"])
FN = CFG["fractal_n"]
VARIANT = sys.argv[1] if __name__ == "__main__" and len(sys.argv) > 1 else "v1"


def set_variant(v):
    global VARIANT, VC, TF_S, TF_E, TF_C
    VARIANT, VC = v, CFG["variants"][v]
    TF_S, TF_E, TF_C = VC.get("tf_struct", "1h"), VC.get("tf_entry", "15m"), VC.get("tf_ctx", "4h")


set_variant(VARIANT)


def tf_range(role, tf):
    """(start, end) of the candles downloaded for a role (struct / entry / ctx)."""
    days = VC.get("warmup_days", {}).get(role, CFG["warmup_days"].get(tf))
    end = T1 + (VC.get("data_after_days", 3) if role == "entry" else 0) * P.DAY_MS
    return T0 - days * P.DAY_MS, end


# ---------- data ----------
def candles(sym, tf, a, b):
    """[t, o, h, l, c, v, ct, quote_vol] closed by b, cached in data/cf/."""
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f"{sym}_{tf}_{a}_{b}.json")
    if os.path.exists(path):
        return json.load(open(path))
    raw = fetch_candles(sym, a, b, tf)
    rows = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), k[6], float(k[7])]
            for k in raw if k[6] < b]
    json.dump(rows, open(path, "w"))
    return rows


def universe():
    path = os.path.join(DIR, "liquidity.json")
    if os.path.exists(path):
        return json.load(open(path))
    with ThreadPoolExecutor(4) as ex:
        vols = dict(zip(P.SCANNER_SYMBOLS, ex.map(lambda s: sum(r[7] for r in candles(s, "1d", T0, T1)),
                                                   P.SCANNER_SYMBOLS)))
    top = sorted(vols, key=lambda s: -vols[s])[:CFG["universe"]["top_n"]]
    json.dump({"top": top, "quote_volume": {s: round(vols[s]) for s in top}}, open(path, "w"), indent=1)
    return json.load(open(path))


# ---------- indicators ----------
def atr_mean(H, L, C, n):
    """wave_test.atrs: mean of the last n true ranges (None before)."""
    a, trs = [None] * len(C), []
    for i in range(1, len(C)):
        trs.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
        if len(trs) >= n:
            a[i] = sum(trs[-n:]) / n
    return a


def rsi(C, n):
    out, ag, al = [None] * len(C), 0.0, 0.0
    for i in range(1, len(C)):
        d = C[i] - C[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            ag += g / n
            al += l / n
            if i < n:
                continue
        else:
            ag = (ag * (n - 1) + g) / n
            al = (al * (n - 1) + l) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def cci(H, L, C, n):
    tp = [(h + l + c) / 3 for h, l, c in zip(H, L, C)]
    out = [None] * len(C)
    for i in range(n - 1, len(C)):
        w = tp[i - n + 1:i + 1]
        m = sum(w) / n
        md = sum(abs(x - m) for x in w) / n
        out[i] = 0.0 if md == 0 else (tp[i] - m) / (0.015 * md)
    return out


def fractals(H, L, n):
    """Swing highs / lows: index j, known at j + n (strictly beyond the n candles on each side)."""
    hi, lo = [], []
    for j in range(n, len(H) - n):
        if H[j] > max(H[j - n:j]) and H[j] > max(H[j + 1:j + n + 1]):
            hi.append(j)
        if L[j] < min(L[j - n:j]) and L[j] < min(L[j + 1:j + n + 1]):
            lo.append(j)
    return hi, lo


def zigzag(C, A, k):
    """wave_test.run's zigzag on closes. Returns pivots [(idx, price, 'H'/'L', confirmed_at)] and per bar the state
    (number of pivots known, direction, index of the running extreme)."""
    piv, state = [], [None] * len(C)
    direction, ext = 0, 0
    for i in range(CFG["zigzag"]["atr_n"] + 1, len(C)):
        c = C[i]
        if A[i] is None:
            continue
        if direction == 0:
            direction, ext = 1, i
        else:
            thr = k * A[i]
            if direction == 1:
                if c > C[ext]:
                    ext = i
                elif C[ext] - c >= thr:
                    piv.append((ext, C[ext], "H", i))
                    direction, ext = -1, i
            else:
                if c < C[ext]:
                    ext = i
                elif c - C[ext] >= thr:
                    piv.append((ext, C[ext], "L", i))
                    direction, ext = 1, i
        state[i] = (len(piv), direction, ext)
    return piv, state


# ---------- structure (B, C) ----------
def impulse_ok(v):
    """6 points v0..v5 oriented upwards (v0 low): Elliott's three rules plus new extremes for waves 3 and 5."""
    if not (v[0] < v[1] > v[2] < v[3] > v[4] < v[5]):
        return False
    w1, w3, w5 = v[1] - v[0], v[3] - v[2], v[5] - v[4]
    return v[2] > v[0] and v[4] > v[1] and v[3] > v[1] and v[5] > v[3] and not (w3 < w1 and w3 < w5)


def structure(piv, state, C1, h, side):
    """At closed 1h bar h: {"kind": "impulse5"/"abc", "fib": bool, "start": 1h idx of the final move's start,
    "end": 1h idx of the latest extreme} for `side`, or None."""
    st = state[h]
    if not st:
        return None
    n, d, ext = st
    end_type = "L" if side == "long" else "H"
    seq = [(p[0], p[1], p[2]) for p in piv[max(0, n - 10):n]]
    tent = (ext, C1[ext], "L" if d == -1 else "H")
    if tent[2] == end_type:
        seq = seq + [tent]
    if not seq or seq[-1][2] != end_type:
        return None
    s_imp = -1 if side == "long" else 1             # long: 5 waves DOWN
    if len(seq) >= 6 and impulse_ok([s_imp * x[1] for x in seq[-6:]]):
        return {"kind": "impulse5", "fib": None, "start": seq[-2][0], "end": seq[-1][0]}
    if len(seq) >= 9:
        s = -s_imp                                  # long: impulse UP, then A-B-C down
        v = [s * x[1] for x in seq[-9:]]
        if impulse_ok(v[:6]) and v[7] < v[5] and v[8] < v[6]:
            ret = (v[5] - v[8]) / (v[5] - v[0])
            f = CFG["fib"]
            return {"kind": "abc", "fib": f["lo"] - f["tol"] <= ret <= f["hi"] + f["tol"], "ret": round(ret, 3),
                    "start": seq[-2][0], "end": seq[-1][0]}
    return None


# ---------- one coin ----------
def run_coin(sym, data=None, t_from=None, t_to=None, sides=("long", "short"), busy_until=0, live=False):
    """Candidates and trades of `sym` for break candles closing in (t_from, t_to] (default: the test period).
    data = (structure, entry, context) candles, else the cached test download. live: an order still waiting or a
    trade still open at the end of the candles is "pending" / "open" instead of rejected (v4 limit entry only)."""
    # b1 / b15 / b4 = the structure / entry / context timeframe (1h / 15m / 4h unless the variant says otherwise)
    if data is None:
        b1, b15, b4 = (candles(sym, tf, *tf_range(role, tf)) for role, tf in (("struct", TF_S), ("entry", TF_E), ("ctx", TF_C)))
        if len(b1) < 300 or len(b15) < 1000:
            return [], []
    else:
        b1, b15, b4 = data
    t_from = T0 if t_from is None else t_from
    t_to = T1 if t_to is None else t_to
    T1h, O1, H1, L1, C1 = ([r[i] for r in b1] for i in range(5))
    CT1 = [r[6] + 1 for r in b1]
    T15, O, H, L, C, V = ([r[i] for r in b15] for i in range(6))
    CT15 = [r[6] + 1 for r in b15]
    CT4 = [r[6] + 1 for r in b4]
    C4 = [r[4] for r in b4]
    n4f = VC.get("fractal_4h_n", FN)
    fh4, fl4 = fractals([r[2] for r in b4], [r[3] for r in b4], n4f)
    H4, L4 = [r[2] for r in b4], [r[3] for r in b4]
    A1 = atr_mean(H1, L1, C1, CFG["zigzag"]["atr_n"])
    piv, zst = zigzag(C1, A1, CFG["zigzag"]["k_atr"])
    R1 = rsi(C1, CFG["rsi"]["n"])
    A15 = atr_mean(H, L, C, CFG["trade"]["stop_atr_n"])
    CCI = cci(H, L, C, CFG["cci"]["n"])
    fh15, fl15 = fractals(H, L, FN)
    fh1, fl1 = fractals(H1, L1, FN)
    vn, vm, lb = CFG["volume"]["avg_n"], CFG["volume"]["mult"], CFG["liquidity"]["lookback"]
    tr = CFG["trade"]
    cands, trades = [], []
    h = -1
    for k in range(max(vn, 30), len(b15) - (0 if live else 1)):    # live: the candle that has just closed too
        t = CT15[k]
        if t <= t_from or t > t_to:
            continue
        while h + 1 < len(b1) and CT1[h + 1] <= t:
            h += 1
        if h < 0:
            continue
        for side in sides:
            sg = 1 if side == "long" else -1
            st = structure(piv, zst, C1, h, side)
            if not st or not (st["kind"] == "impulse5" or st["fib"]):
                continue
            start_t = T1h[st["start"]]
            a = bisect.bisect_left(T15, start_t)
            if k - a < 2 * FN + 2:
                continue
            # D: the last 2 confirmed 15m swings of the final move (highs for a long, lows for a short)
            sw = fh15 if side == "long" else fl15
            X = H if side == "long" else L
            js = [j for j in sw[bisect.bisect_left(sw, a):bisect.bisect_right(sw, k - FN)]]
            if len(js) < 2:
                continue
            j1, j2 = js[-2], js[-1]
            if not (sg * X[j2] < sg * X[j1]):
                continue                            # not lower highs (long) / higher lows (short)
            line = lambda i: X[j1] + (X[j2] - X[j1]) * (i - j1) / (j2 - j1)
            if not (sg * C[k] > sg * line(k) and sg * C[k - 1] <= sg * line(k - 1)):
                continue
            # the final move's extreme on 15m
            seg = range(a, k + 1)
            ex = min(seg, key=lambda i: L[i]) if side == "long" else max(seg, key=lambda i: H[i])
            ex_px = L[ex] if side == "long" else H[ex]
            # E: RSI divergence on 1h
            e = False
            seg1 = range(st["start"], h + 1)
            s2 = min(seg1, key=lambda i: L1[i]) if side == "long" else max(seg1, key=lambda i: H1[i])
            sw1 = [j for j in (fl1 if side == "long" else fh1) if j < s2 and j + FN <= h]
            if sw1 and R1[s2] is not None and R1[sw1[-1]] is not None:
                s1 = sw1[-1]
                P1, P2 = (L1[s1], L1[s2]) if side == "long" else (H1[s1], H1[s2])
                e = sg * P2 < sg * P1 and sg * (R1[s2] - R1[s1]) >= CFG["rsi"]["min_diff"]
            # F: volume
            f = V[k] >= vm * sum(V[k - vn:k]) / vn
            # G: liquidity sweep of the last confirmed 15m swing (lows for a long)
            g = False
            sw_g = fl15 if side == "long" else fh15
            Y = L if side == "long" else H
            for m in range(k - lb + 1, k + 1):
                q = bisect.bisect_right(sw_g, m - 1 - FN) - 1   # last swing known before candle m
                if q >= 0:
                    lvl = Y[sw_g[q]]
                    if sg * Y[m] < sg * lvl and sg * C[m] > sg * lvl:
                        g = True
                        break
            # H: CCI around the extreme
            cc = [CCI[i] for i in range(max(0, ex - CFG["cci"]["around"]), min(k, ex + CFG["cci"]["around"]) + 1)
                  if CCI[i] is not None]
            hh = bool(cc) and (min(cc) < -CFG["cci"]["level"] if side == "long" else max(cc) > CFG["cci"]["level"])
            conf = int(e) + int(f) + int(g) + int(hh)
            # 4h context (journal only)
            q4 = bisect.bisect_right(CT4, t) - 1
            n4 = CFG["ctx4h_sma"]
            ctx = ("up" if C4[q4] > sum(C4[q4 - n4 + 1:q4 + 1]) / n4 else "down") if q4 >= n4 else ""
            entry = O[k + 1] if k + 1 < len(O) else C[k]   # (live, newest candle: the limit entry sets its own price)
            struct4 = ""                            # v2 filter: 4h swing structure
            sw4, Z4 = (fl4, L4) if side == "long" else (fh4, H4)
            known4 = sw4[:bisect.bisect_right(sw4, q4 - n4f)]
            if len(known4) >= 2:
                struct4 = "with" if sg * Z4[known4[-1]] > sg * Z4[known4[-2]] else "against"
            if VC["stop"] == "last_swing":          # v2: beyond the last confirmed 15m swing before the break
                sw_s, Ys = (fl15, L) if side == "long" else (fh15, H)
                q = bisect.bisect_right(sw_s, k - FN) - 1
                base = Ys[sw_s[q]] if q >= 0 else ex_px
            else:                                   # v1: beyond the final move's extreme
                base = ex_px
            stop = base - sg * tr["stop_atr_mult"] * (A15[k] or 0)
            risk = sg * (entry - stop)
            max_risk = VC.get("max_risk_atr1h")
            entry_k, h_risk, retest_fail, t_dec = k + 1, h, None, t
            if VC.get("entry") == "retest" and conf >= CFG["min_confirmations"]:
                rt = None
                for m in range(k + 1, min(k + VC["retest_bars"], len(b15) - 2) + 1):
                    lv = line(m)
                    if sg * C[m] <= sg * lv:
                        retest_fail = "closed back beyond the line"
                        break
                    if (L[m] <= lv + VC["retest_atr"] * A15[m]) if sg > 0 else (H[m] >= lv - VC["retest_atr"] * A15[m]):
                        rt = m
                        break
                if rt is None:
                    retest_fail = retest_fail or f"no retest within {VC['retest_bars']} candles"
                else:
                    sw_s, Ys = (fl15, L) if side == "long" else (fh15, H)
                    q = bisect.bisect_right(sw_s, k - FN) - 1
                    pts = [L[rt] if side == "long" else H[rt]] + ([Ys[sw_s[q]]] if q >= 0 else [])
                    base = min(pts) if side == "long" else max(pts)
                    entry_k, entry, t_dec = rt + 1, O[rt + 1], CT15[rt]
                    stop = base - sg * tr["stop_atr_mult"] * A15[rt]
                    risk = sg * (entry - stop)
                    h_risk = bisect.bisect_right(CT1, CT15[rt]) - 1
            row = {"time": iso(t), "coin": P.coin_of(sym), "symbol": sym, "side": side, "struct": st["kind"],
                   "fib": "" if st["fib"] is None else int(st["fib"]), "D": 1, "E": int(e), "F": int(f), "G": int(g),
                   "H": int(hh), "conf": conf, "ctx4h": ctx, "with_4h": int(ctx == ("up" if side == "long" else "down")),
                   "entry": P.sig(entry), "stop": P.sig(stop), "tp1": "", "tp2": "", "status": "", "reason": "",
                   "exit": "", "exit_time": "", "r": "", "struct4h": struct4,
                   "risk_atr1h": round(risk / A1[h_risk], 2) if A1[h_risk] else "",
                   "entry_time": iso(T15[entry_k]) if entry_k < len(T15) else ""}
            if VC.get("entry") == "limit":
                row.update(line=[T15[j1], X[j1], T15[j2], X[j2]], k_t=T15[k], t_ms=t)
                busy_until = limit_entry(row, side, k, h, conf, line, ex_px, t, busy_until, trades,
                                         T15, O, H, L, C, CT15, fl15, fh15, A15, A1, live)
            elif conf < CFG["min_confirmations"]:
                row.update(status="rejected", reason=f"confirmations {conf} < {CFG['min_confirmations']}")
            elif VC.get("filter_4h") == "structure" and struct4 != "with":
                row.update(status="rejected", reason="against the 4h structure" if struct4 else "no 4h structure yet")
            elif retest_fail:
                row.update(status="rejected", reason=retest_fail)
            elif t_dec < busy_until:
                row.update(status="rejected", reason="position open on this coin")
            elif risk <= 0:
                row.update(status="rejected", reason="entry beyond the stop")
            elif max_risk and A1[h_risk] and risk > max_risk * A1[h_risk]:
                row.update(status="rejected", reason=f"risk above {max_risk} x ATR 1h")
            else:
                tp1, tp2 = entry + sg * tr["tp1_r"] * risk, entry + sg * tr["tp2_r"] * risk
                res = simulate(side, entry, stop, tp1, tp2, entry_k, T15, O, H, L, C, CT15)
                row.update(tp1=P.sig(tp1), tp2=P.sig(tp2))
                if res is None:
                    row.update(status="rejected", reason="not closed by the end of the data")
                else:
                    r, why, exit_ms, exit_px, gross = res
                    busy_until = exit_ms
                    row.update(status="taken", reason=why, exit=P.sig(exit_px), exit_time=iso(exit_ms), r=round(r, 4),
                               r_gross=round(gross, 4))
                    trades.append(dict(row, t=t))
            cands.append(row)
    return cands, trades


def limit_entry(row, side, k, h, conf, line, ex_px, t, busy_until, trades, T15, O, H, L, C, CT15, fl15, fh15, A15, A1,
                live=False):
    """v4 / v4h: the limit order on the line after the break candle k; fills in `row`, returns the new busy_until."""
    tr, sg = CFG["trade"], 1 if side == "long" else -1
    if conf < CFG["min_confirmations"]:
        row.update(status="rejected", reason=f"confirmations {conf} < {CFG['min_confirmations']}")
        return busy_until
    if t < busy_until:
        row.update(status="rejected", reason="position or order open on this coin")
        return busy_until
    sw_s, Ys = (fl15, L) if side == "long" else (fh15, H)
    q = bisect.bisect_right(sw_s, k - FN) - 1
    stop = (Ys[sw_s[q]] if q >= 0 else ex_px) - sg * tr["stop_atr_mult"] * A15[k]
    plan = line(k + 1)
    risk = sg * (plan - stop)
    row.update(entry=P.sig(plan), stop=P.sig(stop), risk_atr1h=round(risk / A1[h], 2) if A1[h] else "")
    if risk <= 0:
        row.update(status="rejected", reason="stop beyond the line")
        return busy_until
    if A1[h] and risk > VC["max_risk_atr_struct"] * A1[h]:
        row.update(status="rejected", reason=f"risk above {VC['max_risk_atr_struct']} x ATR {TF_S}")
        return busy_until
    row["stop_px"] = stop
    o = order_outcome(side, line, k, stop, T15, O, H, L, C, CT15, live)
    return apply_outcome(row, o, busy_until, trades, t)


def order_outcome(side, line, k, stop, T15, O, H, L, C, CT15, live=False):
    """The limit order on `line` placed at the close of candle k with `stop`: {"state": "pending" (live: still
    waiting at the end of the candles) / "cancelled" / "gap" / "open" (live: filled, not closed yet) / "closed" /
    "unclosed" (test: filled, the data ends first), ...}."""
    tr, sg = CFG["trade"], 1 if side == "long" else -1
    last = min(k + VC["limit_bars"], len(T15) - 1)
    fm = None
    for m in range(k + 1, last + 1):
        lv = line(m)
        if (L[m] <= lv) if sg > 0 else (H[m] >= lv):
            fm, entry = m, (min(O[m], lv) if sg > 0 else max(O[m], lv))
            break
    if fm is None:
        if live and k + VC["limit_bars"] > len(T15) - 1:
            return {"state": "pending"}
        return {"state": "cancelled", "busy_ms": CT15[last]}
    risk = sg * (entry - stop)
    o = {"fill_ms": T15[fm], "entry": entry}
    if risk <= 0:
        return dict(o, state="gap", busy_ms=CT15[fm])
    tp1, tp2 = entry + sg * tr["tp1_r"] * risk, entry + sg * tr["tp2_r"] * risk
    o.update(tp1=tp1, tp2=tp2)
    res = simulate(side, entry, stop, tp1, tp2, fm, T15, O, H, L, C, CT15, fill_candle=True)
    if res is None:
        hit = any((H[i] >= tp1) if sg > 0 else (L[i] <= tp1) for i in range(fm + 1, len(T15)))
        return dict(o, state="open" if live else "unclosed", tp1_hit=hit)
    r, why, exit_ms, exit_px, gross = res
    return dict(o, state="closed", r=r, why=why, exit_ms=exit_ms, exit_px=exit_px, gross=gross, busy_ms=exit_ms)


def apply_outcome(row, o, busy_until, trades, t):
    """Write order_outcome() into a journal row; the new busy_until of the coin."""
    st = o["state"]
    if st == "pending":
        row.update(status="pending", reason="limit order on the line")
        return float("inf")
    if st == "cancelled":
        row.update(status="rejected", reason=f"limit not filled within {VC['limit_bars']} candles")
        return o["busy_ms"]
    row.update(entry=P.sig(o["entry"]), entry_time=iso(o["fill_ms"]))
    if st == "gap":
        row.update(status="rejected", reason="filled beyond the stop (gap)")
        return o["busy_ms"]
    row.update(tp1=P.sig(o["tp1"]), tp2=P.sig(o["tp2"]))
    if st == "unclosed":
        row.update(status="rejected", reason="not closed by the end of the data")
        return busy_until
    if st == "open":
        row.update(status="open", reason="filled, open")
        return float("inf")
    row.update(status="taken", reason=o["why"], exit=P.sig(o["exit_px"]), exit_time=iso(o["exit_ms"]),
               r=round(o["r"], 4), r_gross=round(o["gross"], 4))
    trades.append(dict(row, t=t))
    return o["exit_ms"]


# ---------- live (paper.py "friend" signals) ----------
def live_candles(sym, now_ms, fetch=None):
    """(structure, entry, context) candles closed by now_ms, the counts from config live_friend.candles."""
    fetch = fetch or fetch_candles
    out = []
    for tf in (TF_S, TF_E, TF_C):
        n = CFG["live_friend"]["candles"][tf]
        raw = fetch(sym, now_ms - (n + 1) * INTERVALS_MS[tf], now_ms, tf)
        out.append([[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), k[6], float(k[7])]
                    for k in raw if k[6] < now_ms][-n:])
    return tuple(out)


def live_scan(sym, data, t_from, busy_until):
    """New breaks of `sym` closing after t_from on `data` (live_candles), sides from config live_friend: journal
    rows (status pending / open / taken / rejected) and the close time of the last candle scanned."""
    cands, _ = run_coin(sym, data=data, t_from=t_from, t_to=float("inf"), sides=tuple(CFG["live_friend"]["sides"]),
                        busy_until=busy_until, live=True)
    b15 = data[1]
    return cands, (b15[-1][6] + 1 if b15 else t_from)


def live_track(rec, data):
    """order_outcome() of a stored pending / open friend record on fresh entry-timeframe candles, or None if its
    break candle is not in them."""
    b15 = data[1]
    T15, O, H, L, C = ([r[i] for r in b15] for i in range(5))
    CT15 = [r[6] + 1 for r in b15]
    idx = {t: i for i, t in enumerate(T15)}
    if rec["k_t"] not in idx:
        return None
    step = INTERVALS_MS[TF_E]
    t1, x1, t2, x2 = rec["line"]
    j1, j2 = (t1 - T15[0]) / step, (t2 - T15[0]) / step
    line = lambda i: x1 + (x2 - x1) * (i - j1) / (j2 - j1)
    return order_outcome(rec["side"], line, idx[rec["k_t"]], rec.get("stop_x", rec["stop"]), T15, O, H, L, C, CT15,
                         live=True)


def simulate(side, entry, stop, tp1, tp2, k0, T15, O, H, L, C, CT15, fill_candle=False):
    """(R after costs, exit reason, exit ms, last exit price) or None if the data ends first."""
    tr = CFG["trade"]
    sg = 1 if side == "long" else -1
    risk = sg * (entry - stop)
    end = T15[k0] + VC.get("max_hold_h", tr["max_hold_h"]) * 3_600_000
    against = lambda p, i: (L[i] <= p) if sg > 0 else (H[i] >= p)
    reached = lambda p, i: (H[i] >= p) if sg > 0 else (L[i] <= p)
    part, fills, half = tr["tp1_part"], [], False         # fills: (weight, price)
    i = k0
    while i < len(T15) and T15[i] < end:
        if fill_candle and i == k0:                 # limit fill candle: only the stop counts here
            if against(stop, i):
                fills, why = [(1.0, stop)], "stop"
            else:
                i += 1
                continue
        elif not half:
            if against(stop, i):
                fills = [(1.0, stop)]
                why = "stop"
            elif reached(tp2, i):
                fills = [(part, tp1), (1 - part, tp2)]
                why = "tp2"
            elif reached(tp1, i):
                half = True
                if against(entry, i):
                    fills = [(part, tp1), (1 - part, entry)]
                    why = "tp1_be"
                elif CT15[i] >= end:
                    fills, why = [(part, tp1), (1 - part, C[i])], "tp1_time"
                else:
                    i += 1
                    continue
            else:
                if CT15[i] >= end:
                    fills, why = [(1.0, C[i])], "time"
                else:
                    i += 1
                    continue
        else:
            if against(entry, i):
                fills, why = [(part, tp1), (1 - part, entry)], "tp1_be"
            elif reached(tp2, i):
                fills, why = [(part, tp1), (1 - part, tp2)], "tp2"
            elif CT15[i] >= end:
                fills, why = [(part, tp1), (1 - part, C[i])], "tp1_time"
            else:
                i += 1
                continue
        gross = sum(w * sg * (p - entry) for w, p in fills) / risk
        if "fees" in VC:                            # HashHedge: maker entry and targets, taker + slippage otherwise
            fe = VC["fees"]
            exit_cost = 0.0
            for n, (w, p) in enumerate(fills):
                maker = why == "tp2" or (n == 0 and why in ("tp1_be", "tp1_time"))   # the TP1 / TP2 limit fills
                exit_cost += w * p * (fe["maker"] if maker else fe["taker"] + fe["slippage_taker"])
            cost = (fe["maker"] * entry + exit_cost) / risk
        else:
            cost = (tr["fee_rt"] * entry + tr["slippage_side"] * (entry + sum(w * p for w, p in fills))) / risk
        return gross - cost, why, CT15[i], fills[-1][1], gross
    return None


# ---------- report ----------
def stats(rows):
    rs = [x["r"] for x in rows]
    if not rs:
        return {"n": 0, "per_day": 0, "win": None, "avg_r": None, "total_r": 0.0}
    return {"n": len(rs), "per_day": round(len(rs) / ((T1 - T0) / P.DAY_MS), 3),
            "win": round(100 * sum(r > 0 for r in rs) / len(rs), 1), "avg_r": round(sum(rs) / len(rs), 3),
            "total_r": round(sum(rs), 1)}


def full(rows):
    Q = CFG["period"]["quarters"]
    st = stats(rows)
    st["quarters"] = [stats([x for x in rows if ms(Q[i]) < x["t"] <= ms(Q[i + 1])])["total_r"] for i in range(4)]
    by = {}
    for x in rows:
        by[x["symbol"]] = by.get(x["symbol"], 0) + x["r"]
    top = sorted(by, key=lambda s: -by[s])[:CFG["pass"]["plus_without_top"]]
    st["top"] = [P.coin_of(s) for s in top]
    st["without_top"] = stats([x for x in rows if x["symbol"] not in top])
    return st


def main():
    uni = universe()["top"]
    print(f"variant {VARIANT}: {VC}")
    print(f"universe: {len(uni)} coins by quote volume: {', '.join(P.coin_of(s) for s in uni)}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:                   # downloads in parallel; the scan is cheap
        list(ex.map(lambda s: [candles(s, tf, *tf_range(role, tf))
                               for role, tf in (("struct", TF_S), ("entry", TF_E), ("ctx", TF_C))], uni))
    print(f"candles ready ({time.time() - t0:.0f}s)", flush=True)
    cands, trades = [], []
    for s in uni:
        c, tr = run_coin(s)
        cands += c
        trades += tr
        print(f"{s}: {len(c)} candidates, {len(tr)} trades", flush=True)
    cols = ["time", "coin", "side", "struct", "fib", "D", "E", "F", "G", "H", "conf", "ctx4h", "with_4h", "entry",
            "stop", "tp1", "tp2", "status", "reason", "exit", "exit_time", "r"] + (["struct4h", "risk_atr1h"] if VARIANT != "v1" else []) \
        + (["entry_time", "r_gross"] if VARIANT not in ("v1", "v2") else [])
    with open(os.path.join(DIR, "journal.csv" if VARIANT == "v1" else f"journal_{VARIANT}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        w.writeheader()
        for row in sorted(cands, key=lambda x: (x["time"], x["coin"])):
            w.writerow(row)
    groups = {"all": trades, "long": [x for x in trades if x["side"] == "long"],
              "short": [x for x in trades if x["side"] == "short"]}
    for n in (2, 3, 4):
        groups[f"{n} confirmations"] = [x for x in trades if x["conf"] == n]
    groups["impulse5"] = [x for x in trades if x["struct"] == "impulse5"]
    groups["abc+fib"] = [x for x in trades if x["struct"] == "abc"]
    groups["with 4h"] = [x for x in trades if x["with_4h"]]
    groups["against 4h"] = [x for x in trades if not x["with_4h"]]
    groups["4h struct with"] = [x for x in trades if x["struct4h"] == "with"]
    groups["4h struct against"] = [x for x in trades if x["struct4h"] == "against"]
    res = {k: full(v) for k, v in groups.items()}
    a, pc = res["all"], CFG["pass"]
    checks = {"trades>=100": a["n"] >= pc["min_trades"], "avg_r>0.10": (a["avg_r"] or 0) > pc["min_avg_r"],
              "every_quarter_plus": all(q > 0 for q in a["quarters"]), "plus_without_top3": a["without_top"]["total_r"] > 0}
    from collections import Counter
    reasons = Counter(x["reason"] for x in cands if x["status"] == "rejected")
    print(f"\n{len(cands)} candidates (structure + trendline break), {len(trades)} trades; rejected: "
          + ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    print(f"\n{'':<18}{'trades':>7}{'/day':>6}{'win':>7}{'avg R':>8}{'total R':>9}{'Q1':>8}{'Q2':>8}{'Q3':>8}{'Q4':>8}"
          f"{'avg-top3':>10}{'tot-top3':>10}")
    for k, d in res.items():
        print(f"{k:<18}{d['n']:>7}{d['per_day']:>6.2f}{(d['win'] or 0):>6.1f}%{(d['avg_r'] or 0):>+8.3f}{d['total_r']:>+9.1f}"
              + "".join(f"{q:>+8.1f}" for q in d["quarters"])
              + f"{(d['without_top']['avg_r'] or 0):>+10.3f}{d['without_top']['total_r']:>+10.1f}")
    gr = [x["r_gross"] for x in trades]
    print(f"\navg R without fee and slippage: {sum(gr) / len(gr):+.3f} ({len(gr)} trades)" if gr else "")
    print(f"top-3 coins (all): {', '.join(a['top'])}")
    print("checks: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items())
          + f"  ->  {'PASS' if all(checks.values()) else 'FAIL'}")
    json.dump({"universe": uni, "results": res, "checks": checks, "pass": all(checks.values()),
               "rejected": dict(reasons)}, open(os.path.join(DIR, "summary.json" if VARIANT == "v1" else f"summary_{VARIANT}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
