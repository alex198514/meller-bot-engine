"""12-month backtest of the intraday scanner (breakout + wave 3) on all SCANNER_SYMBOLS, 1h and 4h, with the live
run_setups() rules. Research only: paper.py is imported, nothing in the bot is changed.

Rules (the live ones, unchanged):
- each closed 1h / 4h candle is scanned with the window the live run gets (the 999 closed candles up to it):
  setup_at() (breakout) and wave_at() (wave 3; skipped when R:R <= 0, i.e. the fill is already past the target);
- the entry is known only after the candle has closed: breakout = its close, wave = the stop-order fill inside it
  (as run_setups records it); a wave whose candle also touched the stop is a stop (wave_test rule);
- outcomes by track_setup() on 5m candles from the close: stop and target in the same candle = stop,
  breakout half at TP1 then breakeven, rest at TP2; wave one target; exit at the close after 24 hours;
- costs: the live fee (SETUP_FEE_RT, 0.06% round trip) plus slippage SLIPPAGE (0.05%) per side on entry and exit;
- an open signal blocks a new one of the same symbol / tf / type until the run after its exit (close + 35 min);
- market = market_state's rule at the signal: BTC price at the candle close vs the SMA200 of the closed daily
  closes, bull above +MARKET_BAND %, bear below -MARKET_BAND %, else side.

Variants (fixed before the run):
  A all signals; B with the market only (bear -> shorts, bull -> longs, side -> none); C = B on 4h only;
  D = B, breakouts only.
Pass: avg R > +0.10, total R > 0 in each of the four 3-month quarters, total R > 0 without the 3 best coins.

usage: python3 scanner_12m_test.py scan K/N     (shard K of N; per-symbol results in CACHE)
       python3 scanner_12m_test.py report       (tables + data/scanner_12m.json)
"""
import bisect, json, os, sys, time
from datetime import datetime, timezone

import paper as P
from trend_breakout import SLIPPAGE

START = "2025-11-16"
END = "2026-11-16"
QUARTERS = ["2025-11-16", "2026-02-16", "2026-05-16", "2026-08-16", "2026-11-16"]
RUN_LAG = 35 * 60_000
WIN = P.SETUP_SCAN_BARS - 1
CACHE = os.environ.get("SCANNER_12M_CACHE", os.path.join("data", "scanner_12m_cache"))
OUT = os.path.join("data", "scanner_12m.json")
ms = lambda d: int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
iso = lambda t: datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
T0, T1 = ms(START), ms(END)


def bars(sym, tf, a, b):
    return P.kline_bars(P.fetch_candles(sym, a, b, tf), b)


def market_fn():
    """state(t) for a signal whose candle closed at t (market_light's rule, from history)."""
    daily = bars("BTCUSDT", "1d", T0 - 230 * P.DAY_MS, T1)
    hourly = bars("BTCUSDT", "1h", T0 - 2 * P.DAY_MS, T1)
    d_ct = [x["ct"] for x in daily]
    h_t = [x["ct"] + 1 for x in hourly]

    def state(t):
        k = bisect.bisect_left(d_ct, t)                 # daily candles closed before t
        closes = [x["close"] for x in daily[:k]][-200:]
        j = bisect.bisect_right(h_t, t) - 1
        if len(closes) < 200 or j < 0:
            return None
        pct = 100 * (hourly[j]["close"] / (sum(closes) / 200) - 1)
        return "bull" if pct > P.MARKET_BAND else "bear" if pct < -P.MARKET_BAND else "side"
    return state


def scan_symbol(sym, state):
    five = bars(sym, "5m", T0, min(T1 + P.DAY_MS + 3_600_000, int(time.time() * 1000)))
    f_t = [c["t"] for c in five]
    out = []
    for tf, tf_ms in P.SETUP_TF_MS.items():
        bs = bars(sym, tf, T0 - (WIN + 2) * tf_ms, T1)
        for i in range(len(bs)):
            close_ms = bs[i]["ct"] + 1
            if close_ms <= T0 or close_ms > T1:
                continue
            win = bs[max(0, i - WIN + 1):i + 1]
            for kind, hit in (("breakout", P.setup_at(win, len(win) - 1)), ("wave", P.wave_at(win))):
                if not hit or (kind == "wave" and hit["rr"] <= 0):
                    continue
                rec = P.new_setup(sym, tf, hit)
                if hit.get("same_bar_stop"):
                    rec.update(status="stop", exit=rec["stop"])
                    rec["r"] = P.setup_r(rec)
                    exit_ms = close_ms
                else:
                    a = bisect.bisect_left(f_t, close_ms)
                    b = bisect.bisect_left(f_t, close_ms + P.SETUP_EXIT_MS)
                    P.track_setup(rec, five[a:b])
                    if rec["status"] == "open":             # not enough 5m candles yet (the last day)
                        continue
                    rec["r"] = P.setup_r(rec, rec["exit"])
                    exit_ms = rec["checked_ms"]
                risk = abs(rec["entry"] - rec["stop"])
                r = rec["r"] - SLIPPAGE * (rec["entry"] + rec["exit"]) / risk
                out.append({"sym": sym, "tf": tf, "type": kind, "side": rec["side"], "t": close_ms, "exit_ms": exit_ms,
                            "status": rec["status"], "r": round(r, 4), "market": state(close_ms)})
    return out


def scan(k, n):
    os.makedirs(CACHE, exist_ok=True)
    state = market_fn()
    syms = list(P.SCANNER_SYMBOLS)[k::n]
    for j, s in enumerate(syms, 1):
        path = os.path.join(CACHE, s + ".json")
        if os.path.exists(path):
            continue
        t = time.time()
        try:
            rows = scan_symbol(s, state)
        except Exception as e:
            print(f"{s}: failed ({type(e).__name__}: {e})", flush=True)
            continue
        json.dump(rows, open(path, "w"))
        print(f"[{k}/{n}] {j}/{len(syms)} {s}: {len(rows)} candidates, {time.time() - t:.0f}s", flush=True)


VARIANTS = {
    "A": ("all signals", lambda x: True),
    "B": ("with the market only (bear: shorts, bull: longs, side: none)",
          lambda x: (x["market"] == "bear" and x["side"] == "short") or (x["market"] == "bull" and x["side"] == "long")),
    "C": ("B, 4h only", None),
    "D": ("B, breakouts only", None),
}
VARIANTS["C"] = (VARIANTS["C"][0], lambda x: VARIANTS["B"][1](x) and x["tf"] == "4h")
VARIANTS["D"] = (VARIANTS["D"][0], lambda x: VARIANTS["B"][1](x) and x["type"] == "breakout")


def take(cands, keep):
    """The signals the live scanner would record: busy per symbol / tf / type until the run after the exit."""
    busy, out = {}, []
    for x in sorted((c for c in cands if keep(c)), key=lambda c: c["t"]):
        key = (x["sym"], x["tf"], x["type"])
        if x["t"] + RUN_LAG < busy.get(key, 0):
            continue
        busy[key] = x["exit_ms"]
        out.append(x)
    return out


def stats(rows):
    rs = [x["r"] for x in rows]
    if not rs:
        return {"n": 0, "win": None, "avg_r": None, "total_r": 0.0}
    return {"n": len(rs), "win": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 1)}


def report():
    cands, missing = [], []
    for s in P.SCANNER_SYMBOLS:
        path = os.path.join(CACHE, s + ".json")
        if os.path.exists(path):
            cands += json.load(open(path))
        else:
            missing.append(s)
    res = {"period": [START, END], "symbols": len(P.SCANNER_SYMBOLS) - len(missing), "missing": missing,
           "rules": {"tfs": list(P.SETUP_TF_MS), "exit_hours": 24, "fee_rt": P.SETUP_FEE_RT, "slippage_side": SLIPPAGE,
                     "tracking": "5m candles, stop first when both are touched", "market": "BTC vs SMA200, band ±%.1f%%" % P.MARKET_BAND},
           "pass_rule": "avg R > +0.10, every quarter total R > 0, total R > 0 without the 3 best coins",
           "quarters": QUARTERS, "variants": {}}
    qn = [f"Q{i + 1} {QUARTERS[i][2:7]}..{QUARTERS[i + 1][2:7]}" for i in range(4)]
    print(f"12 months {START} .. {END}, {res['symbols']} coins, costs: fee {100 * P.SETUP_FEE_RT:.2f}% RT + slippage "
          f"{100 * SLIPPAGE:.2f}% per side" + (f"; no data: {', '.join(missing)}" if missing else ""))
    for v, (name, keep) in VARIANTS.items():
        rows = take(cands, keep)
        st = stats(rows)
        quarters = [stats([x for x in rows if ms(QUARTERS[i]) < x["t"] <= ms(QUARTERS[i + 1])]) for i in range(4)]
        by = {}
        for x in rows:
            by[x["sym"]] = by.get(x["sym"], 0) + x["r"]
        top3 = sorted(by, key=lambda s: -by[s])[:3]
        ex = stats([x for x in rows if x["sym"] not in top3])
        parts = {k: stats([x for x in rows if f(x)]) for k, f in (
            ("long", lambda x: x["side"] == "long"), ("short", lambda x: x["side"] == "short"),
            ("breakout", lambda x: x["type"] == "breakout"), ("wave", lambda x: x["type"] == "wave"),
            ("1h", lambda x: x["tf"] == "1h"), ("4h", lambda x: x["tf"] == "4h"))}
        checks = {"avg_r_gt_0.10": st["avg_r"] is not None and st["avg_r"] > 0.10,
                  "every_quarter_plus": all(q["total_r"] > 0 for q in quarters),
                  "plus_without_top3": ex["total_r"] > 0}
        res["variants"][v] = {"name": name, **st, "quarters": dict(zip(qn, quarters)), "top3": top3,
                              "without_top3": ex, "parts": parts, "checks": checks, "pass": all(checks.values())}
    print(f"\n{'':<3}{'signals':>8}{'win':>7}{'avg R':>8}{'total R':>9}" + "".join(f"{q[:2]:>8}" for q in qn) +
          f"{'avg-top3':>10}  pass")
    for v, d in res["variants"].items():
        print(f"{v:<3}{d['n']:>8}{(d['win'] or 0):>6.1f}%{(d['avg_r'] or 0):>+8.3f}{d['total_r']:>+9.1f}" +
              "".join(f"{q['total_r']:>+8.1f}" for q in d["quarters"].values()) +
              f"{(d['without_top3']['avg_r'] or 0):>+10.3f}  {'YES' if d['pass'] else 'no'}")
    print("quarters: " + ", ".join(qn))
    for v, d in res["variants"].items():
        print(f"\n{v}: {d['name']}; top-3 coins {', '.join(P.coin_of(s) for s in d['top3'])}; "
              + "; ".join(f"{k} {p['n']} / {(p['avg_r'] or 0):+.3f}R / {p['total_r']:+.0f}R" for k, p in d["parts"].items())
              + "; checks " + ", ".join(f"{k} {'ok' if ok else 'FAIL'}" for k, ok in d["checks"].items()))
    os.makedirs("data", exist_ok=True)
    json.dump(res, open(OUT, "w"), indent=1)
    print(f"\nsaved {OUT}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["scan"]:
        k, n = map(int, (sys.argv[2] if len(sys.argv) > 2 else "0/1").split("/"))
        scan(k, n)
    else:
        report()
