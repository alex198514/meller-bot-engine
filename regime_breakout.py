"""Experiment 6: trend_breakout.py (lookback 20) with a BTC market-regime filter, next to the baseline.

Regime of a day = BULL if BTC's daily close that day is above its 200-day simple moving average
(the 200 closes up to and including that day), BEAR if below. Only data up to that day is used.
Before BTC has 200 closes there is no regime and the regime version takes no entries.

  baseline  trend_breakout.backtest() unchanged: long only, every day.
  regime    BULL days: long entries only, rules identical to the baseline.
            BEAR days: short entries only, mirrored rules:
              entry     daily close below the lowest low of the previous 20 days; skip if that
                        day's range is above 2x the filtered ATR; sell at that close (- slippage)
              stop      initial stop = entry + 2 x ATR; intraday, checked first: if a day's high
                        touches it, exit there (or at the open if the day opened above it)
              trailing  lowest close since entry + 3 x ATR, only moves down; set at a close,
                        exit at the first later close above it
            The regime only decides which side may ENTER. An open position is managed by its own
            stops until it exits, even if the regime flips meanwhile. One position per symbol.
Same filtered ATR(14), fees 0.1% and slippage 0.05% per side. 1R = |entry fill - initial stop|.

Usage:
  python3 regime_breakout.py --set insample   5 known symbols, days before 2025-11-02 only
  python3 regime_breakout.py --set unseen     10 never-used symbols, full history (download first:
                                              python3 fetch_history.py --symbol ADAUSDT --interval 1d --all ...)
The unseen set ends where data/btc_1d_all.csv ends (its last complete day), so every day has a regime.
"""

import argparse
import csv
import json
import os

from trend_breakout import (FEE, SKIP_RANGE_ATR, SLIPPAGE, STOP_ATR, SYMBOLS, TRAIL_ATR, UNTIL, backtest,
                            daily_path, filtered_atr, load_daily, stats)

LOOKBACK = 20
SMA_N = 200
REGIME_SYMBOL = "BTCUSDT"
UNSEEN = ("ADAUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT",
          "DOTUSDT", "TRXUSDT", "ATOMUSDT", "XLMUSDT", "ETCUSDT")


def btc_regime(btc_bars):
    """{day: 'BULL' | 'BEAR'} from BTC close vs its SMA(200) of the closes up to that day."""
    regime, closes, total = {}, [], 0.0
    for b in btc_bars:
        closes.append(b["close"])
        total += b["close"]
        if len(closes) > SMA_N:
            total -= closes[-SMA_N - 1]
        if len(closes) >= SMA_N:
            sma = total / SMA_N
            if b["close"] > sma:
                regime[b["time"]] = "BULL"
            elif b["close"] < sma:
                regime[b["time"]] = "BEAR"
    return regime


def close_pos(pos, price, t, reason, trades):
    d = pos["dir"]
    fill = price * (1 - d * SLIPPAGE)              # long sells lower, short buys back higher
    fees = FEE * (pos["entry"] + fill)
    r = (d * (fill - pos["entry"]) - fees) / pos["risk"]
    trades.append({**pos, "exit_t": t, "exit": fill, "reason": reason, "result_r": r,
                   "fees_r": fees / pos["risk"], "days": t - pos["entry_t"]})


def backtest_regime(bars, regime, lookback=LOOKBACK):
    """Long entries on BULL days, mirrored short entries on BEAR days, none without a regime."""
    trades, pos = [], None
    for t, bar in enumerate(bars):
        atr = filtered_atr(bars, t)
        if pos:
            d = pos["dir"]
            if (bar["low"] <= pos["stop"]) if d > 0 else (bar["high"] >= pos["stop"]):     # 1. initial stop
                close_pos(pos, min(bar["open"], pos["stop"]) if d > 0 else max(bar["open"], pos["stop"]),
                          t, "stop", trades)
                pos = None
            elif pos["trail"] is not None and d * (bar["close"] - pos["trail"]) < 0:       # 2. trailing stop
                close_pos(pos, bar["close"], t, "trail", trades)
                pos = None
            else:                                                                         # 3. move the trail
                pos["ext_close"] = max(pos["ext_close"], bar["close"]) if d > 0 else min(pos["ext_close"], bar["close"])
                if atr is not None:
                    level = pos["ext_close"] - d * TRAIL_ATR * atr
                    pos["trail"] = level if pos["trail"] is None else (
                        max(pos["trail"], level) if d > 0 else min(pos["trail"], level))
            continue

        side = regime.get(bar["time"])
        if t < lookback or atr is None or side is None:
            continue
        prior = bars[t - lookback:t]
        if side == "BULL":
            d = 1
            if bar["close"] <= max(b["high"] for b in prior):
                continue
        else:
            d = -1
            if bar["close"] >= min(b["low"] for b in prior):
                continue
        if bar["high"] - bar["low"] > SKIP_RANGE_ATR * atr:
            continue
        fill = bar["close"] * (1 + d * SLIPPAGE)
        stop = fill - d * STOP_ATR * atr
        pos = {"dir": d, "entry_t": t, "entry": fill, "stop": stop, "risk": abs(fill - stop), "atr": atr,
               "ext_close": bar["close"], "trail": bar["close"] - d * TRAIL_ATR * atr}

    if pos:
        close_pos(pos, bars[-1]["close"], len(bars) - 1, "end of data", trades)
    for tr in trades:
        tr["entry_time"] = bars[tr["entry_t"]]["time"]
        tr["exit_time"] = bars[tr["exit_t"]]["time"]
    return trades


def fmt(name, st, width=24):
    pf = f"{st['profit_factor']:.2f}" if st["profit_factor"] is not None else ("n/a" if not st["trades"] else "inf")
    return (f"{name:<{width}}{st['trades']:>7}{st['win_pct']:>7.1f}%{st['avg_r']:>+8.2f}{st['total_r']:>+9.2f}"
            f"{pf:>7}{st['max_drawdown_r']:>8.2f}")


def head(first, width=24):
    return f"{first:<{width}}{'trades':>7}{'win':>8}{'avg R':>8}{'total R':>9}{'PF':>7}{'max DD':>8}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=("insample", "unseen"), required=True)
    args = parser.parse_args()

    # insample: only days before UNTIL are ever loaded; unseen: complete days ("live" drops today's bar)
    symbols, until = (SYMBOLS, UNTIL) if args.set == "insample" else (UNSEEN, "live")
    btc, _ = load_daily(daily_path(REGIME_SYMBOL), until)
    end_day = btc[-1]["time"]
    regime = btc_regime(btc)
    first_regime = min(regime)
    data = {s: [b for b in load_daily(daily_path(s), until)[0] if b["time"] <= end_day] for s in symbols}

    period = f"days before {UNTIL}" if args.set == "insample" else f"full history up to {end_day}"
    print(f"Experiment 6: trend breakout {LOOKBACK}d, {args.set} set ({len(symbols)} symbols), {period}")
    print(f"Regime: BTC close vs SMA({SMA_N}) of BTC closes; first day with a regime: {first_regime}. "
          f"BULL days {sum(v == 'BULL' for v in regime.values())}, BEAR days {sum(v == 'BEAR' for v in regime.values())}")
    print(f"Costs: fee {FEE:.1%} + slippage {SLIPPAGE:.2%} per side. All figures in R.\n")

    versions = {"baseline": {}, "regime": {}}
    for s, bars in data.items():
        versions["baseline"][s] = [{**tr, "dir": 1} for tr in backtest(bars, LOOKBACK)]
        versions["regime"][s] = backtest_regime(bars, regime)

    out, rows = {"set": args.set, "period": period, "first_regime_day": first_regime}, []
    for v, by_sym in versions.items():
        print(f"== {v} ==")
        print(head("symbol / period"))
        out[v] = {}
        for s, trades in by_sym.items():
            st = stats(trades)
            out[v][s] = st
            print(fmt(f"{s} {data[s][0]['time'][:7]}", st))
            for tr in trades:
                rows.append({"version": v, "symbol": s, "side": "long" if tr["dir"] > 0 else "short",
                             "entry_time": tr["entry_time"], "exit_time": tr["exit_time"], "days": tr["days"],
                             "entry": round(tr["entry"], 8), "initial_stop": round(tr["stop"], 8),
                             "exit": round(tr["exit"], 8), "reason": tr["reason"],
                             "fees_r": round(tr["fees_r"], 3), "result_r": round(tr["result_r"], 3)})
        everything = [tr for trades in by_sym.values() for tr in trades]
        st = stats(everything)
        out[v]["ALL"] = st
        print(fmt("ALL", st))
        if v == "baseline":
            same = [tr for tr in everything if tr["entry_time"] >= first_regime]
            out[v]["ALL_from_first_regime_day"] = stats(same)
            print(fmt(f"ALL entries >= {first_regime}", stats(same)))
        print()

    print("== by year of entry (all symbols) ==")
    years = sorted({tr["entry_time"][:4] for by_sym in versions.values() for trades in by_sym.values() for tr in trades})
    print(f"{'year':<6}{'baseline':>36}   {'regime':>36}")
    print(f"{'':<6}{'trades  win%   avg R  total R    PF':>36}   {'trades  win%   avg R  total R    PF':>36}")
    out["by_year"] = {}
    for y in years:
        cells = []
        for v, by_sym in versions.items():
            st = stats([tr for trades in by_sym.values() for tr in trades if tr["entry_time"][:4] == y])
            out["by_year"].setdefault(y, {})[v] = st
            pf = f"{st['profit_factor']:.2f}" if st["profit_factor"] is not None else ("-" if not st["trades"] else "inf")
            cells.append(f"{st['trades']:>6}{st['win_pct']:>6.1f}{st['avg_r']:>+8.2f}{st['total_r']:>+9.2f}{pf:>7}")
        print(f"{y:<6}{cells[0]:>36}   {cells[1]:>36}")
    print()

    print("== longs vs shorts (all symbols) ==")
    print(head("version / side"))
    out["by_side"] = {}
    for v, by_sym in versions.items():
        everything = [tr for trades in by_sym.values() for tr in trades]
        for side, d in (("long", 1), ("short", -1)):
            part = [tr for tr in everything if tr["dir"] == d]
            if v == "baseline" and not part:
                continue
            st = stats(part)
            out["by_side"][f"{v}_{side}"] = st
            print(fmt(f"{v} {side}s", st))
    print()

    name = f"regime_breakout_{args.set}"
    with open(os.path.join("data", name + "_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join("data", name + ".json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved data/{name}_trades.csv and data/{name}.json")


if __name__ == "__main__":
    main()
