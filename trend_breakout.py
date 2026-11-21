"""Strategy 3: long-only trend breakout on DAILY candles, with a filtered ATR and a trailing stop.

Rules (decisions at the daily close, only with data up to that close):
  ATR       Gerchik-style filtered ATR(14) from the 14 daily bars BEFORE the current day:
            plain ATR = average range (high - low) of those 14 bars; filtered ATR = average of only
            the ranges between 0.5x and 2x the plain ATR (if none qualify, the plain ATR).
  entry     the daily close is above the highest high of the previous N days (N = 20; 10 and 55
            as a robustness check). Skip if that day's range is above 2x the filtered ATR.
            Buy at that close (+ slippage).
  stop      initial stop = entry - 2 x ATR (ATR at the entry day). Intraday: if a day's low touches
            it, exit there (or at the open if the day opened below it) - checked before anything else.
  trailing  highest close since entry - 3 x ATR (ATR of that day), only moves up; it is set at a
            close and used from the next day: exit at the first daily close below it.
  no fixed targets; one position per symbol; a new entry is possible from the day after an exit.
Costs: 0.1% fee per side plus 0.05% slippage per side (buy higher, sell lower).
1R = initial risk per trade = entry fill - initial stop.

Usage: python3 trend_breakout.py [--symbol BTCUSDT,ETHUSDT,...] [--lookback 10,20,55] [--until 2025-11-02]
       python3 trend_breakout.py --lookback 20 --from 2025-11-02 --until live   (out-of-sample check)
--from: entries only from that day; earlier days only warm up the N-day high and the ATR.
--until live: all complete days; today's unfinished daily candle gives no signals, but positions
still open are marked at its latest price (as if closed now, with fees and slippage), and an
initial stop already touched by today's low counts as hit.
Download the data first: python3 fetch_history.py --symbol BTCUSDT --interval 1d --all
"""

import argparse
import csv
import json
import os

from datetime import datetime, timezone

from symbols import base

ATR_N = 14
ATR_LOW, ATR_HIGH = 0.5, 2.0      # ranges outside 0.5x-2x the plain ATR are ignored
SKIP_RANGE_ATR = 2.0              # skip a breakout day with range above 2x the filtered ATR
STOP_ATR = 2.0
TRAIL_ATR = 3.0
FEE = 0.001                       # 0.1% per side
SLIPPAGE = 0.0005                 # 0.05% per side
LOOKBACKS = (10, 20, 55)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
UNTIL = "2025-11-02"
RISK_PER_TRADE = 0.01             # only for the % comparison with buy-and-hold: 1% of equity per 1R


def daily_path(symbol):
    return os.path.join("data", f"{base(symbol)}_1d_all.csv")


def load_daily(path, until):
    """Complete daily bars before `until` ('live' = up to yesterday) and today's unfinished bar (or None)."""
    with open(path, newline="") as f:
        rows = [{"time": r["time"][:10], "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])} for r in csv.DictReader(f)]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    live = rows[-1] if rows and rows[-1]["time"] == today else None
    end = today if until == "live" else min(until, today)
    return [r for r in rows if r["time"] < end], (live if until == "live" else None)


def filtered_atr(bars, t):
    """Filtered ATR from bars t-14 .. t-1 (known before day t). None if not enough history."""
    if t < ATR_N:
        return None
    ranges = [b["high"] - b["low"] for b in bars[t - ATR_N:t]]
    plain = sum(ranges) / ATR_N
    kept = [r for r in ranges if ATR_LOW * plain <= r <= ATR_HIGH * plain]
    return sum(kept) / len(kept) if kept else plain


def backtest(bars, lookback, start=None, live=None):
    """start: first day on which entries are allowed (YYYY-MM-DD); live: today's unfinished bar."""
    trades, pos = [], None
    for t in range(len(bars)):
        bar = bars[t]
        atr = filtered_atr(bars, t)

        if pos:
            # 1. Initial stop, intraday, checked first
            if bar["low"] <= pos["stop"]:
                close_trade(pos, min(bar["open"], pos["stop"]), t, "stop", trades)
                pos = None
            # 2. Trailing stop set at the previous close
            elif pos["trail"] is not None and bar["close"] < pos["trail"]:
                close_trade(pos, bar["close"], t, "trail", trades)
                pos = None
            else:
                # 3. Update the trailing stop for tomorrow (it only moves up)
                pos["high_close"] = max(pos["high_close"], bar["close"])
                if atr is not None:
                    level = pos["high_close"] - TRAIL_ATR * atr
                    pos["trail"] = level if pos["trail"] is None else max(pos["trail"], level)
                continue  # still in the trade; no new entry today
            continue      # exited today; a new entry is possible from tomorrow

        # Entry at the close
        if t < lookback or atr is None or (start and bar["time"] < start):
            continue
        prior_high = max(b["high"] for b in bars[t - lookback:t])
        if bar["close"] <= prior_high:
            continue
        if bar["high"] - bar["low"] > SKIP_RANGE_ATR * atr:
            continue
        fill = bar["close"] * (1 + SLIPPAGE)
        stop = fill - STOP_ATR * atr
        pos = {"entry_t": t, "entry": fill, "stop": stop, "risk": fill - stop, "atr": atr,
               "high_close": bar["close"], "trail": bar["close"] - TRAIL_ATR * atr}

    if pos and live:  # still open: today's low may already have hit the initial stop, else mark at the latest price
        if live["low"] <= pos["stop"]:
            close_trade(pos, min(live["open"], pos["stop"]), len(bars) - 1, "stop (today)", trades)
        else:
            close_trade(pos, live["close"], len(bars) - 1, "open", trades)
        trades[-1]["exit_time_override"] = live["time"]
        trades[-1]["days"] += 1
    elif pos:  # still open at the end of the period: close at the last close
        close_trade(pos, bars[-1]["close"], len(bars) - 1, "end of data", trades)
    for tr in trades:
        tr["entry_time"] = bars[tr["entry_t"]]["time"]
        tr["exit_time"] = tr.pop("exit_time_override", None) or bars[tr["exit_t"]]["time"]
    return trades


def close_trade(pos, price, t, reason, trades):
    fill = price * (1 - SLIPPAGE)
    fees = FEE * (pos["entry"] + fill)
    r = (fill - pos["entry"] - fees) / pos["risk"]
    trades.append({**pos, "exit_t": t, "exit": fill, "reason": reason, "result_r": r,
                   "fees_r": fees / pos["risk"], "days": t - pos["entry_t"]})


def stats(trades):
    trades = sorted(trades, key=lambda tr: (tr["exit_time"], tr["entry_time"]))
    n = len(trades)
    rs = [tr["result_r"] for tr in trades]
    total = peak = dd = 0.0
    for r in rs:
        total += r
        peak = max(peak, total)
        dd = max(dd, peak - total)
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r <= 0)
    top5 = sum(sorted(rs, reverse=True)[:5])
    return {
        "trades": n,
        "win_pct": round(100 * sum(1 for r in rs if r > 0) / n, 1) if n else 0.0,
        "avg_r": round(total / n, 3) if n else 0.0,
        "total_r": round(total, 2),
        "profit_factor": round(wins / losses, 2) if losses else None,
        "max_drawdown_r": round(dd, 2),
        "top5_r": round(top5, 2),
        "top5_share_pct": round(100 * top5 / total, 0) if total > 0 else None,
        "avg_days": round(sum(tr["days"] for tr in trades) / n, 1) if n else 0.0,
        "avg_fees_r": round(sum(tr["fees_r"] for tr in trades) / n, 3) if n else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default=",".join(SYMBOLS), help="symbols separated by commas (default: all 5)")
    parser.add_argument("--lookback", default=",".join(map(str, LOOKBACKS)), help="breakout lookbacks in days")
    parser.add_argument("--until", default=UNTIL,
                        help=f"use only days before this date, or 'live' for everything up to now (default {UNTIL})")
    parser.add_argument("--from", dest="start", help="allow entries only from this date (earlier days only warm up)")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]
    lookbacks = [int(x) for x in args.lookback.split(",")]

    data = {s: load_daily(daily_path(s), args.until) for s in symbols}
    period = f"{'from ' + args.start + ' ' if args.start else ''}" + ("up to now" if args.until == "live" else f"before {args.until}")
    print(f"Trend breakout, long only, daily bars {period}; filtered ATR({ATR_N}), "
          f"stop {STOP_ATR:g} ATR, trailing {TRAIL_ATR:g} ATR from the highest close, "
          f"fees {FEE:.1%} + slippage {SLIPPAGE:.2%} per side")
    print(f"'strat %' = total R x {RISK_PER_TRADE:.0%} risk per trade (simple sum, no compounding), "
          "next to buy-and-hold of the same symbol over the same days.\n")

    summary, all_rows = {}, []
    head = (f"{'symbol':<9}{'period':<25}{'trades':>7}{'win':>7}{'avg R':>8}{'total R':>9}{'PF':>6}"
            f"{'max DD':>8}{'top5 R':>8}{'top5 %':>8}{'days':>6}{'fee R':>7}{'strat %':>9}{'B&H %':>9}")
    for lb in lookbacks:
        print(f"Lookback {lb} days")
        print(head)
        everything, bh = [], []
        summary[lb] = {}
        for s in symbols:
            bars, live = data[s]
            trades = backtest(bars, lb, args.start, live)
            st = stats(trades)
            st["open"] = sum(1 for tr in trades if tr["reason"] == "open")
            # buy-and-hold over the same days: from the close before the first allowed day to the latest price
            first = next(k for k, b in enumerate(bars) if b["time"] >= args.start) - 1 if args.start else 0
            last_price = live["close"] if live else bars[-1]["close"]
            hold = 100 * (last_price / bars[first]["close"] - 1)
            shown_from = bars[first + 1]["time"] if args.start else bars[0]["time"]
            shown_to = live["time"] if live else bars[-1]["time"]
            bh.append(hold)
            st["buy_hold_pct"] = round(hold, 1)
            summary[lb][s] = {"from": shown_from, "to": shown_to, **st}
            everything += trades
            for tr in trades:
                all_rows.append({"lookback": lb, "symbol": s, "entry_time": tr["entry_time"],
                                 "exit_time": tr["exit_time"], "days": tr["days"],
                                 "entry": round(tr["entry"], 6), "initial_stop": round(tr["stop"], 6),
                                 "exit": round(tr["exit"], 6), "reason": tr["reason"],
                                 "fees_r": round(tr["fees_r"], 3), "result_r": round(tr["result_r"], 3)})
            print(line(s, f"{shown_from} - {shown_to}", st, hold))
        st = stats(everything)
        st["buy_hold_pct"] = round(sum(bh) / len(bh), 1)
        st["open"] = sum(1 for tr in everything if tr["reason"] == "open")
        summary[lb]["ALL"] = st
        print(line("ALL", f"{len(symbols)} symbols (B&H avg)", st, st["buy_hold_pct"]))
        print()

    suffix = "_oos" if args.start else ""
    with open(os.path.join("data", f"trend_breakout{suffix}_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()) if all_rows else ["lookback"])
        writer.writeheader()
        writer.writerows(all_rows)
    with open(os.path.join("data", f"trend_breakout{suffix}.json"), "w") as f:
        json.dump({"from": args.start, "until": args.until, "lookbacks": lookbacks, "results": summary}, f, indent=2)
    print(f"Saved data/trend_breakout{suffix}_trades.csv and data/trend_breakout{suffix}.json")


def line(name, period, st, hold):
    pf = st["profit_factor"] if st["profit_factor"] is not None else "n/a"
    share = f"{st['top5_share_pct']:.0f}%" if st["top5_share_pct"] is not None else "n/a"
    strat = st["total_r"] * RISK_PER_TRADE * 100
    return (f"{name:<9}{period:<25}{st['trades']:>7}{st['win_pct']:>6.1f}%{st['avg_r']:>+8.2f}{st['total_r']:>+9.2f}"
            f"{pf:>6}{st['max_drawdown_r']:>8.2f}{st['top5_r']:>+8.2f}{share:>8}{st['avg_days']:>6.0f}"
            f"{st['avg_fees_r']:>7.3f}{strat:>+8.0f}%{hold:>+8.0f}%")


if __name__ == "__main__":
    main()
