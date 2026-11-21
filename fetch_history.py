"""Download 1-hour candles for a Binance symbol (default BTCUSDT).

Usage: python3 fetch_history.py [--symbol BTCUSDT] [--days 90] [--output data/btc_1h.csv]
  e.g. python3 fetch_history.py --days 1095 --output data/btc_1h_3y.csv   (3 years for the backtest)
       python3 fetch_history.py --symbol ETHUSDT --days 1095 --3y         (-> data/eth_1h_3y.csv)
       python3 fetch_history.py --symbol ETHUSDT --interval 1d --all       (-> data/eth_1d_all.csv)
The default output is data/<coin>_1h.csv, data/<coin>_1h_3y.csv with --3y,
or data/<coin>_<interval>_all.csv with --all (full history from the listing date).
"""

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from symbols import DEFAULT_SYMBOL, base, candles_path

# Main Binance host and the public market-data mirror (in case the first is geo-blocked)
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
INTERVALS_MS = {"1m": 60 * 1000, "5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}
DAYS = 90  # default
LIMIT = 1000  # Binance returns at most 1000 candles per request

HOUR_MS = 60 * 60 * 1000


def fetch_json(path, retries=3):
    """Try each host in turn and return the parsed JSON from the first one that works. Rate limited (HTTP 429 or the
    418 ban warning): wait Retry-After seconds (default 5, at most 60) and try again, up to `retries` times."""
    last_error = None
    for attempt in range(retries + 1):
        limited = 0
        for host in HOSTS:
            try:
                with urllib.request.urlopen(host + path, timeout=15) as res:
                    return json.load(res)
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code in (418, 429):
                    try:
                        limited = max(limited, min(60, int(e.headers.get("Retry-After") or 5)))
                    except ValueError:
                        limited = max(limited, 5)
            except Exception as e:
                last_error = e
        if not limited or attempt == retries:
            break
        print(f"Binance rate limit ({last_error}): waiting {limited} s")
        time.sleep(limited)
    raise RuntimeError(f"Binance unavailable: {last_error}")


def fetch_candles(symbol, start_ms, end_ms, interval="1h"):
    """Download all candles between start_ms and end_ms, 1000 at a time."""
    candles = []
    while start_ms < end_ms:
        path = (
            f"/api/v3/klines?symbol={symbol}&interval={interval}"
            f"&startTime={start_ms}&endTime={end_ms}&limit={LIMIT}"
        )
        batch = fetch_json(path)
        if not batch:
            break
        candles.extend(batch)
        # Continue right after the open time of the last candle we received
        start_ms = batch[-1][0] + INTERVALS_MS[interval]
        time.sleep(0.2)  # be polite to the API
    return candles


def save_csv(candles, path):
    """Write candles to a CSV file with columns: time, open, high, low, close, volume."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for k in candles:
            # k = [open_time, open, high, low, close, volume, close_time, ...]
            t = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            writer.writerow([t, k[1], k[2], k[3], k[4], k[5]])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=DAYS, help=f"how many days back to download (default {DAYS})")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help=f"Binance symbol (default {DEFAULT_SYMBOL})")
    parser.add_argument("--3y", dest="years3", action="store_true",
                        help="default output name for the backtest: data/<coin>_1h_3y.csv")
    parser.add_argument("--interval", choices=INTERVALS_MS, default="1h", help="candle interval (default 1h)")
    parser.add_argument("--all", action="store_true", help="full history from the listing date (ignores --days)")
    parser.add_argument("--output", help="CSV file to write (default data/<coin>_1h.csv)")
    args = parser.parse_args()
    args.symbol = args.symbol.upper()
    if args.all:
        output = args.output or os.path.join("data", f"{base(args.symbol)}_{args.interval}_all.csv")
    else:
        output = args.output or candles_path(args.symbol, args.years3)

    end_ms = int(time.time() * 1000)
    start_ms = 0 if args.all else end_ms - args.days * 24 * HOUR_MS  # 0: Binance starts at the first candle
    candles = fetch_candles(args.symbol, start_ms, end_ms, args.interval)
    save_csv(candles, output)
    print(f"Saved {len(candles)} {args.symbol} candles to {output}")


if __name__ == "__main__":
    main()
