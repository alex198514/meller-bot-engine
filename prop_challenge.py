"""Prop challenge simulation: the long-only baseline trend breakout (lookback 20) as one 15-symbol portfolio.

Strategy: trend_breakout.backtest() unchanged on each symbol (original 5 + the 10 unseen ones), complete
daily bars up to yesterday. Every symbol's trade list is computed once; the account only decides which
of those trades it takes and how big. A trade still open on the last day stays open (marked, never exited).

Challenge (HashHedge 2-step, as specified):
  phase 1   target +5%, max total loss 10%
  phase 2   target +6%, max total loss 8%       (new account, flat: phase-1 positions are closed at the pass)
  both      daily loss limit 5% of the starting balance; at least 5 trading days; no time limit; leverage 1:5
  All checks on equity INCLUDING open positions at each daily close (UTC). On a day where a loss rule and
  the target are both met, the loss rule wins.
  daily loss  equity at the close below the day-start BALANCE (closed P&L only, HashHedge rule: open profit
              given back does not count, open losses do) by 5% of the starting balance or more
  max loss    equity at the close at or below start - 10% (phase 1) / - 8% (phase 2)
  trading day a day on which the account opens or closes at least one position

Account / sizing (all % of the phase's starting balance, which never changes):
  risk per trade  --risk (default 0.25, 0.5, 1): qty = risk / (entry fill - initial stop)
  open-risk cap   --cap  (default 4%): a new trade is skipped if the initial risk of all open positions plus
                  its own would exceed the cap (4% keeps even "every stop hit on one day" under the 5% daily limit)
  leverage        total notional at entry prices at most 5x the starting balance; a trade that would break it
                  is cut down to fit (skipped if nothing fits)
  Same-day entries are taken in symbol order (the 5 original symbols first). Exits are booked before entries.
  P&L per trade = its R (fees and slippage included, as in the backtest) x the risk taken.

Attempts: one starting at the first day of every month, 2018-01 .. the current month. An attempt still
running on the last day is reported as unfinished. Bull / bear year = BTC calendar-year close-to-close
return above / below zero (current year: to date), by the attempt's start month.

Usage: python3 prop_challenge.py [--risk 0.25,0.5,1] [--cap 4]
"""

import argparse
import json
import os
from statistics import median

from regime_breakout import UNSEEN
from trend_breakout import FEE, SLIPPAGE, SYMBOLS, backtest, daily_path, load_daily

LOOKBACK = 20
PHASES = ((0.05, 0.10), (0.06, 0.08))      # (target, max total loss) as fractions of the starting balance
DAILY_LOSS = 0.05
MIN_DAYS = 5
LEVERAGE = 5.0
CAP = 0.04                                 # default open-risk cap (also used by paper.py)
FIRST_YEAR = 2018


def load():
    symbols = list(SYMBOLS) + list(UNSEEN)
    bars = {s: load_daily(daily_path(s), "live")[0] for s in symbols}
    days = sorted({b["time"] for bs in bars.values() for b in bs})
    idx = {d: i for i, d in enumerate(days)}
    closes = {}
    for s, bs in bars.items():
        by_day, row, last = {b["time"]: b["close"] for b in bs}, [], None
        for d in days:
            last = by_day.get(d, last)        # forward-fill a missing day; None before the listing
            row.append(last)
        closes[s] = row
    entries = [[] for _ in days]
    for s in symbols:
        for tr in backtest(bars[s], LOOKBACK):
            still_open = tr["reason"] == "end of data"
            entries[idx[tr["entry_time"]]].append({
                "symbol": s, "ei": idx[tr["entry_time"]], "xi": None if still_open else idx[tr["exit_time"]],
                "entry": tr["entry"], "unit_risk": tr["risk"], "r": tr["result_r"]})
    return days, closes, entries, bars["BTCUSDT"]


def mark_r(tr, price):
    """R of `tr` if it were closed at `price` (same formula as trend_breakout.close_trade)."""
    fill = price * (1 - SLIPPAGE)
    return (fill - tr["entry"] - FEE * (tr["entry"] + fill)) / tr["unit_risk"]


def run_phase(start, target, max_loss, risk, cap, days, closes, entries):
    """('pass' | 'daily loss' | 'max loss' | 'unfinished', day index, trading days, trades, equity, min equity)."""
    realized, prev_equity, tdays, taken, open_pos, low = 0.0, 1.0, 0, 0, [], 1.0
    for i in range(start, len(days)):
        day_start_balance = 1.0 + realized               # HashHedge daily-loss base: closed P&L before today's exits
        traded = False
        for p in [p for p in open_pos if p["tr"]["xi"] == i]:
            realized += p["tr"]["r"] * p["risk"]
            open_pos.remove(p)
            traded = True
        for tr in entries[i]:
            if sum(p["risk"] for p in open_pos) + risk > cap + 1e-12:
                continue
            notional = risk / tr["unit_risk"] * tr["entry"]
            room = LEVERAGE - sum(p["notional"] for p in open_pos)
            scale = min(1.0, room / notional)
            if scale <= 0:
                continue
            open_pos.append({"tr": tr, "risk": risk * scale, "notional": notional * scale})
            taken += 1
            traded = True
        equity = 1.0 + realized + sum(mark_r(p["tr"], closes[p["tr"]["symbol"]][i]) * p["risk"] for p in open_pos)
        tdays += traded
        low = min(low, equity)
        if equity <= 1.0 - max_loss + 1e-12:
            return "max loss", i, tdays, taken, equity, low
        if day_start_balance - equity >= DAILY_LOSS - 1e-12:
            return "daily loss", i, tdays, taken, equity, low
        if equity >= 1.0 + target and tdays >= MIN_DAYS:
            return "pass", i, tdays, taken, equity, low
        prev_equity = equity
    return "unfinished", len(days) - 1, tdays, taken, prev_equity, low


def attempt(start, risk, cap, days, closes, entries):
    out = {"start": days[start]}
    i = start
    for n, (target, max_loss) in enumerate(PHASES, 1):
        result, end, tdays, taken, equity, low = run_phase(i, target, max_loss, risk, cap, days, closes, entries)
        out[f"p{n}"] = {"result": result, "end": days[end], "days": end - i + 1, "trading_days": tdays, "trades": taken,
                        "equity_pct": round(100 * (equity - 1), 2), "min_equity_pct": round(100 * (low - 1), 2)}
        if result != "pass":
            out["outcome"] = "unfinished" if result == "unfinished" else f"fail p{n}: {result}"
            return out
        i = end + 1
        if i >= len(days):
            out["p2"] = {"result": "unfinished", "end": days[-1], "days": 0, "trading_days": 0, "trades": 0,
                         "equity_pct": 0.0, "min_equity_pct": 0.0}
            out["outcome"] = "unfinished"
            return out
    out["outcome"] = "pass"
    out["days_total"] = sum(out[f"p{n}"]["days"] for n in (1, 2))
    return out


def summarize(atts):
    n = len(atts)
    pct = lambda k: round(100 * k / n, 1) if n else 0.0
    p1 = [a for a in atts if a["p1"]["result"] == "pass"]
    both = [a for a in atts if a["outcome"] == "pass"]
    fails = {}
    for a in atts:
        if a["outcome"].startswith("fail"):
            fails[a["outcome"][6:]] = fails.get(a["outcome"][6:], 0) + 1
    return {"attempts": n, "pass_p1_pct": pct(len(p1)), "pass_both_pct": pct(len(both)),
            "fail_pct": pct(sum(fails.values())), "fails": {k: pct(v) for k, v in sorted(fails.items())},
            "unfinished_pct": pct(sum(a["outcome"] == "unfinished" for a in atts)),
            "median_days_p1": median(a["p1"]["days"] for a in p1) if p1 else None,
            "median_days_both": median(a["days_total"] for a in both) if both else None}


def row(name, s):
    md = lambda v: f"{v:.0f}" if v is not None else "-"
    fails = ", ".join(f"{k} {v:.0f}%" for k, v in s["fails"].items()) or "-"
    return (f"  {name:<22}{s['attempts']:>4}{s['pass_p1_pct']:>8.0f}%{s['pass_both_pct']:>8.0f}%{s['fail_pct']:>7.0f}%"
            f"{s['unfinished_pct']:>7.0f}%{md(s['median_days_p1']):>8}{md(s['median_days_both']):>8}   {fails}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--risk", default="0.25,0.5,1", help="risk per trade in %% of the starting balance")
    parser.add_argument("--cap", type=float, default=100 * CAP, help="max total open initial risk in %% (default 4)")
    args = parser.parse_args()
    risks = [float(x) for x in args.risk.split(",")]
    cap = args.cap / 100

    days, closes, entries, btc = load()
    idx = {d: i for i, d in enumerate(days)}
    starts = [d for d in days if d.endswith("-01") and d >= f"{FIRST_YEAR}-01-01"]
    last12 = starts[-12:]

    year_close = {}
    for b in btc:
        year_close[b["time"][:4]] = b["close"]
    years = sorted(year_close)
    btc_year = {y: year_close[y] / year_close[years[k - 1]] - 1 for k, y in enumerate(years) if k}
    bull = {y for y, r in btc_year.items() if r > 0}

    print(f"Prop challenge, baseline trend breakout {LOOKBACK}d long only, {len(SYMBOLS) + len(UNSEEN)} symbols, "
          f"daily closes {days[0]} .. {days[-1]}")
    print(f"Phase 1 +5% / max loss 10%, phase 2 +6% / max loss 8%, daily loss 5%, min {MIN_DAYS} trading days, "
          f"leverage 1:{LEVERAGE:g}, open-risk cap {args.cap:g}%")
    print("BTC by year: " + ", ".join(f"{y} {100 * r:+.0f}% ({'bull' if y in bull else 'bear'})"
                                      for y, r in btc_year.items() if y >= str(FIRST_YEAR)))
    print(f"{len(starts)} attempts, one per month start {starts[0]} .. {starts[-1]}; "
          f"last 12 months = starts {last12[0]} .. {last12[-1]}\n")

    out = {"cap_pct": args.cap, "days": [days[0], days[-1]], "btc_year_return": btc_year, "results": {}}
    for risk in risks:
        atts = [attempt(idx[d], risk / 100, cap, days, closes, entries) for d in starts]
        groups = {"all": atts,
                  "bull-year starts": [a for a in atts if a["start"][:4] in bull],
                  "bear-year starts": [a for a in atts if a["start"][:4] not in bull],
                  "last 12 months": [a for a in atts if a["start"] in last12]}
        print(f"Risk {risk:g}% per trade")
        print(f"  {'':<22}{'n':>4}{'pass P1':>9}{'pass both':>10}{'fail':>7}{'unfin':>8}"
              f"{'d P1':>8}{'d both':>8}   failed by (phase: rule, % of attempts)")
        summary = {}
        for name, g in groups.items():
            summary[name] = summarize(g)
            print(row(name, summary[name]))
        print("  last 12 months, one by one:")
        for a in groups["last 12 months"]:
            p = a["p2"] if "p2" in a else a["p1"]
            phase = "p2" if "p2" in a else "p1"
            print(f"    {a['start']}  {a['outcome']:<18} ({phase} {p['days']} days, {p['trading_days']} trading days, "
                  f"{p['trades']} trades, last day {p['end']}, equity then {p['equity_pct']:+.1f}%, "
                  f"lowest {p['min_equity_pct']:+.1f}%)")
        print()
        out["results"][str(risk)] = {"summary": summary, "attempts": atts}

    with open(os.path.join("data", "prop_challenge.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("Saved data/prop_challenge.json   (days = calendar days from the attempt start)")


if __name__ == "__main__":
    main()
