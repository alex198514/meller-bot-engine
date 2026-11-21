"""Research (nothing in the bot or app changes): what does an order placed IN ADVANCE give compared with how the
bot works now (hourly run at :35, the push comes after the entry has already happened)?

Period 2025-11-16 .. 2026-11-16 (the scanner's 12-month test). Fills and exits on 5m candles. HashHedge costs:
maker 0.01% (limit entry, take profits), taker 0.03% + 0.05% slippage (stop / market entries, stops, breakeven
stops, time exits). The strategies' rules are unchanged.

1 Wave 3 (wave_test.run's rules and entries, 126 SCANNER_SYMBOLS, 1h and 4h bars):
  A  the stop order sits at the top of wave 1 from the bar after wave 2's low is confirmed: fill at the first 5m
     candle reaching it, max(open, trigger) for a long; in that candle only the stop counts.
  B  as the live bot: the entry is known at the close of the fill bar, the user enters at the next :35 run
     (the open of the 5m candle at bar close + 35 min) with the same stop and target, only if price has not
     touched the target or the stop since the fill and the entry is still between them.
  Both: one target (wave 2 low + 1.618 x wave 1), stop at wave 2's low, exit 24 h after the entry.
2 Friend's setup (confluence_test.py v4, shorts, its 30 coins; the same orders as the backtest):
  A  the limit order on the line from the close of the break candle (as v4); B  the order appears only at the
     first :35 run at or after that close, touches before are missed; both cancelled 12 candles 15m after the
     break. Line price per 15m candle, fill when a 5m candle touches it; then confluence_test.simulate() (v4:
     fill candle stop only, TP1 1.5R half + breakeven, TP2 3R, 48 h).
3 Breakout C (NEW strategy, pass rule of CLAUDE.md): on every 1h / 4h candle a buy stop at the high and a sell
  stop at the low of the previous 20 candles, placed in advance, no volume / close filter; first touch on 5m
  fills at max(open, level); stop 1.5 x ATR(14) (the 14 candles before) from the fill, TP1 1.5R half then
  breakeven, TP2 3R, exit 24 h after the fill; one position per symbol and timeframe.
Fixed beforehand: A better than B by more than 0.05R per trade -> pre-placed orders are worth it.

usage: python3 preorder_test.py scan K/N     (per-symbol results in data/pre/cache)
       python3 preorder_test.py report       (tables + data/preorder.json)
"""
import bisect, json, os, sys, time
from datetime import datetime, timezone

import paper as P
import wave_test
import confluence_test as CF
from fetch_history import fetch_candles

START, END = "2025-11-16", "2026-11-16"
QUARTERS = ["2025-11-16", "2026-02-16", "2026-05-16", "2026-08-16", "2026-11-16"]
MAKER, TAKER, SLIP = 0.0001, 0.0003, 0.0005
MKT = TAKER + SLIP                       # a market / stop order's cost
RUN_MIN = 35                             # the hourly watch run
TF_MS = {"1h": 3_600_000, "4h": 14_400_000}
FIVE = 300_000
CACHE = os.path.join("data", "pre", "cache")
OUT = os.path.join("data", "preorder.json")
ms = lambda d: int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
T0, T1 = ms(START), ms(END)


def next_run(t):
    """The first hourly run (:35) at or after t."""
    h = t - t % 3_600_000
    r = h + RUN_MIN * 60_000
    return r if r >= t else r + 3_600_000


def bars(sym, tf, a, b):
    return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), k[6] + 1] for k in fetch_candles(sym, a, b, tf)
            if k[6] < b]


def sim(sg, entry, stop, tps, k, F, hold_ms, entry_cost, fill_candle):
    """R after costs of a position entered in 5m candle k of F = (T, O, H, L, C). tps = [tp] or [tp1, tp2] (half
    each, stop to breakeven after TP1). Stop first when both are touched; a TP1 candle that also touches the
    entry closes the rest at breakeven; fill_candle: in candle k only the stop counts. Exits at the levels, the
    time exit at the close of the last candle within hold_ms. (r, reason, exit_ms, gross) or None (data ends)."""
    T, O, H, L, C = F
    risk = sg * (entry - stop)
    end = T[k] + hold_ms
    against = lambda p, i: (L[i] <= p) if sg > 0 else (H[i] >= p)
    reached = lambda p, i: (H[i] >= p) if sg > 0 else (L[i] <= p)
    fills, half = [], False                         # (weight, price, maker)
    i = k
    while i < len(T) and T[i] < end:
        if fill_candle and i == k:
            if against(stop, i):
                fills, why = [(1.0, stop, False)], "stop"
                break
            i += 1
            continue
        if len(tps) == 1:
            if against(stop, i):
                fills, why = [(1.0, stop, False)], "stop"
                break
            if reached(tps[0], i):
                fills, why = [(1.0, tps[0], True)], "tp"
                break
        elif not half:
            if against(stop, i):
                fills, why = [(1.0, stop, False)], "stop"
                break
            if reached(tps[1], i):
                fills, why = [(0.5, tps[0], True), (0.5, tps[1], True)], "tp2"
                break
            if reached(tps[0], i):
                half = True
                if against(entry, i):
                    fills, why = [(0.5, tps[0], True), (0.5, entry, False)], "tp1_be"
                    break
        else:
            if against(entry, i):
                fills, why = [(0.5, tps[0], True), (0.5, entry, False)], "tp1_be"
                break
            if reached(tps[1], i):
                fills, why = [(0.5, tps[0], True), (0.5, tps[1], True)], "tp2"
                break
        if T[i] + FIVE >= end:
            fills = ([(0.5, tps[0], True)] if half else []) + [(0.5 if half else 1.0, C[i], False)]
            why = "tp1_time" if half else "time"
            break
        i += 1
    else:
        return None
    gross = sum(w * sg * (p - entry) for w, p, _ in fills) / risk
    cost = (entry_cost * entry + sum(w * p * (MAKER if mk else MKT) for w, p, mk in fills)) / risk
    return gross - cost, why, T[i] + FIVE, gross


def first_touch(F, a, b, test):
    """Index of the first 5m candle in [a, b) for which test(i) is true, or None."""
    for i in range(a, b):
        if test(i):
            return i
    return None


# ---------- 1 wave 3 ----------
def wave_rows(sym, tf, tb, F, T5):
    b = [{"t": x[0], "o": x[1], "h": x[2], "l": x[3], "c": x[4]} for x in tb]
    hits = []
    wave_test.run(b, sym, on_entry=lambda i, st, fill: hits.append((i, st)))
    out = []
    for i, st in hits:
        t_open, t_close = tb[i][0], tb[i][5]
        if not (T0 <= t_open < T1):
            continue
        sg, trig, stop, tp = st["side"], st["trig"], st["inv"], st["tp"]
        a, z = bisect.bisect_left(T5, t_open), bisect.bisect_left(T5, t_close)
        T, O, H, L, C = F
        k = first_touch(F, a, z, lambda j: (H[j] >= trig) if sg > 0 else (L[j] <= trig))
        if k is None:
            continue                                # the 5m data does not show the touch (gap in data)
        ea = max(O[k], trig) if sg > 0 else min(O[k], trig)
        row = {"sym": sym, "tf": tf, "side": "long" if sg > 0 else "short", "t": T[k], "entry_a": ea}
        if sg * (ea - stop) <= 0:
            continue
        ra = sim(sg, ea, stop, [tp], k, F, P.DAY_MS, MKT, True)
        if ra:
            row.update(r_a=ra[0], why_a=ra[1], gross_a=ra[3])
        # B: the next run after the fill bar's close
        run = next_run(t_close)
        kb = bisect.bisect_left(T5, run)
        row["delay_min"] = (run - T[k]) / 60_000
        if kb >= len(T5) or T5[kb] != run:
            row["skip_b"] = "no 5m candle at the run"
        else:
            touched = any(((L[j] <= stop or H[j] >= tp) if sg > 0 else (H[j] >= stop or L[j] <= tp)) for j in range(k, kb))
            eb = O[kb]
            if touched:
                row["skip_b"] = "target or stop touched before the run"
            elif not (sg * (tp - eb) > 0 and sg * (eb - stop) > 0):
                row["skip_b"] = "price beyond the target or stop at the run"
            else:
                rb = sim(sg, eb, stop, [tp], kb, F, P.DAY_MS, MKT, False)
                if rb:
                    row.update(entry_b=eb, r_b=rb[0], why_b=rb[1], gross_b=rb[3],
                               worse_r=sg * (eb - ea) / (sg * (ea - stop)))
        out.append(row)
    return out


# ---------- 3 breakout C ----------
def breakout_rows(sym, tf, tb, F, T5):
    T, O, H, L, C = F
    out, busy = [], 0
    for i in range(20, len(tb)):
        t_open = tb[i][0]
        if not (T0 <= t_open < T1) or t_open < busy:
            continue
        prev = tb[i - 20:i]
        hi, lo = max(x[2] for x in prev), min(x[3] for x in prev)
        trs = [max(tb[j][2] - tb[j][3], abs(tb[j][2] - tb[j - 1][4]), abs(tb[j][3] - tb[j - 1][4])) for j in range(i - 14, i)]
        atr = sum(trs) / 14
        if atr <= 0:
            continue
        a, z = bisect.bisect_left(T5, t_open), bisect.bisect_left(T5, tb[i][5])
        k = first_touch(F, a, z, lambda j: H[j] >= hi or L[j] <= lo)
        if k is None:
            continue
        up, dn = H[k] >= hi, L[k] <= lo
        if up and dn:                               # both levels in one 5m candle: the one nearer the open first
            up = hi - O[k] <= O[k] - lo
        sg = 1 if up else -1
        lvl = hi if up else lo
        e = max(O[k], lvl) if sg > 0 else min(O[k], lvl)
        stop = e - sg * 1.5 * atr
        res = sim(sg, e, stop, [e + sg * 1.5 * 1.5 * atr, e + sg * 3.0 * 1.5 * atr], k, F, P.DAY_MS, MKT, True)
        if not res:
            continue
        busy = res[2]
        out.append({"sym": sym, "tf": tf, "side": "long" if sg > 0 else "short", "t": T[k], "r": res[0],
                    "why": res[1], "gross": res[3]})
    return out


# ---------- 2 friend ----------
def friend_rows(sym, F, T5):
    CF.set_variant("v4")
    cands, _ = CF.run_coin(sym, sides=("short",))
    T, O, H, L, C = F
    step = 15 * 60_000
    hold = CF.VC["max_hold_h"] * 3_600_000
    tr = CF.CFG["trade"]
    out = []
    for row in cands:
        placed = row["status"] == "taken" or row["reason"].startswith(("limit not filled", "filled beyond", "not closed"))
        if not placed:
            continue
        t1, x1, t2, x2 = row["line"]
        line = lambda t15: x1 + (x2 - x1) * ((t15 - t1) / step) / ((t2 - t1) / step)
        stop = row["stop_px"]
        t_break_close = row["t_ms"]
        expiry = t_break_close + CF.VC["limit_bars"] * step

        def fill(start):
            a, z = bisect.bisect_left(T5, start), bisect.bisect_left(T5, expiry)
            for j in range(a, z):
                lv = line(T[j] - T[j] % step)       # the line's price of the 15m candle holding this 5m candle
                if H[j] >= lv:
                    return j, max(O[j], lv)
            return None, None

        def trade(j, e):
            risk = stop - e
            if risk <= 0:
                return {"gap": True}
            tp1, tp2 = e - tr["tp1_r"] * risk, e - tr["tp2_r"] * risk
            res = sim(-1, e, stop, [tp1, tp2], j, F, hold, MAKER, True)
            return {"r": res[0], "why": res[1], "gross": res[3]} if res else None
        rec = {"sym": sym, "t": t_break_close, "run": next_run(t_break_close), "stop": stop}
        ja, ea = fill(t_break_close)
        if ja is not None:
            rec.update(fill_a=T[ja], entry_a=ea, a=trade(ja, ea))
        if rec["run"] >= expiry:
            rec["b_note"] = "order expired before the run"
        else:
            jb, eb = fill(rec["run"])
            if jb is not None:
                rec.update(fill_b=T[jb], entry_b=eb, b=trade(jb, eb))
        out.append(rec)
    return out


def scan(k, n):
    os.makedirs(CACHE, exist_ok=True)
    friends = set(CF.CFG["live_friend"]["symbols"])
    for j, s in enumerate(list(P.SCANNER_SYMBOLS)[k::n], 1):
        path = os.path.join(CACHE, s + ".json")
        if os.path.exists(path):
            continue
        t = time.time()
        try:
            raw5 = fetch_candles(s, T0 - P.DAY_MS, T1 + 3 * P.DAY_MS, "5m")
            T5 = [x[0] for x in raw5]
            F = (T5, [float(x[1]) for x in raw5], [float(x[2]) for x in raw5], [float(x[3]) for x in raw5],
                 [float(x[4]) for x in raw5])
            res = {"wave": [], "breakout": [], "friend": []}
            for tf, tf_ms in TF_MS.items():
                tb = bars(s, tf, T0 - (60 if tf == "1h" else 240) * P.DAY_MS, T1 + 2 * P.DAY_MS)
                res["wave"] += wave_rows(s, tf, tb, F, T5)
                res["breakout"] += breakout_rows(s, tf, tb, F, T5)
            if s in friends:
                res["friend"] = friend_rows(s, F, T5)
        except Exception as e:
            print(f"{s}: failed ({type(e).__name__}: {e})", flush=True)
            continue
        json.dump(res, open(path, "w"))
        print(f"[{k}/{n}] {j} {s}: wave {len(res['wave'])}, breakout {len(res['breakout'])}, friend {len(res['friend'])}"
              f" ({time.time() - t:.0f}s)", flush=True)


# ---------- report ----------
def stats(rs_t):
    """rs_t = [(r, t, sym)]"""
    rs = [r for r, _, _ in rs_t]
    if not rs:
        return {"n": 0, "win": None, "avg_r": None, "total_r": 0.0, "quarters": [0.0] * 4, "without_top3": None}
    q = [round(sum(r for r, t, _ in rs_t if ms(QUARTERS[i]) <= t < ms(QUARTERS[i + 1])), 1) for i in range(4)]
    by = {}
    for r, _, s in rs_t:
        by[s] = by.get(s, 0) + r
    top = sorted(by, key=lambda s: -by[s])[:3]
    ex = [r for r, _, s in rs_t if s not in top]
    return {"n": len(rs), "win": round(100 * sum(r > 0 for r in rs) / len(rs), 1), "avg_r": round(sum(rs) / len(rs), 3),
            "total_r": round(sum(rs), 1), "quarters": q, "top3": [P.coin_of(s) for s in top],
            "without_top3": {"avg_r": round(sum(ex) / len(ex), 3) if ex else None, "total_r": round(sum(ex), 1)}}


def report():
    W, B, FR, missing = [], [], [], []
    for s in P.SCANNER_SYMBOLS:
        path = os.path.join(CACHE, s + ".json")
        if not os.path.exists(path):
            missing.append(s)
            continue
        d = json.load(open(path))
        W += d["wave"]
        B += d["breakout"]
        FR += d["friend"]
    res = {"period": [START, END], "costs": {"maker": MAKER, "taker": TAKER, "slippage": SLIP}, "missing": missing}
    line = lambda name, st: (f"{name:<24}{st['n']:>6}{(st['win'] or 0):>7.1f}%{(st['avg_r'] or 0):>+8.3f}{st['total_r']:>+9.1f}"
                             + "".join(f"{q:>+8.1f}" for q in st["quarters"])
                             + f"{((st['without_top3'] or {}).get('avg_r') or 0):>+10.3f}")
    head = f"{'':<24}{'trades':>6}{'win':>8}{'avg R':>8}{'total R':>9}{'Q1':>8}{'Q2':>8}{'Q3':>8}{'Q4':>8}{'avg-top3':>10}"

    # 1 wave
    wa = [(x["r_a"], x["t"], x["sym"]) for x in W if "r_a" in x]
    wb = [(x["r_b"], x["t"], x["sym"]) for x in W if "r_b" in x]
    both = [x for x in W if "r_a" in x and "r_b" in x]
    skips = {}
    for x in W:
        if "skip_b" in x:
            skips[x["skip_b"]] = skips.get(x["skip_b"], 0) + 1
    w = {"A": stats(wa), "B": stats(wb), "skipped_b": skips,
         "paired": {"n": len(both), "a_avg": round(sum(x["r_a"] for x in both) / len(both), 3) if both else None,
                    "b_avg": round(sum(x["r_b"] for x in both) / len(both), 3) if both else None},
         "delay_min": round(sum(x["delay_min"] for x in W) / len(W), 1) if W else None,
         "worse_r": round(sum(x["worse_r"] for x in both) / len(both), 3) if both else None,
         "by_tf": {tf: {"A": stats([(x["r_a"], x["t"], x["sym"]) for x in W if "r_a" in x and x["tf"] == tf]),
                        "B": stats([(x["r_b"], x["t"], x["sym"]) for x in W if "r_b" in x and x["tf"] == tf])} for tf in TF_MS}}
    w["a_minus_b"] = round((w["A"]["avg_r"] or 0) - (w["B"]["avg_r"] or 0), 3)
    w["worth_it"] = w["a_minus_b"] > 0.05
    res["wave"] = w
    print(f"\n=== 1 Wave 3 (126 coins, 1h + 4h; {len(W)} wave_test entries) ===\n{head}")
    print(line("A pre-placed stop", w["A"]))
    print(line("B at the :35 run", w["B"]))
    for tf in TF_MS:
        print(line(f"  {tf} A", w["by_tf"][tf]["A"]))
        print(line(f"  {tf} B", w["by_tf"][tf]["B"]))
    print(f"A - B per trade: {w['a_minus_b']:+.3f}R; same setups traded in both ({len(both)}): A {w['paired']['a_avg']:+.3f}R, "
          f"B {w['paired']['b_avg']:+.3f}R")
    print(f"B skipped: {skips}; mean entry delay B {w['delay_min']} min; mean entry worse by {w['worse_r']:+.3f} of the stop")

    # 2 friend
    fa = [(x["a"]["r"], x["t"], x["sym"]) for x in FR if x.get("a") and "r" in x["a"]]
    fb = [(x["b"]["r"], x["t"], x["sym"]) for x in FR if x.get("b") and "r" in x["b"]]
    fboth = [x for x in FR if x.get("a") and "r" in x["a"] and x.get("b") and "r" in x["b"]]
    early = sum(1 for x in FR if "fill_a" in x and x["fill_a"] < x["run"])
    f = {"orders": len(FR), "A": stats(fa), "B": stats(fb),
         "filled_a": sum("fill_a" in x for x in FR), "filled_b": sum("fill_b" in x for x in FR),
         "filled_before_push": early, "expired_before_run": sum(x.get("b_note") == "order expired before the run" for x in FR),
         "delay_min": round(sum((x["run"] - x["t"]) / 60_000 for x in FR) / len(FR), 1) if FR else None,
         "worse_r": round(sum((x["entry_a"] - x["entry_b"]) / (CFG_STOP(x) - x["entry_a"]) for x in fboth) / len(fboth), 3) if fboth else None,
         "paired": {"n": len(fboth), "a_avg": round(sum(x["a"]["r"] for x in fboth) / len(fboth), 3) if fboth else None,
                    "b_avg": round(sum(x["b"]["r"] for x in fboth) / len(fboth), 3) if fboth else None}}
    f["a_minus_b"] = round((f["A"]["avg_r"] or 0) - (f["B"]["avg_r"] or 0), 3)
    f["worth_it"] = f["a_minus_b"] > 0.05
    res["friend"] = f
    print(f"\n=== 2 Friend's setup v4 shorts (30 coins; {len(FR)} limit orders) ===\n{head}")
    print(line("A order at the break", f["A"]))
    print(line("B order at the :35 run", f["B"]))
    print(f"A - B per trade: {f['a_minus_b']:+.3f}R; same orders traded in both ({len(fboth)}): A {f['paired']['a_avg']:+.3f}R, "
          f"B {f['paired']['b_avg']:+.3f}R")
    print(f"filled A {f['filled_a']}, B {f['filled_b']}; A fills before the bot's push {early}; orders expired before the "
          f"run {f['expired_before_run']}; mean delay of the order in B {f['delay_min']} min; B entry worse by {f['worse_r']} of the stop")

    # 3 breakout C
    c = stats([(x["r"], x["t"], x["sym"]) for x in B])
    checks = {"trades>=100": c["n"] >= 100, "avg_r>0.10": (c["avg_r"] or 0) > 0.10,
              "every_quarter_plus": all(q > 0 for q in c["quarters"]),
              "plus_without_top3": ((c["without_top3"] or {}).get("total_r") or 0) > 0}
    parts = {k: stats([(x["r"], x["t"], x["sym"]) for x in B if fn(x)]) for k, fn in (
        ("1h", lambda x: x["tf"] == "1h"), ("4h", lambda x: x["tf"] == "4h"),
        ("long", lambda x: x["side"] == "long"), ("short", lambda x: x["side"] == "short"))}
    gr = [x["gross"] for x in B]
    res["breakout_c"] = {"all": c, "parts": parts, "checks": checks, "pass": all(checks.values()),
                         "avg_r_before_costs": round(sum(gr) / len(gr), 3) if gr else None}
    print(f"\n=== 3 Breakout C: stop orders at the 20-candle high / low in advance (NEW, 126 coins) ===\n{head}")
    print(line("all", c))
    for k, st in parts.items():
        print(line(f"  {k}", st))
    print(f"avg R before costs {res['breakout_c']['avg_r_before_costs']:+.3f}; checks: "
          + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()) + f" -> {'PASS' if all(checks.values()) else 'FAIL'}")
    print(f"\nconclusion (fixed: A - B > 0.05R): wave {'yes' if w['worth_it'] else 'no'} ({w['a_minus_b']:+.3f}R), "
          f"friend {'yes' if f['worth_it'] else 'no'} ({f['a_minus_b']:+.3f}R)" + (f"; missing {missing}" if missing else ""))
    os.makedirs("data", exist_ok=True)
    json.dump(res, open(OUT, "w"), indent=1)
    print(f"saved {OUT}")


def CFG_STOP(x):
    return x["stop"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["scan"]:
        k, n = map(int, (sys.argv[2] if len(sys.argv) > 2 else "0/1").split("/"))
        scan(k, n)
    else:
        report()
