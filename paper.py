"""Forward paper trading of trend_breakout.py: lookback 20, long only, HashHedge costs, two exit variants.

Symbols: 75 = our 14 HashHedge symbols plus the 61 coins of the new coins test. ETCUSDT is not on
HashHedge: it is retired (an open position would still close by the rules, then the symbol is dropped).
A symbol added later starts flat on the UTC day of the run that adds it: no past days are backfilled.

Two variants run side by side on every symbol, each with its own position (after a partial exit B can be
flat, and enter again, while A still holds):
  A  trend_breakout.backtest() unchanged: initial stop, exit at a close below the trailing stop.
  B  same entry, initial stop and trailing, plus take profits (variant B of the tp test): close 1/3 at
     +2R (TP1) and 1/3 at +4R (TP2), the rest by the trailing stop. From the day after TP1 the stop on
     the rest is the entry price (breakeven). Per day: stop first (initial or breakeven; a take profit on
     that day does not count), then the take profits (fill at the level, or at the open if it gapped
     above), then the close below the trailing stop, then the trailing update. B entries from 2026-11-08.
Pushes follow variant B (what is traded by hand), and only for trades the virtual challenge B takes.

Costs: 0.03% HashHedge taker fee per side, 0.05% slippage per side (as in the backtest), and the real
Binance USDT-M funding on the part of the position still open: on every run each open position adds the
funding paid at every funding time since the last run (rate x mark price, converted to R with the
position's stop distance; positive = the long pays). A position pays the funding times strictly after its
entry close and strictly before its exit day's close (same rule as the costs test).
If the futures API is blocked (GitHub's US runners get HTTP 451), funding is ESTIMATED at 0.01% per 8 hours
(00/08/16 UTC, at the day's open price) and marked as estimated. Once a month, when Binance's monthly
funding archive (data.binance.vision, published on the 1st) covers an estimated period, the estimate is
replaced by the real funding (at the day's open price; the archive has no mark price): the trade's journal
R, its open position, and the virtual challenges' balance/equity (if the trade belongs to the current
phase) are corrected, and the next daily summary push says how much R changed. Past challenge checks are
not re-run.

Each run:
  1. downloads the latest ~60 daily candles per symbol from Binance;
  2. keeps only fully closed daily candles (UTC; today's forming candle never gives signals);
  3. processes, in order, every closed day not processed yet, for variant A and variant B;
  4. adds the funding paid by every open position;
  5. appends every event to paper/journal.csv and saves the current state to paper/state.json;
  6. prints a short report (and sends it to Telegram if .env has TELEGRAM_TOKEN and TELEGRAM_CHAT_ID);
  7. runs the two virtual HashHedge 2-step challenges (see below);
  8. if NTFY_TOPIC is set (environment, else .env), pushes to ntfy (JSON publish, so titles may hold emoji
     and Cyrillic) HashHedge instructions in Russian for variant B, as numbered steps that follow the
     terminal's buttons, symbol as named in the HashHedge terminal, quantity in coins:
       "🟢 LONG <COIN>": a PNG signal card in signal-app style (1080x1350, Pillow, DejaVu Sans from fonts/):
         "LONG · 1D · R:R 1:x" (x = TP2 reward / risk from the live price) and the setup grade («сильный» if the
         breakout day closed in the top 25% of its range on volume above its 20-day average, else «обычный»);
         Вход (live price) | Стоп (with % from the entry); boxes Тейк 1 / Тейк 2 (% and price) / Тейк 3 трейлинг;
         the last 60 daily candles with entry, stop, TP1, TP2 tagged on the right price axis; one sentence of
         context (breakout, market light, volume); the size in coins (qty = $50 / (live - initial stop), cut to
         the HashHedge position cap: $1,000 on TNSR and 1INCH, $5,000 elsewhere; rounded down to 4 significant
         digits) and the margin at 5x. Attached with ntfy PUT; its message is one line: "🟢 LONG <COIN> · вход ·
         стоп · TP1 / TP2 / TP3" (also the text push if the card cannot be drawn or uploaded). The exchange
         setup stays as before: 33% TP1 + SL, 33% TP2 + SL, 34% SL only. "⏸ ПРОПУСК <COIN>" instead if the challenge B did not
         take the trade, or live <= stop, or live is more than 1 ATR above the entry fill;
       "🎯 TP1 <COIN>": move the SL of the two remaining parts to the entry price;
       "🎯 TP2 <COIN>": the last third keeps its SL, wait for the trailing exit;
       "🔴 ЗАКРЫТЬ <COIN> СЕЙЧАС": close what is left (daily close below the trailing stop);
       "⚪ <COIN>: сработал стоп": initial or breakeven stop hit, what to check;
       "⏸ <COIN>: пробой без входа": the day closed above the level but its range was above 2 filtered ATR, so B
         skipped the entry by its rules (the X.X ATR of that candle is in the message);
       "📊 Meller Bot: итог дня" whenever a new day was processed, as a PNG dashboard card (market light: BTC vs its
         200-day average, green above +3%, red below -3%, yellow between; challenges A and B with target /
         daily-loss / max-loss / trading-day bars; open B positions in R; the nearest breakouts, bars filling up
         as a coin gets closer; last run time) with a one-line message ("📊 Итог дня: сигналов нет · ближе всего
         INJ 7.9%"). Only if the card cannot be drawn or uploaded, the full text is pushed instead (the 5 flat symbols closest to their breakout
         level, one line per challenge, funding corrections, the SL to keep and the trailing level to watch for
         every followed position);
     and the challenge alerts (failed / phase passed / near a loss limit).
     The run that processes a Saturday also pushes "📅 Weekly report": an English PNG card for X posts (week N and
     its 7 closed days Sun..Sat, market light, challenges A and B: equity, % this week, % since the phase start,
     target progress; variant B entries and exits in R; the closest breakouts; "built with Claude Code ·
     @meller_ai"), once per week (state["weekly_sent"]). "% this week" uses state["equity_log"], the challenges'
     equity at each evaluated close (kept 35 days). A push of PUSH_LIMIT bytes or more
     is split at line ends into several, titled "(1/2)", "(2/2)".

Virtual challenges (same rules and sizing as prop_challenge.py), both on all 75 symbols, fresh from
2026-11-08 (the earlier ones are kept in state.json under challenge_archive): A takes variant A's trades,
B takes variant B's. Each: $10,000 starting balance per phase, 0.5% of it risked per trade (qty = risk /
(entry fill - initial stop)), skip a trade if open initial risk would exceed 4% (a B trade's risk counts 0
once its stop is at breakeven), total notional of the open parts at most 5x the balance and each position
at most its HashHedge cap (a trade is cut down to fit). Phase 1 target +5% / max loss 10%, phase 2 target
+6% / max loss 8%, daily loss 5% of the starting balance below the day-start BALANCE (HashHedge rule: closed
P&L only, so open profit given back does not count, open losses do), min 5 trading days
(days the account opens or closes a position or a part of one), no time limit. Every check is on equity
incl. open positions (and the funding they paid) at each daily close; a loss rule beats the target on the
same day. An account only takes its variant's OPEN events from its phase start on (same-day entries in
symbol order) and books their TP and CLOSE events at the journal's R. A passed phase closes its positions
at that close; phase 2 starts flat the next day. A failed attempt is followed by a new one starting the
next day. A day is evaluated only once every symbol has processed it.

Safe to run any number of times a day: each symbol remembers its last processed day in
state.json and a day is only ever processed once. Once the latest closed day is processed by every symbol
a run exits quietly (no push, no commit), unless --dry-run or --notify is given.

Watchdog (--watchdog OUTCOME, a separate step of the scheduled workflow): from WATCHDOG_HOUR UTC on, if the
latest closed day is not processed or its summary push failed (state["summary_push"]), it pushes
"⚠️ Meller Bot: сводка за сегодня не отправлена" with the reason, at most once per day (state["watchdog_sent"]).

Journal (column variant = A or B) actions:
  OPEN        entry; price = entry fill (close + slippage), stop = initial stop
  TRAIL       trailing stop raised; price = that day's close, stop = new trailing stop, R = open R of the trade
  TP1, TP2    (B) a third closed at the take profit; price = exit fill, stop = stop then, R = that third's R
  CLOSE_STOP  initial stop hit intraday; price = exit fill, stop = initial stop, R = R of the part closed
  CLOSE_BE    (B) breakeven stop hit; price = exit fill, stop = entry price, R = R of the part closed
  CLOSE_TRAIL close below the trailing stop; price = exit fill, stop = trailing stop, R = R of the part closed
  SKIP        breakout ignored, day's range above 2x the filtered ATR; price = close
A trade's result = the sum of its TP and CLOSE rows. R always includes fees, slippage and the funding paid
(funding not yet booked goes into the next TP or CLOSE row): 1R = entry fill - initial stop.

Usage: python3 paper.py [--notify] [--demo] [--demo-en] [--weekly-demo] [--watch] [--friend] [--export] [--dry-run] [--watchdog OUTCOME]
  --notify:  send the report to Telegram even if no new day
  --demo:    print and push one sample "DEMO 🟢 LONG BTC" with its card, then a DEMO dashboard card (live price, stop 2 ATR below), check the
             futures funding API is reachable; changes nothing
  --demo-en: push one English "EXAMPLE 🟢 LONG BTC" card: entry just above the 20-day high, stop 2 ATR below,
             TP1 +2R, TP2 +4R; changes nothing (real signals stay in Russian)
  --weekly-demo: push one sample "DEMO 📅 Weekly report" card from the saved state and journal; changes nothing
  --export:  only write site/data.json and site/news.json (the public web app's data; also written after every daily run that
             processed a day and every --watch run): per symbol the breakout level and its path for the next 10 days if no new
             highs come (display only), ATR, distance, last 60 daily
             candles and today's forming candle; open A/B positions; both challenges; the last 20 entries/exits;
             the market light. Built
             from a whitelist; never .env or the ntfy topic (the file is not written if a secret value would be in it)
  --watch:   intraday alerts only; reads state.json, never writes it. For every open A and B position, the hourly
             candles since its last processed daily close: high >= TP1 / TP2 not yet hit, low <= stop -> one push
             each, once per position. Every symbol B is flat on, within 3% below its 20-day high (live price) ->
             "👀 <COIN> в x% от входа", at most once per coin per UTC day, with a line on the 2 ATR candle filter:
             today's candle so far (high - low) in filtered ATRs, and whether a close above the level would be
             skipped (> 2 ATR) or give a BUY. Sent alerts: paper/alerts.json
             (forgotten when the position closes / the day ends). Nothing found -> no push.
             Intraday signal feed (a new strategy, stats still building; strategy B is not affected): the last closed
             1H and 4H candle of every symbol; close beyond the previous 20 candles' high (LONG) / low (SHORT), volume
             >= 1.5x their average, range < 2.5 ATR(14) -> "СИГНАЛ 4H · LONG <SYMBOL>" push with a card (entry =
             the close, stop 1.5 ATR, TP1 +1.5R, TP2 +3R, size for $50 risk, margin at 5x); none while the symbol has
             an open setup on that timeframe. Pushes: 1H and 4H, at most 3 per run in total (highest volume ratio
             first, the last one says how many more are in the app), none for a symbol pushed in the last 12 hours. Every setup and its outcome on 5m candles (stop first if both touched;
             half at TP1 then stop to breakeven, half at TP2; not closed within 24 hours -> closed at the close of the
             24th hour; R after 0.06% round trip):
             setups.json, committed by the workflow
  --dry-run: run everything, print the daily summary and every push it would send; saves nothing, sends nothing
  --watchdog OUTCOME: only the watchdog check; OUTCOME = result of the paper.py step (success, failure, ...)
"""

import argparse
import base64
import csv
import fcntl
import html
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from email.utils import parsedate_to_datetime

from fetch_history import fetch_candles, fetch_json
from prop_challenge import CAP, DAILY_LOSS, LEVERAGE, MIN_DAYS, PHASES
from regime_breakout import UNSEEN
from symbols import usd
from trend_breakout import SKIP_RANGE_ATR, SLIPPAGE, STOP_ATR, SYMBOLS, TRAIL_ATR, filtered_atr

RETIRED = ("ETCUSDT",)            # not on HashHedge: an open position still closes by the rules, then dropped
CURRENT_SYMBOLS = tuple(s for s in SYMBOLS + UNSEEN if s not in RETIRED)
NEW_SYMBOLS = tuple(c + "USDT" for c in (     # the 61 coins of the new coins test (Binance spot names)
    "SHIB AAVE LDO UNI ZEC BCH APT OP ACH ANKR APE API3 AR AUCTION BEL BICO CAKE CFX CHZ CKB COMP DASH DODO "
    "DUSK EGLD ENJ ENS FET FIL GMT GMX GRT HBAR ICP ILV IMX INJ IOST JASMY JOE LPT LSK MANA MASK NEO ONG "
    "PEOPLE POLYX ROSE RSR RUNE SAND SPELL STX TRB UMA VET WOO YGG ZRX 1INCH").split())
PAPER_SYMBOLS = CURRENT_SYMBOLS + NEW_SYMBOLS
# Intraday scanner + web app: every HashHedge crypto instrument ("Instruments and position limits" page, 135 crypto
# rows on 2026-11-15) with a TRADING Binance USDT spot pair (exchangeInfo, 2026-11-15) = 126. Not on Binance spot:
# XMR, LIT, RIVER, LAB, UB, BSV, MON, RATS, ZETA (LIT on Binance is another coin). Strategy B keeps PAPER_SYMBOLS.
HH_CRYPTO = tuple((
    "BTC DOGE ETH PEPE SHIB SOL XRP LTC ADA BNB BONK FLOKI LINK TRX XLM AAVE TRUMP LDO UNI WIF ASTER "
    "HYPE TAO DOT SUI ZEC AVAX BCH PUMP VIRTUAL APT OP JUP TIA ARB WLFI ACE ACH AEVO ALT ANKR APE API3 "
    "AR ARKM ATOM AUCTION BEAMX BEL BICO BIGTIME BLUR BOME CAKE CATI CFX CHZ CKB COMP CYBER DASH DODOX "
    "DUSK DYM EDU EGLD ENA ENJ ENS ETHFI FET FIL GAS GMT GMX GRT HBAR HMSTR ICP ID ILV IMX INJ IOST "
    "JASMY JOE JTO LINEA LPT LQTY LSK MANA MANTA MASK MAV METIS NEO ONDO ONG ORDI PENDLE PEOPLE POLYX "
    "PYTH ROSE RSR RUNE SAGA SAND SEI SPELL SSV STRK STX TRB UMA USTC VET W WLD WOO XAI YGG ZRX TNSR "
    "1INCH "
    ).split())
SCANNER_SYMBOLS = PAPER_SYMBOLS + tuple(s for s in ({"DODOX": "DODO"}.get(c, c) + "USDT" for c in HH_CRYPTO)
                                        if s not in PAPER_SYMBOLS)
TPS = {"A": (), "B": ((2.0, 1 / 3), (4.0, 1 / 3))}       # take profits: (R multiple, fraction of the position)
PARTS_PCT = (33, 33, 34)                                  # the B parts as entered in «Частичная позиция»
POS_KEY = {"A": "position", "B": "position_b"}
CHALLENGES = (("challenge", "A"), ("challenge_b", "B"))   # (state key, name = variant it trades)
CHALLENGE_SETUP = "2026-11-08: A = 75 symbols trailing only, B = 75 symbols TP 1/3 @2R, 1/3 @4R, rest trailing"
HH_NAME = {"DODOUSDT": "DODOXUSDT"}                       # HashHedge terminal name where it differs from spot
FUTURES = {"SHIBUSDT": ("1000SHIBUSDT", 1000), "DODOUSDT": ("DODOXUSDT", 1)}   # (Binance futures, coins per unit)
POS_CAP = {"TNSRUSDT": 1_000.0, "1INCHUSDT": 1_000.0}    # HashHedge max position in $; every other symbol:
POS_CAP_DEFAULT = 5_000.0                                # at least $5,000, so $5,000 is used
HH_FEE = 0.0003                   # HashHedge taker fee per side (trend_breakout.FEE stays 0.1% for the backtests)
FAPI = "https://fapi.binance.com/fapi/v1/fundingRate"
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{fut}/{fut}-fundingRate-{month}.zip"
EST_RATE = 0.0001                 # funding estimate when the futures API is blocked: 0.01% per 8 hours
H8_MS = 8 * 60 * 60 * 1000
LOOKBACK = 20
CH_BALANCE = 10_000.0             # virtual challenges: starting balance of every phase
CH_RISK = 0.005                   # 0.5% of the starting balance per trade
CH_NEAR = 0.01                    # alert when equity is within 1% of the starting balance of a loss limit
HISTORY_DAYS = 61                 # 60 closed days: the 20-day high, the 14-day ATR and the BUY card chart
PAPER_DIR = "paper"
JOURNAL = os.path.join(PAPER_DIR, "journal.csv")
STATE = os.path.join(PAPER_DIR, "state.json")
LOCK = os.path.join(PAPER_DIR, ".lock")
ALERTS = os.path.join(PAPER_DIR, "alerts.json")
SITE_DATA = os.path.join("site", "data.json")        # public web app data (published to GitHub Pages)
SITE_NEWS = os.path.join("site", "news.json")        # public headlines for the web app (titles and links only)
SECRET_ENV = ("NTFY_TOPIC", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "PAGES_TOKEN", "GITHUB_TOKEN")    # --watch: alerts already sent (state.json is never written)
NEAR_PCT = 3.0                    # --watch: flat symbol within this % below its breakout level
JOURNAL_FIELDS = ["date", "symbol", "action", "price", "stop", "R", "variant"]
DAY_MS = 24 * 60 * 60 * 1000
DRY_RUN = False                   # --dry-run: ntfy() and telegram() only print
WATCHDOG_HOUR = 8                 # UTC; GitHub can start a cron hours late, so any scheduled run from this hour on
WATCHDOG_TITLE = "⚠️ Meller Bot: сводка за сегодня не отправлена"
PUSH_LIMIT = 3500                 # every push stays under this many UTF-8 bytes (ntfy's own limit is 4096)
NEAREST_BREAKOUTS = 5             # symbols listed in the daily summary
RULE_RU = {"max loss": "макс. убыток", "daily loss": "дневной убыток"}


def day_str(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def next_day(d):
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def prev_day(d):
    return (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def close_ms(d):
    """Time of the daily close of day `d` (00:00 UTC of the next day), in ms."""
    return int(datetime.strptime(next_day(d), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def px(p):
    """usd() for normal prices; 4 significant digits below $0.01 (usd() would round SHIB's $0.0000115 to $0.000012)."""
    if abs(p) >= 0.01:
        return usd(p)
    return "$" + format(Decimal(f"{p:.4g}"), "f")


def hh_name(symbol):
    return HH_NAME.get(symbol, symbol)


def coin_of(symbol):
    return hh_name(symbol).removesuffix("USDT")


def pos_cap(symbol):
    return POS_CAP.get(symbol, POS_CAP_DEFAULT)


TODAY_BAR = {}                    # symbol -> today's forming daily candle, kept by download() for the watch alerts


def download(symbol, now_ms):
    """Closed daily bars (oldest first) and the latest price from today's forming candle (also kept in TODAY_BAR)."""
    raw = fetch_candles(symbol, now_ms - HISTORY_DAYS * DAY_MS, now_ms, "1d")
    bars, live = [], None
    for k in raw:   # k = [open_time, open, high, low, close, volume, close_time, ...]
        bar = {"time": day_str(k[0]), "open": float(k[1]), "high": float(k[2]),
               "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        if k[6] < now_ms:
            bars.append(bar)
        else:
            live = bar   # still forming: only used for the report and the watch alerts
            TODAY_BAR[symbol] = bar
    for a, b in zip(bars, bars[1:]):
        if next_day(a["time"]) != b["time"]:
            raise RuntimeError(f"{symbol}: gap in daily candles between {a['time']} and {b['time']}")
    return bars, (live["close"] if live else bars[-1]["close"])


def mark(pos, price):
    """(exit fill, R of the whole position) if closed at `price`: trend_breakout.close_trade's formula with
    the HashHedge fee; funding not included."""
    fill = price * (1 - SLIPPAGE)
    return fill, (fill - pos["entry"] - HH_FEE * (pos["entry"] + fill)) / pos["risk"]


def unbooked(pos):
    """Funding R paid but not yet in a TP or CLOSE row."""
    return pos.get("funding_r", 0.0) - pos.get("funding_booked", 0.0)


def open_r(pos, price):
    """The trade's R if what is left were closed at `price` now: parts already closed + the open part,
    funding paid so far included."""
    return pos.get("booked_r", 0.0) + pos.get("rem", 1.0) * mark(pos, price)[1] - unbooked(pos)


def book(pos, frac, price):
    """Close `frac` of the original position at `price`; returns that part's R (with the funding not booked yet)."""
    r = frac * mark(pos, price)[1] - unbooked(pos)
    pos["funding_booked"] = pos.get("funding_r", 0.0)
    pos["booked_r"] = pos.get("booked_r", 0.0) + r
    pos["rem"] = pos.get("rem", 1.0) - frac
    return r


# ---------- funding ----------

_funding_cache = {}
_fapi_blocked = []                # set after the first failure: no more futures API calls this run


def fetch_funding(symbol, start_ms, end_ms):
    """[(time ms rounded to the minute, rate, mark price per coin or None)] from Binance USDT-M futures."""
    fut, per_unit = FUTURES.get(symbol, (symbol, 1))
    out, start = [], start_ms
    while True:
        url = f"{FAPI}?symbol={fut}&startTime={start}&endTime={end_ms}&limit=1000"
        with urllib.request.urlopen(url, timeout=15) as res:
            batch = json.load(res)
        for x in batch:
            mp = float(x["markPrice"]) / per_unit if x.get("markPrice") not in (None, "") and float(x["markPrice"]) > 0 else None
            out.append((round(x["fundingTime"] / 60000) * 60000, float(x["fundingRate"]), mp))
        if len(batch) < 1000:
            return out
        start = batch[-1]["fundingTime"] + 1


def accrue_funding(symbol, pos, until_ms, now_ms, price_at):
    """Add to `pos` the funding paid on its open part strictly after pos['funding_through_ms'] and strictly
    before `until_ms`. If the futures API is blocked: estimate 0.01% per 8 hours instead, remembered in
    pos['funding_est'] as [from_ms, to_ms, estimated R, open part] windows (stamps from < t <= to)."""
    pos.setdefault("funding_r", 0.0)
    pos.setdefault("funding_days", {})
    pos.setdefault("funding_through_ms", close_ms(pos["entry_date"]))
    rem = pos.get("rem", 1.0)
    a = pos["funding_through_ms"]
    if until_ms <= a + 1:
        return
    cached = _funding_cache.get(symbol)
    if (not cached or cached[0] > a + 1) and not _fapi_blocked:
        try:
            _funding_cache[symbol] = cached = (a + 1, fetch_funding(symbol, a + 1, now_ms))
        except Exception as e:
            _fapi_blocked.append(f"{type(e).__name__}: {e}")
            print(f"Futures funding API not available ({_fapi_blocked[0]}): funding estimated at "
                  f"{100 * EST_RATE:g}% per 8h this run, corrected from Binance's monthly archive later")
    if cached and cached[0] <= a + 1:
        for t, rate, price in cached[1]:
            if a < t < until_ms:
                pos["funding_r"] += rem * rate * (price or price_at(t)) / pos["risk"]
                pos["funding_days"][day_str(t)] = round(pos["funding_r"], 6)   # cumulative R through that UTC day
                pos["funding_through_ms"] = max(pos["funding_through_ms"], t)
        return
    b = min(until_ms - 1, now_ms)                     # estimate: stamps at 00/08/16 UTC, a < t <= b
    windows = pos.setdefault("funding_est", [])
    lo = a
    while lo < b:                                     # one window per calendar month (one archive file each)
        m = datetime.strptime(day_str(lo + 1)[:7] + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
        nxt = int((m.replace(year=m.year + 1, month=1) if m.month == 12 else m.replace(month=m.month + 1)).timestamp() * 1000)
        hi = min(b, nxt - 1)
        est, t = 0.0, (lo // H8_MS + 1) * H8_MS
        while t <= hi:
            inc = rem * EST_RATE * price_at(t) / pos["risk"]
            est += inc
            pos["funding_r"] += inc
            pos["funding_days"][day_str(t)] = round(pos["funding_r"], 6)
            t += H8_MS
        w = windows[-1] if windows else None
        if w and w[1] == lo and day_str(w[0] + 1)[:7] == day_str(hi)[:7] and (w[3] if len(w) > 3 else 1.0) == rem:
            w[1], w[2] = hi, w[2] + est
        else:
            windows.append([lo, hi, est, rem])
        lo = hi
    pos["funding_through_ms"] = b


def funding_est_r(pos):
    return sum(w[2] for w in pos.get("funding_est", []))


_archive_cache = {}


def archive_funding(symbol, month):
    """Real funding of one month from Binance's public archive: [(time ms, rate)], or None if not published yet."""
    fut, _ = FUTURES.get(symbol, (symbol, 1))
    if (fut, month) not in _archive_cache:
        try:
            with urllib.request.urlopen(ARCHIVE.format(fut=fut, month=month), timeout=30) as res:
                data = res.read()
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            _archive_cache[(fut, month)] = None
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            rows = csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), "utf-8"))
            _archive_cache[(fut, month)] = [(round(int(r["calc_time"]) / 60000) * 60000, float(r["last_funding_rate"]))
                                            for r in rows]
    return _archive_cache[(fut, month)]


def real_window_r(symbol, a, b, risk):
    """Real funding R of a whole position at archive stamps a < t <= b (price: the day's spot open), or None
    if a month is not published yet."""
    months = sorted({day_str(a + 1)[:7], day_str(b)[:7]} |
                    {day_str(t)[:7] for t in range(a + 1, b + 1, 24 * 60 * 60 * 1000)})
    recs = []
    for m in months:
        got = archive_funding(symbol, m)
        if got is None:
            return None
        recs += [x for x in got if a < x[0] <= b]
    if not recs:
        return 0.0
    opens = {day_str(k[0]): float(k[1]) for k in fetch_candles(symbol, a - DAY_MS, b + DAY_MS, "1d")}
    return sum(rate * opens[day_str(t)] / risk for t, rate in recs if day_str(t) in opens)


def correct_funding(state, journal):
    """Replace estimated funding with the archive's real funding wherever the archive covers it. Corrects
    open positions, closed trades' journal R (in `journal`, on the trade's CLOSE row) and the challenges.
    Returns (rows changed?, note)."""
    fixes = []                                   # (symbol, entry_date, variant, estimated R, real R, window end)
    def fix_windows(symbol, entry_date, variant, risk, windows):
        keep = []
        for w in windows:
            a, b, est = w[:3]
            rem = w[3] if len(w) > 3 else 1.0
            try:
                real = real_window_r(symbol, a, b, risk)
            except Exception as e:
                print(f"{symbol}: funding archive not readable ({type(e).__name__}: {e}); retried next run")
                real = None
            if real is None:
                keep.append(w)
            else:
                fixes.append((symbol, entry_date, variant, est, rem * real, b))
        return keep

    for s, st in state["symbols"].items():
        for v, key in POS_KEY.items():
            p = st.get(key)
            if p and p.get("funding_est"):
                n = len(fixes)
                p["funding_est"] = fix_windows(s, p["entry_date"], v, p["risk"], p["funding_est"])
                for *_, est, real, b in fixes[n:]:
                    p["funding_r"] += real - est
                    for d in p["funding_days"]:
                        if d >= day_str(b):
                            p["funding_days"][d] = round(p["funding_days"][d] + real - est, 6)
    rows_changed = False
    for item in state.get("funding_pending", []):
        n = len(fixes)
        v = item.get("variant", "A")
        item["windows"] = fix_windows(item["symbol"], item["entry_date"], v, item["risk"], item["windows"])
        delta = sum(real - est for *_, est, real, _ in fixes[n:])
        if fixes[n:]:
            for r in journal:
                if ((r["symbol"], r["date"], r.get("variant", "A")) == (item["symbol"], item["close_date"], v)
                        and r["action"].startswith("CLOSE")):
                    r["R"] = round(float(r["R"]) - delta, 3)
                    rows_changed = True
    state["funding_pending"] = [i for i in state.get("funding_pending", []) if i["windows"]]
    if not fixes:
        return False, None

    by_trade = {}
    for s, entry_date, v, est, real, _ in fixes:
        by_trade[(s, entry_date, v)] = by_trade.get((s, entry_date, v), 0.0) + real - est
    for key, name in CHALLENGES:
        ch = state.get(key)
        if not ch or ch["status"] != "active":
            continue
        hit = [(c["risk_usd"], by_trade[(c["symbol"], c["entry_date"], name)]) for c in ch.get("closed", [])
               if (c["symbol"], c["entry_date"], name) in by_trade]
        hit += [(p["risk_usd"], by_trade[(s, p["entry_date"], name)]) for s, p in ch["positions"].items()
                if (s, p["entry_date"], name) in by_trade]
        usd_change = -sum(risk_usd * d for risk_usd, d in hit)
        for c in [c for c in ch.get("closed", []) if (c["symbol"], c["entry_date"], name) in by_trade]:
            ch["balance"] += -by_trade[(c["symbol"], c["entry_date"], name)] * c["risk_usd"]
        ch["equity"] = round(ch["equity"] + usd_change, 2)
        ch["prev_close_equity"] = round(ch["prev_close_equity"] + usd_change, 2)
        set_limits(ch)
    est_total, real_total = sum(f[3] for f in fixes), sum(f[4] for f in fixes)
    note = (f"Коррекция фандинга (месячный архив Binance): сделок {len(by_trade)}, оценка {est_total:.3f}R "
            f"заменена реальным {real_total:.3f}R, результат изменился на {est_total - real_total:+.3f}R")
    print(note)
    return rows_changed, note


def unbooked_at(state, symbol, entry_date, day, variant):
    """Funding R the symbol's variant position (opened on `entry_date`) had paid by the close of `day`
    and not yet booked in a TP or CLOSE row."""
    p = state["symbols"].get(symbol, {}).get(POS_KEY[variant])
    if not p or p["entry_date"] != entry_date:
        return 0.0
    days = [d for d in p.get("funding_days", {}) if d <= day]
    return max(0.0, (p["funding_days"][max(days)] if days else 0.0) - p.get("funding_booked", 0.0))


# ---------- strategy ----------

def event(day, symbol, action, price, stop=None, r=None, variant="A"):
    return {"date": day, "symbol": symbol, "action": action, "price": round(price, 8),
            "stop": "" if stop is None else round(stop, 8), "R": "" if r is None else round(r, 3), "variant": variant}


def process_day(symbol, pos, bars, t, fund, variant, may_enter=True):
    """One closed day for one variant. A: the trend_breakout.backtest() rules; B: the same plus the take
    profits and the breakeven stop. Returns (position, events). fund(pos, until_ms) adds the funding paid
    before `until_ms` (the rules never depend on it)."""
    bar, day = bars[t], bars[t]["time"]
    atr = filtered_atr(bars, t)
    tps = TPS[variant]

    if pos:
        pos.setdefault("rem", 1.0)
        pos.setdefault("hit", [])
        pos.setdefault("be", False)
        if bar["low"] <= pos["stop"]:                                   # 1. stop (initial / breakeven), first
            fund(pos, close_ms(day))
            price = min(bar["open"], pos["stop"])
            action = "CLOSE_BE" if pos["be"] else "CLOSE_STOP"
            return None, [event(day, symbol, action, mark(pos, price)[0], pos["stop"], book(pos, pos["rem"], price), variant)]
        events = []
        for k, (mult, frac) in enumerate(tps):                          # 2. take profits (B)
            level = pos["tp"][k]
            if k not in pos["hit"] and bar["high"] >= level:
                fund(pos, close_ms(day))
                pos["hit"].append(k)
                price = max(bar["open"], level)
                events.append(event(day, symbol, f"TP{k + 1}", mark(pos, price)[0], pos["stop"],
                                    book(pos, min(frac, pos["rem"]), price), variant))
        if pos["trail"] is not None and bar["close"] < pos["trail"]:    # 3. close below the trailing stop
            fund(pos, close_ms(day))
            events.append(event(day, symbol, "CLOSE_TRAIL", mark(pos, bar["close"])[0], pos["trail"],
                                book(pos, pos["rem"], bar["close"]), variant))
            return None, events
        pos["high_close"] = max(pos["high_close"], bar["close"])        # 4. raise the trailing stop
        if atr is not None:
            level = pos["high_close"] - TRAIL_ATR * atr
            if pos["trail"] is None or level > pos["trail"]:
                pos["trail"] = level
                fund(pos, close_ms(day))
                events.append(event(day, symbol, "TRAIL", bar["close"], level, open_r(pos, bar["close"]), variant))
        if pos["hit"] and not pos["be"]:                                # 5. breakeven from the day after TP1
            pos["be"], pos["stop"] = True, max(pos["stop"], pos["entry"])
        return pos, events

    if not may_enter:
        return None, []
    if t < LOOKBACK or atr is None:
        raise RuntimeError(f"{symbol}: not enough history before {day}")
    prior_high = max(b["high"] for b in bars[t - LOOKBACK:t])
    if bar["close"] <= prior_high:
        return None, []
    if bar["high"] - bar["low"] > SKIP_RANGE_ATR * atr:
        return None, [event(day, symbol, "SKIP", bar["close"], variant=variant)]
    fill = bar["close"] * (1 + SLIPPAGE)
    stop = fill - STOP_ATR * atr
    pos = {"entry_date": day, "entry": fill, "stop": stop, "risk": fill - stop, "atr": atr,
           "high_close": bar["close"], "trail": bar["close"] - TRAIL_ATR * atr,
           "rem": 1.0, "hit": [], "be": False, "booked_r": 0.0, "tp": [fill + m * (fill - stop) for m, _ in tps],
           "funding_r": 0.0, "funding_booked": 0.0, "funding_through_ms": close_ms(day), "funding_days": {}}
    return pos, [event(day, symbol, "OPEN", fill, stop, 0.0, variant)]


def watch(bars):
    """What the next closed day needs for an entry: close above this level, range at most 2x this ATR."""
    t = len(bars)
    return {"day": next_day(bars[-1]["time"]),
            "breakout_above": max(b["high"] for b in bars[t - LOOKBACK:t]),
            "atr": filtered_atr(bars, t)}


# ---------- journal and state ----------

def read_journal():
    if not os.path.exists(JOURNAL):
        return []
    with open(JOURNAL, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["variant"] = r.get("variant") or "A"       # rows from before the variant column are variant A
    return rows


def jkey(r):
    return r["date"], r["symbol"], r["action"], r.get("variant") or "A"


def write_journal(rows):
    """Rewrite the whole journal (funding correction, or the one-time upgrade to the variant column)."""
    tmp = JOURNAL + ".tmp"
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        writer.writeheader()
        writer.writerows({k: r.get(k, "") for k in JOURNAL_FIELDS} for r in rows)
    os.replace(tmp, JOURNAL)


def append_journal(rows):
    """Append, skipping rows already there (in case a previous run died between journal and state)."""
    existing_rows = read_journal()
    if os.path.exists(JOURNAL):
        with open(JOURNAL, newline="") as f:
            if "variant" not in (next(csv.reader(f), []) or []):
                write_journal(existing_rows)         # one-time upgrade: add the variant column
    existing = {jkey(r) for r in existing_rows}
    rows = [r for r in rows if jkey(r) not in existing]
    new_file = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def journal_with(new_events):
    """The journal plus this run's events not written yet (all of them under --dry-run)."""
    rows = read_journal()
    existing = {jkey(r) for r in rows}
    return rows + [e for e in new_events if jkey(e) not in existing]


def closed_stats(journal, variant):
    """(closed trades, total R) of a variant: a trade's result is the sum of its TP and CLOSE rows."""
    rows = [r for r in journal if r.get("variant", "A") == variant]
    n = sum(1 for r in rows if r["action"].startswith("CLOSE"))
    return n, sum(float(r["R"]) for r in rows if r["action"].startswith(("CLOSE", "TP")) and r["R"] != "")


def trade_total(journal, symbol, variant, entry_date, through_date):
    """Result so far of one trade: its TP and CLOSE rows from the entry day on."""
    return sum(float(r["R"]) for r in journal
               if r["symbol"] == symbol and r.get("variant", "A") == variant and entry_date <= r["date"] <= through_date
               and r["action"].startswith(("CLOSE", "TP")) and r["R"] != "")


def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE)   # atomic: never a half-written state.json


def report(state, prices, new_events, processed):
    lines = [f"Paper · trend breakout {LOOKBACK}d, long only, HashHedge costs · A trailing / B TP 2R+4R · "
             f"since {state['start_date']}"]
    days = {}
    for s, d in processed:
        days.setdefault(s, []).append(d)
    lines.append("Processed: " + (", ".join(f"{s} {d[0]}" + (f"..{d[-1]}" if len(d) > 1 else "")
                                            for s, d in days.items()) if processed else
                                  "nothing new (every closed day already processed)"))

    for v, key in POS_KEY.items():
        lines.append(f"\nOpen positions {v}:")
        open_syms = [s for s, st in state["symbols"].items() if st.get(key)]
        for s in open_syms:
            p = state["symbols"][s][key]
            r_txt = f"{open_r(p, prices[s]):+.2f}R" if s in prices else "n/a"
            part = f"  {round(100 * p.get('rem', 1)):.0f}% open" if p.get("rem", 1) < 0.999 else ""
            lines.append(f"  {s:<8} since {p['entry_date']}  entry {px(p['entry'])}  now {px(prices.get(s, p['entry']))}"
                         f"  stop {px(p['stop'])}  trail {px(p['trail'])}  {r_txt}{part} (funding {p.get('funding_r', 0):.3f}R"
                         + (f", {funding_est_r(p):.3f}R of it estimated)" if p.get("funding_est") else ")"))
        if not open_syms:
            lines.append("  none")

    lines.append("\nNew signals:")
    for e in new_events:
        if e["action"] != "TRAIL":
            extra = (f" stop {px(e['stop'])}" if e["stop"] != "" and e["action"] == "OPEN" else
                     f" {e['R']:+.2f}R" if e["R"] != "" and e["action"] != "OPEN" else "")
            lines.append(f"  {e['date']} {e['variant']} {e['symbol']:<8} {e['action']:<11} {px(e['price'])}{extra}")
    if not any(e["action"] != "TRAIL" for e in new_events):
        lines.append("  none")

    lines.append("\nWatch (flat symbols, entry needs a daily close above):")
    for s, st in state["symbols"].items():
        w = st.get("watch")
        if st.get("position") or st.get("position_b") or not w:
            continue
        dist = 100 * (w["breakout_above"] / prices[s] - 1) if s in prices else None
        dist_txt = f"{dist:+.1f}% away" if dist is not None else ""
        lines.append(f"  {s:<8} {w['day']}  > {px(w['breakout_above'])}  (now {px(prices.get(s, 0))}, {dist_txt})")

    journal = journal_with(new_events)
    pending = state.get("funding_pending", [])
    for v in POS_KEY:
        n, total = closed_stats(journal, v)
        lines.append(("\n" if v == "A" else "") + f"Closed trades {v}: {n}, total {total:+.2f}R")
    if pending:
        lines.append(f"({len(pending)} closed trades with estimated funding, corrected from the monthly archive)")
    for note in state.get("funding_notes", []):
        lines.append(note)

    for key, name in CHALLENGES:
        ch = state.get(key)
        if not ch:
            continue
        lines.append(f"\nVirtual challenge {name} (variant {name}, {len(PAPER_SYMBOLS)} symbols, ${ch['start_balance']:,.0f}, "
                     f"{ch['risk_pct']:g}% risk/trade, cap {ch['cap_pct']:g}%; evaluated through {ch['last_day']}):")
        lines.append("  " + challenge_line(ch))
        if ch["status"] == "active":
            lines.append(f"  balance ${ch['balance']:,.2f}, positions {len(ch['positions'])}, open risk ${ch['open_risk']:,.2f}; "
                         f"floors: max loss ${ch['max_loss_floor']:,.2f}, daily ${ch['daily_loss_floor']:,.2f}")
        for h in state.get(key + "_history", [])[-3:]:
            lines.append(f"  #{h['attempt']} {h['result']} on {h['end']} (equity ${h['equity']:,.2f})")
    return "\n".join(lines)


# ---------- notifications ----------

def load_env(path=".env"):
    if not os.path.exists(path):
        return {}
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def telegram(text):
    """Send `text` if .env has TELEGRAM_TOKEN and TELEGRAM_CHAT_ID; silently do nothing otherwise."""
    env = load_env()
    token, chat = env.get("TELEGRAM_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat or DRY_RUN:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()   # Telegram limit: 4096
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15)
    except Exception as e:  # a notifier problem must never break the paper run
        print(f"(Telegram not sent: {type(e).__name__})")


def split_push(text, limit=PUSH_LIMIT):
    """`text` cut into pieces of fewer than `limit` UTF-8 bytes, at line ends (inside a line only if it alone is too long)."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line.encode()) >= limit:
            head = line.encode()[:limit - 1].decode(errors="ignore")    # never cuts a character in two
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(head)
            line = line[len(head):]
        joined = f"{cur}\n{line}" if cur else line
        if len(joined.encode()) >= limit:
            parts.append(cur)
            cur = line
        else:
            cur = joined
    return parts + [cur] if cur or not parts else parts


def ntfy(title, text):
    """Push `text` to ntfy, split if needed so that every push is under PUSH_LIMIT bytes.
    Returns None if everything was sent, else the first error text."""
    parts = split_push(text)
    errors = [ntfy_one(f"{title} ({i}/{len(parts)})" if len(parts) > 1 else title, part)
              for i, part in enumerate(parts, 1)]
    return next((e for e in errors if e), None)


def ntfy_one(title, text):
    """One push to topic NTFY_TOPIC (environment first, else .env). Every attempt prints one log line
    (title, message size in bytes, HTTP status or the error). Returns None if sent, else the error text."""
    size = len(text.encode("utf-8"))
    if DRY_RUN:
        print(f"\n--- dry run, not pushed: {title} ({size} bytes) ---\n{text}")
        return None
    topic = os.environ.get("NTFY_TOPIC") or load_env().get("NTFY_TOPIC")
    if not topic:
        print(f"ntfy: {title} ({size} bytes) -> ERROR NTFY_TOPIC is not set")
        return "NTFY_TOPIC is not set"
    body = json.dumps({"topic": topic, "title": title, "message": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=body, headers={"Content-Type": "application/json"},
                                 method="POST")      # JSON publish: the title may hold emoji and Cyrillic
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"ntfy: {title} ({size} bytes) -> HTTP {resp.status}")
        return None
    except Exception as e:  # a notifier problem must never break the paper run
        error = f"{type(e).__name__}: {e}"
        print(f"ntfy: {title} ({size} bytes) -> ERROR {error}")
        return error


def round_down_sig(x, digits=4):
    """`x` rounded DOWN to `digits` significant digits, as a plain decimal string (no exponent)."""
    d = Decimal(repr(x))
    step = Decimal(1).scaleb(d.adjusted() - digits + 1)
    return format(d.quantize(step, rounding=ROUND_DOWN), "f")


def buy_size(symbol, live, stop):
    """(qty to type as a string, raw qty, cut to the position cap?, notional at `live`) of a variant-B buy."""
    raw_qty = CH_RISK * CH_BALANCE / (live - stop)
    capped = raw_qty * live > pos_cap(symbol)
    if capped:
        raw_qty = pos_cap(symbol) / live
    qty = round_down_sig(raw_qty)
    return qty, raw_qty, capped, float(qty) * live


def buy_order(symbol, live, entry, stop, atr, lang="ru"):
    """(title, one-line text) of a variant-B LONG signal: market entry at the live price, the stop, TP1 / TP2 at
    B's prices, TP3 trailing (lang="en": English, for the English example only). SKIP if the price moved too far."""
    coin = coin_of(symbol)
    if lang == "ru" and (live <= stop or live > entry + atr):
        return (f"⏸ ПРОПУСК {coin}", f"Не входить: цена ушла слишком далеко от сигнала.\n"
                                     f"Сейчас {px(live)}, вход в тесте {px(entry)}, стоп {px(stop)}, ATR {px(atr)}")
    tp1, tp2 = (entry + m * (entry - stop) for m, _ in TPS["B"])
    if lang == "en":
        return (f"🟢 LONG {coin}", f"🟢 LONG {coin} · entry {px(live)} · stop {px(stop)} · "
                                   f"TP1 {px(tp1)} / TP2 {px(tp2)} / TP3 trailing")
    return (f"🟢 LONG {coin}", f"🟢 LONG {coin} · вход {px(live)} · стоп {px(stop)} · "
                               f"TP1 {px(tp1)} / TP2 {px(tp2)} / TP3 трейлинг")


# ---------- BUY signal card (PNG) ----------

CARD_W, CARD_H = 1080, 1350
CARD_TEXT = {
    "ru": {"grade": ("сильный", "обычный"), "entry": "Вход", "stop": "Стоп", "tp": "Тейк", "trailing": "трейлинг",
           "context": "Пробой 20-дневного максимума, рынок: {market}, объём {vol} среднего.",
           "market": {"bull": "бычий", "bear": "медвежий", "side": "боковик", None: "нет данных"},
           "vol": ("выше", "ниже"), "size": "Размер: {qty} {coin}", "margin": "маржа 5x: {m} USDT",
           "capped": "урезано лимитом позиции", "k1000": "в 1000{coin}: {q}", "tags": ("TP2", "TP1", "ВХОД", "СТОП")},
    "en": {"grade": ("strong", "normal"), "entry": "Entry", "stop": "Stop", "tp": "Take", "trailing": "trailing",
           "context": "Breakout of the 20-day high, market: {market}, volume {vol} average.",
           "market": {"bull": "bull", "bear": "bear", "side": "sideways", None: "no data"},
           "vol": ("above", "below"), "size": "Size: {qty} {coin}", "margin": "margin 5x: {m} USDT",
           "capped": "cut by the position cap", "k1000": "in 1000{coin}: {q}", "tags": ("TP2", "TP1", "ENTRY", "STOP")},
}
CARD_BARS = 60
FONT_FILES = {False: ("fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
              True: ("fonts/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")}
C_BG, C_PANEL, C_GRID = (13, 17, 23), (22, 27, 34), (40, 46, 56)
C_TEXT, C_MUTED = (230, 237, 243), (139, 148, 158)
C_GREEN, C_RED, C_BLUE, C_GOLD = (46, 204, 113), (248, 81, 73), (88, 166, 255), (227, 179, 65)


def card_font(size, bold=False):
    from PIL import ImageFont
    here = os.path.dirname(os.path.abspath(__file__))
    for f in FONT_FILES[bold]:
        path = f if os.path.isabs(f) else os.path.join(here, f)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise FileNotFoundError("DejaVu Sans not found (fonts/ in the repo or the system)")


def signal_grade(bars, day=None):
    """(strong?, volume above its 20-day average? or None) of the breakout day (`day`, default the last bar):
    strong = the close in the top 25% of the day's range and the volume above the previous 20 days' average."""
    t = next((i for i, b in enumerate(bars) if b["time"] == day), len(bars) - 1) if day else len(bars) - 1
    bar = bars[t]
    rng = bar["high"] - bar["low"]
    top = (bar["close"] - bar["low"]) / rng >= 0.75 if rng > 0 else True
    vols = [b.get("volume") for b in bars[max(0, t - LOOKBACK):t]]
    if bar.get("volume") is None or len(vols) < LOOKBACK or None in vols:
        return False, None
    above = bar["volume"] > sum(vols) / len(vols)
    return top and above, above


_LIGHT = {}


def market_state(now_ms=None):
    """'bull' / 'bear' / 'side' by BTC vs its SMA200 (±MARKET_BAND %), None if unknown; fetched once per run."""
    if "v" not in _LIGHT:
        light = market_light(now_ms or int(time.time() * 1000))
        _LIGHT["v"] = None if not light else "bull" if light[0] > MARKET_BAND else "bear" if light[0] < -MARKET_BAND else "side"
    return _LIGHT["v"]


def card_chart(d, show, lines, lo_extra, hi_extra):
    """The candle chart panel of a card (y 455..1060) with dashed price lines and tags on the right price axis.
    `lines` = [(price, colour, name)] from the top down; the price range covers the candles, `lo_extra`, `hi_extra`."""
    f = card_font
    cx0, cy0, cx1, cy1, ax = 60, 475, 860, 1040, 870
    d.rounded_rectangle((40, 455, 1040, 1060), 16, fill=C_PANEL)
    lo = min([b["low"] for b in show] + [lo_extra])
    hi = max([b["high"] for b in show] + [hi_extra])
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    y = lambda p: cy1 - (p - lo) / (hi - lo) * (cy1 - cy0)
    placed = []
    for price, _, _ in lines:                           # axis tag positions, top to bottom, kept apart
        placed.append(max(y(price), placed[-1] + 34) if placed else y(price))
    for k in range(6):                                  # grid and axis prices (not under a tag)
        gp = lo + (hi - lo) * k / 5
        d.line((cx0, y(gp), cx1, y(gp)), fill=C_GRID, width=1)
        if all(abs(y(gp) - ty) > 26 for ty in placed):
            d.text((ax + 8, y(gp)), px(gp), font=f(17), fill=C_MUTED, anchor="lm")
    d.line((cx1 + 4, cy0, cx1 + 4, cy1), fill=C_GRID, width=2)
    step = (cx1 - cx0) / max(len(show), 1)
    for i, b in enumerate(show):
        c = cx0 + (i + 0.5) * step
        col = C_GREEN if b["close"] >= b["open"] else C_RED
        d.line((c, y(b["high"]), c, y(b["low"])), fill=col, width=2)
        top, bot = y(max(b["open"], b["close"])), y(min(b["open"], b["close"]))
        d.rectangle((c - step * 0.32, top, c + step * 0.32, max(bot, top + 2)), fill=col)
    for (price, col, name), ty in zip(lines, placed):
        ly = y(price)
        for xs in range(cx0, cx1, 20):
            d.line((xs, ly, min(xs + 11, cx1), ly), fill=col, width=3)
        d.text((cx0 + 6, ly - 16), name, font=f(20, True), fill=col, anchor="lm")
        tag = px(price)
        fs = 20
        while fs > 13 and d.textlength(tag, font=f(fs, True)) > 1040 - ax - 20:
            fs -= 1
        d.rounded_rectangle((ax, ty - 15, 1034, ty + 15), 6, fill=col)
        d.text(((ax + 1034) / 2, ty), tag, font=f(fs, True), fill=C_BG, anchor="mm")


def buy_card(symbol, bars, live, entry, stop, level, demo=False, lang="ru", badge=None, day=None, market="?"):
    """PNG bytes of the LONG signal card (1080x1350, dark, signal-app style): coin, "LONG · 1D · R:R 1:x" and the
    setup grade; entry | stop; three take-profit boxes; the last CARD_BARS daily candles with entry, stop, TP1, TP2
    tagged on the right price axis; one sentence of context; size in coins and margin at 5x. Needs Pillow."""
    from PIL import Image, ImageDraw
    coin, L = coin_of(symbol), CARD_TEXT[lang]
    badge = badge or ("DEMO" if demo else None)
    market = market_state() if market == "?" else market
    tp1, tp2 = (entry + m * (entry - stop) for m, _ in TPS["B"])
    qty, raw_qty, capped, notional = buy_size(symbol, live, stop)
    strong, vol_above = signal_grade(bars, day)
    rr = (tp2 - live) / (live - stop)
    pct = lambda p: 100 * (p / live - 1)
    img = Image.new("RGB", (CARD_W, CARD_H), C_BG)
    d = ImageDraw.Draw(img)
    f = card_font

    # header: coin, LONG · 1D · R:R, grade
    d.text((50, 62), hh_name(symbol), font=f(64, True), fill=C_TEXT, anchor="lm")
    if badge:
        bw = d.textlength(badge, font=f(34, True)) + 36
        d.rounded_rectangle((970 - bw, 32, 970, 92), 12, fill=C_GOLD)
        d.text((970 - bw / 2, 62), badge, font=f(34, True), fill=C_BG, anchor="mm")
    chips = [(f"LONG · 1D · R:R 1:{rr:.1f}", C_GREEN, True), (L["grade"][0] if strong else L["grade"][1],
                                                              C_GREEN if strong else C_MUTED, strong)]
    x = 50
    for text, col, filled in chips:
        w = d.textlength(text, font=f(28, True)) + 40
        if filled:
            d.rounded_rectangle((x, 112, x + w, 162), 12, fill=col)
            d.text((x + w / 2, 137), text, font=f(28, True), fill=C_BG, anchor="mm")
        else:
            d.rounded_rectangle((x, 112, x + w, 162), 12, outline=col, width=3)
            d.text((x + w / 2, 137), text, font=f(28, True), fill=col, anchor="mm")
        x += w + 16
    d.text((1030, 137), (day or bars[-1]["time"]) if bars else "", font=f(24), fill=C_MUTED, anchor="rm")

    # entry | stop
    d.rounded_rectangle((40, 185, 1040, 285), 16, fill=C_PANEL)
    d.line((540, 205, 540, 265), fill=C_GRID, width=2)
    d.text((70, 215), L["entry"], font=f(24), fill=C_MUTED, anchor="lm")
    d.text((70, 255), px(live), font=f(38, True), fill=C_TEXT, anchor="lm")
    d.text((570, 215), L["stop"], font=f(24), fill=C_MUTED, anchor="lm")
    d.text((570, 255), px(stop), font=f(38, True), fill=C_RED, anchor="lm")
    d.text((1010, 255), f"{pct(stop):+.2f}%", font=f(30, True), fill=C_RED, anchor="rm")

    # three take-profit boxes
    for k, (price, label) in enumerate(((tp1, f"{pct(tp1):+.2f}%"), (tp2, f"{pct(tp2):+.2f}%"), (None, L["trailing"]))):
        x0 = 40 + k * 340
        d.rounded_rectangle((x0, 305, x0 + 320, 435), 16, fill=C_PANEL, outline=C_GREEN if price else C_GRID, width=2)
        d.text((x0 + 24, 335), f"{L['tp']} {k + 1}", font=f(24), fill=C_MUTED, anchor="lm")
        d.text((x0 + 24, 375), label, font=f(34, True), fill=C_GREEN, anchor="lm")
        if price:
            d.text((x0 + 24, 412), px(price), font=f(24), fill=C_TEXT, anchor="lm")

    # chart with the price axis on the right
    lines = [(tp2, C_GREEN, L["tags"][0]), (tp1, C_GREEN, L["tags"][1]), (live, C_BLUE, L["tags"][2]),
             (stop, C_RED, L["tags"][3])]
    card_chart(d, bars[-CARD_BARS:], lines, stop, tp2)

    # one sentence of context
    sentence = L["context"].format(market=L["market"].get(market, L["market"][None]),
                                   vol=L["vol"][0] if vol_above else L["vol"][1])
    if vol_above is None:
        sentence = sentence.split(",")[0] + ", " + sentence.split(",")[1].strip() + "."
    words, cur, wrapped = sentence.split(), "", []
    for w_ in words:                                    # wrap at 980 px
        nxt = f"{cur} {w_}".strip()
        if d.textlength(nxt, font=f(30)) > 980 and cur:
            wrapped.append(cur)
            cur = w_
        else:
            cur = nxt
    wrapped.append(cur)
    for i, line in enumerate(wrapped[:2]):
        d.text((50, 1100 + i * 40), line, font=f(30), fill=C_TEXT, anchor="lm")

    # size and margin
    d.line((40, 1200, 1040, 1200), fill=C_GRID, width=2)
    shown_qty = f"{float(qty):,.0f}" if float(qty) >= 1000 and float(qty).is_integer() else qty
    size_txt = L["size"].format(qty=shown_qty, coin=coin)
    margin_txt = L["margin"].format(m=f"{notional / LEVERAGE:,.2f}")
    fs = 42
    while fs > 26 and d.textlength(size_txt, font=f(fs, True)) + d.textlength(margin_txt, font=f(30)) > 940:
        fs -= 1
    d.text((50, 1250), size_txt, font=f(fs, True), fill=C_TEXT, anchor="lm")
    d.text((1030, 1250), margin_txt, font=f(30), fill=C_GOLD, anchor="rm")
    notes = []
    if symbol in FUTURES and FUTURES[symbol][1] > 1:
        notes.append(L["k1000"].format(coin=coin, q=round_down_sig(raw_qty / FUTURES[symbol][1])))
    if capped:
        notes.append(L["capped"])
    if notes:
        d.text((50, 1305), " · ".join(notes), font=f(24), fill=C_MUTED, anchor="lm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def header_value(s):
    """An HTTP header value: ASCII as is, anything else as one RFC 2047 UTF-8 word (ntfy decodes it)."""
    return s if s.isascii() else "=?UTF-8?B?" + base64.b64encode(s.encode("utf-8")).decode() + "?="


def ntfy_card(title, text, png, filename, fallback=None):
    """Push `png` as an ntfy attachment (PUT, Filename/Title/Message headers) with `text` as the message.
    If the card could not be made (png None) or the upload fails, push `fallback` (default `text`) as usual instead."""
    fallback = fallback or text
    if png is None:
        return ntfy(title, fallback)
    size = len(png)
    if DRY_RUN:
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "wb") as fh:
            fh.write(png)
        print(f"\n--- dry run, not pushed: card {title} ({size} bytes) saved to {path} ---\n{text}")
        return None
    topic = os.environ.get("NTFY_TOPIC") or load_env().get("NTFY_TOPIC")
    if not topic:
        print(f"ntfy: card {title} -> ERROR NTFY_TOPIC is not set")
        return "NTFY_TOPIC is not set"
    if len(text.encode("utf-8")) >= PUSH_LIMIT:
        return ntfy(title, fallback)
    req = urllib.request.Request(f"https://ntfy.sh/{urllib.parse.quote(topic)}", data=png, method="PUT",
                                 headers={"Filename": filename, "Title": header_value(title),
                                          "Message": header_value(text)})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"ntfy: card {title} ({size} bytes PNG) -> HTTP {resp.status}")
        return None
    except Exception as e:  # a notifier problem must never break the paper run: fall back to the text push
        print(f"ntfy: card {title} ({size} bytes PNG) -> ERROR {type(e).__name__}: {e}; sending the text push")
        return ntfy(title, fallback)


def try_card(symbol, bars, live, entry, stop, level, demo=False, lang="ru", badge=None, day=None):
    """buy_card(), or None (logged) if Pillow / the font is missing or drawing fails."""
    try:
        return buy_card(symbol, bars, live, entry, stop, level, demo, lang, badge, day)
    except Exception as e:
        print(f"card {symbol}: not drawn ({type(e).__name__}: {e}); text push only")
        return None


def breakout_level(bars, day):
    """The 20-day high the close of `day` broke (None if `day` is not in `bars` with 20 days before it)."""
    t = next((i for i, b in enumerate(bars) if b["time"] == day), None)
    return max(b["high"] for b in bars[t - LOOKBACK:t]) if t is not None and t >= LOOKBACK else None


def challenge_took(state, e):
    """Did the virtual challenge B take this B entry: 'yes', 'no' (open-risk cap or leverage) or 'pending'."""
    ch = state.get("challenge_b")
    if not ch:
        return "pending"
    p = ch["positions"].get(e["symbol"])
    return "yes" if p and p["entry_date"] == e["date"] else "pending" if ch["last_day"] < e["date"] else "no"


def left_pct(hits):
    return 100 - sum(PARTS_PCT[:hits])


def ntfy_events(state, prices, new_events, journal, bars_of=None):
    """Variant-B pushes: an order per entry the challenge B took, then TP1 / TP2 / close pushes for the
    trades a BUY was pushed for (state['followed_b']); none per TRAIL, none for variant A."""
    followed = state.setdefault("followed_b", {})
    for e in new_events:
        if e["variant"] != "B":
            continue
        s, name, coin = e["symbol"], hh_name(e["symbol"]), coin_of(e["symbol"])
        f = followed.get(s)
        if e["action"] == "OPEN":
            pos = state["symbols"].get(s, {}).get("position_b")
            took = challenge_took(state, e)
            if not pos or pos["entry_date"] != e["date"] or s not in prices:
                ntfy(f"⏸ ПРОПУСК {coin}", f"Не входить: вход от {e['date']} в тесте уже закрыт (или нет текущей цены).")
                continue
            if took == "no":
                ntfy(f"⏸ ПРОПУСК {coin}", f"Не входить: челлендж B не взял сделку от {e['date']} "
                                          f"(лимит открытого риска {100 * CAP:g}% или плечо).")
                continue
            title, text = buy_order(s, prices[s], pos["entry"], pos["stop"], pos["atr"])
            if title.startswith("🟢"):
                followed[s] = {"entry_date": e["date"], "entry": pos["entry"], "stop": pos["stop"], "tp": pos["tp"], "hits": 0}
                bars = (bars_of or {}).get(s) or []
                level = breakout_level(bars, e["date"])
                png = try_card(s, bars, prices[s], pos["entry"], pos["stop"], level, day=e["date"]) if level else None
                ntfy_card(title, text, png, f"buy_{coin.lower()}_{e['date']}.png")
                continue
            ntfy(title, text)
        elif e["action"] == "SKIP":                   # a breakout the 2 ATR candle filter skipped
            bars = (bars_of or {}).get(s) or []
            t = next((i for i, b in enumerate(bars) if b["time"] == e["date"]), None)
            ratio = candle_atr(bars[t], filtered_atr(bars, t)) if t is not None else None
            if ratio is not None:
                ntfy(*skip_alert(coin, ratio))
        elif not f or e["date"] < f["entry_date"]:
            continue                                  # not a trade a BUY was pushed for
        elif e["action"] == "TP1":
            f["hits"] = 1
            ntfy(f"🎯 TP1 {coin}",
                 f"TP1 {px(f['tp'][0])} исполнен: первая треть закрыта, в тесте {e['R']:+.2f}R.\n"
                 f"Переставьте SL двух оставшихся частей на цену входа {px(f['entry'])}:\n"
                 f"1. «Позиции» → карандаш у TP/SL → вкладка «Частичная позиция».\n"
                 f"2. Часть 2 ({PARTS_PCT[1]}%, TP {px(f['tp'][1])}): SL измените на {px(f['entry'])}.\n"
                 f"3. Часть 3 ({PARTS_PCT[2]}%, без TP): SL измените на {px(f['entry'])}.\n"
                 f"После этого остаток сделки без риска (стоп в безубытке).")
        elif e["action"] == "TP2":
            f["hits"] = 2
            pos = state["symbols"].get(s, {}).get("position_b")
            trail = f" (сейчас {px(pos['trail'])})" if pos and pos.get("trail") else ""
            ntfy(f"🎯 TP2 {coin}",
                 f"TP2 {px(f['tp'][1])} исполнен: вторая треть закрыта, в тесте {e['R']:+.2f}R.\n"
                 f"1. Проверьте в «Позиции»: осталась часть {PARTS_PCT[2]}% со SL {px(f['entry'])}, без TP.\n"
                 f"2. Ничего не меняйте: ждите выхода по трейлингу. Бот пришлёт «🔴 ЗАКРЫТЬ {coin} СЕЙЧАС», "
                 f"когда дневное закрытие будет ниже трейлинг-стопа{trail}.")
        elif e["action"].startswith("CLOSE"):
            left = left_pct(f["hits"])
            total = trade_total(journal, s, "B", f["entry_date"], e["date"])
            res = (f"Результат в тесте: {e['R']:+.2f}R" if f["hits"] == 0 else
                   f"Результат в тесте: остаток {e['R']:+.2f}R, вся сделка {total:+.2f}R")
            est = any((i["symbol"], i["close_date"], i.get("variant")) == (s, e["date"], "B")
                      for i in state.get("funding_pending", []))
            res += " (фандинг частично оценён, уточнится в начале месяца)" if est else ""
            if e["action"] == "CLOSE_TRAIL":
                ntfy(f"🔴 ЗАКРЫТЬ {coin} СЕЙЧАС",
                     f"Дневное закрытие ниже трейлинг-стопа {px(e['stop'])}. Закройте всё, что осталось ({left}% позиции).\n"
                     f"1. Откройте «Позиции» и найдите {name}.\n"
                     f"2. Нажмите «Закрыть» → «Рынок», закройте всё оставшееся количество.\n"
                     f"3. Проверьте, что позиции {name} больше нет и не осталось частичных TP/SL-ордеров.\n" + res)
            else:
                what = (f"Стоп в безубытке {px(e['stop'])} должен был закрыть остаток ({left}%) на бирже."
                        if e["action"] == "CLOSE_BE" else
                        f"Ваш SL {px(e['stop'])} должен был закрыть все части на бирже.")
                ntfy(f"⚪ {coin}: сработал стоп",
                     f"{what}\n"
                     f"1. Откройте «Позиции»: по {name} должно быть 0.\n"
                     f"2. Если что-то осталось — «Закрыть» → «Рынок», всё количество.\n"
                     f"3. Проверьте, что не осталось частичных TP/SL-ордеров.\n" + res)
            followed.pop(s, None)


def demo():
    """Print and push one sample BUY for BTCUSDT: live price, stop 2 filtered ATR below. Touches no file.
    Also checks that the futures funding API answers from here."""
    now_ms = int(time.time() * 1000)
    bars, live = download("BTCUSDT", now_ms)
    atr = filtered_atr(bars, len(bars))
    title, text = buy_order("BTCUSDT", live, live, live - STOP_ATR * atr, atr)
    title = f"DEMO {title}"            # "DEMO 🟢 LONG BTC"
    print(f"{title}\n{text}")
    level = max(b["high"] for b in bars[-LOOKBACK:])
    png = try_card("BTCUSDT", bars, live, live, live - STOP_ATR * atr, level, demo=True)
    ntfy_card(title, text, png, "demo_buy_btc.png")
    demo_dashboard(now_ms)
    try:
        recs = fetch_funding("BTCUSDT", now_ms - 2 * DAY_MS, now_ms)
        t, rate, _ = recs[-1]
        print(f"Funding check: OK, {len(recs)} BTCUSDT funding records in 2 days, "
              f"last {100 * rate:.4f}% at {datetime.fromtimestamp(t / 1000, tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
    except Exception as e:
        print(f"Funding check: FAILED ({type(e).__name__}: {e})")


def nearest_list(state, prices):
    """[(distance %, symbol, level)] of the NEAREST_BREAKOUTS flat symbols closest to their breakout level."""
    near = []
    for s, st in state["symbols"].items():
        w = st.get("watch")
        if w and s in prices and not st.get("position") and not st.get("position_b"):
            near.append((100 * (w["breakout_above"] / prices[s] - 1), s, w["breakout_above"]))
    near.sort(key=lambda n: abs(n[0]))
    return near[:NEAREST_BREAKOUTS]


def nearest_breakouts(state, prices):
    """"Ближе всего к пробою: ..." for the flat symbols closest to their breakout level, or None if there are none."""
    near = nearest_list(state, prices)
    return ("Ближе всего к пробою: " + ", ".join(f"{coin_of(s)} {px(level)} ({dist:+.1f}%)"
                                                 for dist, s, level in near)) if near else None


def summary_line(state, prices, new_events):
    """The one-line message under the dashboard card: new B signals and the nearest breakout."""
    opened = [coin_of(e["symbol"]) for e in new_events if e["variant"] == "B" and e["action"] == "OPEN"]
    line = f"📊 Итог дня: новых сигналов {len(opened)} ({', '.join(opened)})" if opened else "📊 Итог дня: сигналов нет"
    near = nearest_list(state, prices)
    if near:
        line += f" · ближе всего {coin_of(near[0][1])} {near[0][0]:.1f}%"
    return line


def summary_text(state, prices, new_events, processed):
    """Daily summary in Russian: last day, open B positions, signals, closed totals, one line per challenge,
    funding corrections, and what to keep on the exchange for every followed position."""
    last = max(d for _, d in processed) if processed else max(st["last_processed"] for st in state["symbols"].values())
    lines = [f"День {last} обработан" if processed else f"Нового дня нет (последний обработан {last})"]
    opened = []
    for s, st in state["symbols"].items():
        p = st.get("position_b")
        if p:
            est = " (фандинг — оценка)" if p.get("funding_est") else ""
            opened.append(f"{coin_of(s)} {open_r(p, prices[s]):+.2f}R{est}" if s in prices else coin_of(s))
    n_a = sum(1 for st in state["symbols"].values() if st.get("position"))
    lines.append("Открыто (B): " + (", ".join(opened) if opened else "нет") + f"; в варианте A позиций: {n_a}")
    lines.append(f"Новых сигналов (B): {sum(e['variant'] == 'B' and e['action'] not in ('TRAIL', 'SKIP') for e in new_events)}")
    journal = journal_with(new_events)
    (na, ta), (nb, tb) = closed_stats(journal, "A"), closed_stats(journal, "B")
    lines.append(f"Закрытых сделок: A {na}, итого {ta:+.2f}R; B {nb}, итого {tb:+.2f}R")
    nearest = nearest_breakouts(state, prices)
    if nearest:
        lines.append(nearest)
    for key, name in CHALLENGES:
        if state.get(key):
            lines.append(challenge_line_ru(state[key]))
    lines += state.get("funding_notes", [])          # cleared once a summary carrying them was pushed
    for s, f in state.get("followed_b", {}).items():
        p = state["symbols"].get(s, {}).get("position_b")
        if p and p["entry_date"] == f["entry_date"]:
            lines.append(f"{hh_name(s)}: осталось {left_pct(len(p.get('hit', [])))}%, SL {px(p['stop'])} на бирже. "
                         f"Закройте вручную, если дневное закрытие будет ниже {px(p['trail'])}.")
    return "📊 Meller Bot: итог дня", "\n".join(lines)


# ---------- daily dashboard card (PNG) ----------

MARKET_BAND = 3.0                 # dashboard market light: BTC more than this % above / below its SMA200


def market_light(now_ms):
    """(BTC % vs its SMA200, BTC price, BTC 200-day average of the closes) or None."""
    try:
        raw = fetch_candles("BTCUSDT", now_ms - 230 * DAY_MS, now_ms, "1d")
        closes = [float(k[4]) for k in raw if k[6] < now_ms]
        price = float(raw[-1][4])
        if len(closes) < 200:
            return None
        sma = sum(closes[-200:]) / 200
        return 100 * (price / sma - 1), price, sma
    except Exception as e:
        print(f"market light: BTC candles failed ({type(e).__name__}: {e})")
        return None


def dashboard_card(state, prices, day, light, run_time, badge=None):
    """PNG bytes of the daily dashboard (1080x1350, the signal card's style): market light, challenges A and B,
    open B positions, the nearest breakouts, last run time. Needs Pillow."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (CARD_W, CARD_H), C_BG)
    d = ImageDraw.Draw(img)
    f = card_font

    def bar(x, y, w, frac, col, h=14):
        d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=C_GRID)
        frac = max(0.0, min(1.0, frac))
        if frac > 0:
            d.rounded_rectangle((x, y, x + max(h, w * frac), y + h), h // 2, fill=col)

    def sev(frac):
        return C_RED if frac >= 0.8 else C_GOLD if frac >= 0.5 else C_GREEN

    # header
    d.text((50, 70), "Meller Bot", font=f(60, True), fill=C_TEXT, anchor="lm")
    d.text((50 + d.textlength("Meller Bot ", font=f(60, True)), 70), f"· закрытие {day[8:10]}.{day[5:7]}",
           font=f(40), fill=C_MUTED, anchor="lm")
    if badge:
        bw = d.textlength(badge, font=f(34, True)) + 36
        d.rounded_rectangle((970 - bw, 40, 970, 100), 12, fill=C_GOLD)        # 60 px in from the right edge
        d.text((970 - bw / 2, 70), badge, font=f(34, True), fill=C_BG, anchor="mm")
    if light:
        pct, price, sma = light
        col, word = ((C_GREEN, "бычий") if pct > MARKET_BAND else (C_RED, "медвежий") if pct < -MARKET_BAND
                     else (C_GOLD, "боковик"))
        detail = f"BTC {px(price)} · SMA200 {px(sma)} · {pct:+.1f}%"
    else:
        col, word, detail = C_MUTED, "нет данных", "BTC SMA200 недоступна"
    d.rounded_rectangle((40, 125, 1040, 205), 16, fill=C_PANEL)
    d.ellipse((66, 145, 106, 185), fill=col)
    d.text((126, 165), f"Рынок: {word}", font=f(36, True), fill=col, anchor="lm")
    d.text((1016, 165), detail, font=f(22), fill=C_MUTED, anchor="rm")

    # challenges
    for k, (key, name) in enumerate(CHALLENGES):
        ch = state.get(key)
        x0, y0, w = 40 + k * 510, 225, 490
        d.rounded_rectangle((x0, y0, x0 + w, y0 + 400), 16, fill=C_PANEL)
        kind = "трейлинг" if name == "A" else "TP 2R+4R"
        if not ch:
            d.text((x0 + 24, y0 + 40), f"Челлендж {name}: нет", font=f(30, True), fill=C_MUTED, anchor="lm")
            continue
        d.text((x0 + 24, y0 + 32), f"Челлендж {name}", font=f(30, True), fill=C_TEXT, anchor="lm")
        d.text((x0 + 24, y0 + 64), f"попытка #{ch['attempt']} · фаза {ch['phase']} · {kind}", font=f(20), fill=C_MUTED, anchor="lm")
        b = ch["start_balance"]
        if ch["status"] == "passed":
            d.text((x0 + 24, y0 + 120), "ОБЕ ФАЗЫ ПРОЙДЕНЫ", font=f(34, True), fill=C_GREEN, anchor="lm")
            d.text((x0 + 24, y0 + 170), str(ch.get("passed_on", "")), font=f(26), fill=C_MUTED, anchor="lm")
            continue
        pnl = 100 * (ch["equity"] / b - 1)
        d.text((x0 + 24, y0 + 110), f"${ch['equity']:,.2f}", font=f(42, True), fill=C_TEXT, anchor="lm")
        d.text((x0 + w - 24, y0 + 110), f"{pnl:+.2f}%", font=f(30, True), fill=C_GREEN if pnl >= 0 else C_RED, anchor="rm")
        d.text((x0 + 24, y0 + 148), f"баланс (закрытые) ${ch['balance']:,.2f}", font=f(20), fill=C_MUTED, anchor="lm")
        target, max_loss = PHASES[ch["phase"] - 1]
        daily_used = max(0.0, 1 - ch["to_daily_loss"] / (DAILY_LOSS * b))
        max_used = max(0.0, (b - ch["equity"]) / (max_loss * b))
        rows = [(f"Цель +{100 * target:g}%", f"{max(0.0, pnl):.2f}% из {100 * target:g}%", pnl / (100 * target), C_GREEN),
                (f"Дневной убыток", f"{100 * daily_used * DAILY_LOSS:.1f}% из {100 * DAILY_LOSS:g}%", daily_used, sev(daily_used)),
                (f"Макс. убыток", f"{100 * max_used * max_loss:.1f}% из {100 * max_loss:g}%", max_used, sev(max_used)),
                ("Торговые дни", f"{ch['trading_days']} / {MIN_DAYS}", ch["trading_days"] / MIN_DAYS, C_BLUE)]
        ry = y0 + 190
        for label, value, frac, colr in rows:
            d.text((x0 + 24, ry), label, font=f(24, True), fill=C_TEXT, anchor="lm")
            d.text((x0 + w - 24, ry), value, font=f(22), fill=C_MUTED, anchor="rm")
            bar(x0 + 24, ry + 18, w - 48, frac, colr)
            ry += 52

    # open positions (B: the traded variant)
    y0 = 645
    open_b = [(s, st["position_b"]) for s, st in sorted(state["symbols"].items()) if st.get("position_b")]
    n_a = sum(1 for st in state["symbols"].values() if st.get("position"))
    pos_h = 270 if open_b else 135
    d.rounded_rectangle((40, y0, 1040, y0 + pos_h), 16, fill=C_PANEL)
    d.text((64, y0 + 34), "Открытые позиции (B)", font=f(30, True), fill=C_TEXT, anchor="lm")
    d.text((1016, y0 + 34), f"в варианте A: {n_a}", font=f(22), fill=C_MUTED, anchor="rm")
    if not open_b:
        d.text((540, y0 + 90), "нет позиций", font=f(32), fill=C_MUTED, anchor="mm")
    else:
        for col_x, head in ((64, "монета"), (300, "вход"), (560, "стоп"), (1016, "сейчас")):
            d.text((col_x, y0 + 76), head, font=f(20), fill=C_MUTED, anchor="rm" if col_x == 1016 else "lm")
        shown = open_b[:4]
        for i, (s, p) in enumerate(shown):
            ry = y0 + 112 + i * 38
            r = open_r(p, prices[s]) if s in prices else None
            d.text((64, ry), coin_of(s), font=f(26, True), fill=C_TEXT, anchor="lm")
            d.text((300, ry), px(p["entry"]), font=f(24), fill=C_TEXT, anchor="lm")
            d.text((560, ry), px(p["stop"]) + (" (б/у)" if p.get("be") else ""), font=f(24), fill=C_RED, anchor="lm")
            d.text((1016, ry), "—" if r is None else f"{r:+.2f}R", font=f(26, True),
                   fill=C_MUTED if r is None else C_GREEN if r >= 0 else C_RED, anchor="rm")
        if len(open_b) > len(shown):
            d.text((64, y0 + 112 + 4 * 38), f"и ещё {len(open_b) - len(shown)}", font=f(22), fill=C_MUTED, anchor="lm")

    # nearest breakouts
    y0 = 645 + pos_h + 20
    box_h = 1255 - y0
    step = min(70, (box_h - 130) / 4)
    near = nearest_list(state, prices)
    d.rounded_rectangle((40, y0, 1040, y0 + box_h), 16, fill=C_PANEL)
    d.text((64, y0 + 34), "Ближе всего к пробою", font=f(30, True), fill=C_TEXT, anchor="lm")
    d.text((1016, y0 + 34), "полная полоса = у уровня входа", font=f(20), fill=C_MUTED, anchor="rm")
    if not near:
        d.text((540, y0 + box_h / 2), "нет данных", font=f(30), fill=C_MUTED, anchor="mm")
    for i, (dist, s, level) in enumerate(near):
        ry = y0 + 90 + i * step
        d.text((64, ry), coin_of(s), font=f(26, True), fill=C_TEXT, anchor="lm")
        d.text((250, ry), px(level), font=f(22), fill=C_MUTED, anchor="lm")
        frac = 1 - max(dist, 0) / 20                    # fills up as the coin gets closer (clamped in bar())
        bar(470, ry - 8, 400, frac, C_GREEN if dist <= NEAR_PCT else C_BLUE if dist <= 10 else C_MUTED, h=16)
        d.text((1016, ry), f"{dist:+.1f}%", font=f(26, True), fill=C_GREEN if dist <= NEAR_PCT else C_TEXT, anchor="rm")

    # bottom line
    d.line((40, 1280, 1040, 1280), fill=C_GRID, width=2)
    d.text((60, 1315), f"Последний запуск: {run_time}", font=f(23), fill=C_MUTED, anchor="lm")
    d.text((1020, 1315), "следующая проверка каждый час", font=f(23), fill=C_MUTED, anchor="rm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def try_dashboard(state, prices, day, now_ms, badge=None):
    """dashboard_card(), or None (logged) if it cannot be drawn: the summary then goes as a text push."""
    try:
        run_time = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return dashboard_card(state, prices, day, market_light(now_ms), run_time, badge)
    except Exception as e:
        print(f"dashboard card: not drawn ({type(e).__name__}: {e}); text push only")
        return None


# ---------- virtual HashHedge 2-step challenges ----------

def new_challenge(name, attempt, start_day):
    """A fresh phase-1 account whose first evaluated day is `start_day`."""
    ch = {"name": name, "variant": name, "attempt": attempt, "status": "active", "start_balance": CH_BALANCE,
          "risk_pct": 100 * CH_RISK, "cap_pct": 100 * CAP, "leverage": LEVERAGE, "attempt_start": start_day}
    start_phase(ch, 1, start_day)
    return ch


def start_phase(ch, phase, start_day):
    ch.update({"phase": phase, "phase_start": start_day, "balance": CH_BALANCE, "equity": CH_BALANCE,
               "prev_close_equity": CH_BALANCE, "trading_days": 0, "positions": {}, "skipped": [], "closed": [],
               "last_day": (datetime.strptime(start_day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
               "near_alerted": False})
    set_limits(ch)


def set_limits(ch):
    """Targets, limits and distances (dollars) at the last evaluated close."""
    target, max_loss = PHASES[ch["phase"] - 1]
    b = ch["start_balance"]
    ch["target_pct"], ch["max_loss_pct"], ch["daily_loss_pct"] = 100 * target, 100 * max_loss, 100 * DAILY_LOSS
    ch["target_equity"] = round(b * (1 + target), 2)
    ch["max_loss_floor"] = round(b * (1 - max_loss), 2)
    ch["daily_loss_floor"] = round(ch["balance"] - DAILY_LOSS * b, 2)   # next close: day-start balance (closed P&L) - 5%
    ch["to_target"] = round(ch["target_equity"] - ch["equity"], 2)
    ch["to_max_loss"] = round(ch["equity"] - ch["max_loss_floor"], 2)
    ch["to_daily_loss"] = round(ch["equity"] - ch["daily_loss_floor"], 2)
    ch["open_risk"] = round(sum(p["risk_usd"] for p in ch["positions"].values() if not p.get("be_from")), 2)


def challenge_line(ch):
    name = ch.get("name", "A")
    if ch["status"] == "passed":
        return f"Challenge {name} #{ch['attempt']}: PASSED both phases ({ch['passed_on']})"
    pnl = 100 * (ch["equity"] / ch["start_balance"] - 1)
    return (f"Challenge {name} #{ch['attempt']} phase {ch['phase']}: equity ${ch['equity']:,.2f} ({pnl:+.2f}%), "
            f"to target ${ch['to_target']:,.2f}, to max loss ${ch['to_max_loss']:,.2f}, "
            f"trading days {ch['trading_days']}/{MIN_DAYS}")


def challenge_line_ru(ch):
    name = ch.get("name", "A")
    kind = "трейлинг" if name == "A" else "TP 2R+4R"
    if ch["status"] == "passed":
        return f"Челлендж {name} ({kind}) #{ch['attempt']}: ОБЕ ФАЗЫ ПРОЙДЕНЫ ({ch['passed_on']})"
    pnl = 100 * (ch["equity"] / ch["start_balance"] - 1)
    return (f"Челлендж {name} ({kind}) #{ch['attempt']}, фаза {ch['phase']}: эквити ${ch['equity']:,.2f} ({pnl:+.2f}%), "
            f"до цели ${ch['to_target']:,.2f}, до макс. убытка ${ch['to_max_loss']:,.2f}, "
            f"торговых дней {ch['trading_days']}/{MIN_DAYS}")


def challenge_day(state, key, day, events, closes, alerts):
    """Evaluate one closed day for one account (its variant's events only); may pass a phase or fail and
    restart the attempt."""
    ch = state[key]
    name, b = ch.get("name", "A"), ch["start_balance"]
    events = [e for e in events if (e.get("variant") or "A") == name]
    day_start_balance = ch["balance"]                 # HashHedge daily-loss base: closed P&L only
    traded = False
    for e in events:                                   # exits and partial exits first: they free open risk
        s = e["symbol"]
        if s not in ch["positions"]:
            continue
        p = ch["positions"][s]
        if e["action"] in ("TP1", "TP2"):
            ch["balance"] += float(e["R"]) * p["risk_usd"]
            p["rem"] = p.get("rem", 1.0) - TPS[name][int(e["action"][2]) - 1][1]
            p.setdefault("be_from", next_day(day))     # stop at breakeven from tomorrow: risk counts 0
            traded = True
        elif e["action"].startswith("CLOSE"):
            ch["positions"].pop(s)
            ch["balance"] += float(e["R"]) * p["risk_usd"]
            ch.setdefault("closed", []).append({"symbol": s, "entry_date": p["entry_date"],
                                                "risk_usd": p["risk_usd"]})   # for funding corrections
            traded = True
    open_risk = lambda: sum(p["risk_usd"] for p in ch["positions"].values() if not (p.get("be_from") and p["be_from"] <= day))
    for e in sorted((e for e in events if e["action"] == "OPEN" and e["symbol"] in PAPER_SYMBOLS),
                    key=lambda e: PAPER_SYMBOLS.index(e["symbol"])):
        s, entry, unit_risk = e["symbol"], float(e["price"]), float(e["price"]) - float(e["stop"])
        if open_risk() + CH_RISK * b > CAP * b + 1e-6:
            ch["skipped"].append(f"{day} {s} (open-risk cap)")
            continue
        notional = CH_RISK * b / unit_risk * entry
        used = sum(p["notional"] * p.get("rem", 1.0) for p in ch["positions"].values())
        scale = min(1.0, (LEVERAGE * b - used) / notional, pos_cap(s) / notional)
        if scale <= 0:
            ch["skipped"].append(f"{day} {s} (leverage)")
            continue
        ch["positions"][s] = {"entry_date": day, "entry": entry, "risk": unit_risk, "rem": 1.0,
                              "qty": CH_RISK * b * scale / unit_risk, "risk_usd": CH_RISK * b * scale,
                              "notional": notional * scale}
        traded = True

    equity = ch["balance"] + sum((p.get("rem", 1.0) * mark(p, closes[s][day])[1]
                                  - unbooked_at(state, s, p["entry_date"], day, name)) * p["risk_usd"]
                                 for s, p in ch["positions"].items())
    ch["equity"] = round(equity, 2)
    ch["trading_days"] += traded
    ch["last_day"] = day
    target, max_loss = PHASES[ch["phase"] - 1]
    floor_max, floor_daily = b * (1 - max_loss), day_start_balance - DAILY_LOSS * b

    failed = ("max loss" if equity <= floor_max + 1e-6 else
              "daily loss" if equity <= floor_daily + 1e-6 else None)
    if failed:
        state.setdefault(key + "_history", []).append(
            {"attempt": ch["attempt"], "result": f"failed phase {ch['phase']}: {failed}", "start": ch["attempt_start"],
             "phase_start": ch["phase_start"], "end": day, "equity": ch["equity"]})
        alerts.append((f"❌ Челлендж {name} #{ch['attempt']}: ПРОВАЛ",
                       f"{day}: фаза {ch['phase']} провалена по правилу «{RULE_RU[failed]}». Эквити ${equity:,.2f} "
                       f"(порог макс. убытка ${floor_max:,.2f}, дневной порог ${floor_daily:,.2f}). "
                       f"Новый челлендж {name} #{ch['attempt'] + 1} начинается {next_day(day)}."))
        state[key] = new_challenge(name, ch["attempt"] + 1, next_day(day))
        return
    if equity >= b * (1 + target) - 1e-6 and ch["trading_days"] >= MIN_DAYS:
        state.setdefault(key + "_history", []).append(
            {"attempt": ch["attempt"], "result": f"passed phase {ch['phase']}", "start": ch["attempt_start"],
             "phase_start": ch["phase_start"], "end": day, "equity": ch["equity"],
             "trading_days": ch["trading_days"]})
        if ch["phase"] == 1:
            alerts.append((f"✅ Челлендж {name} #{ch['attempt']}: фаза 1 ПРОЙДЕНА",
                           f"{day}: эквити ${equity:,.2f} (+{100 * target:.0f}% достигнуто, торговых дней {ch['trading_days']}). "
                           f"Открытые позиции закрыты; фаза 2 (+6%, макс. убыток 8%) начинается {next_day(day)}."))
            start_phase(ch, 2, next_day(day))
        else:
            alerts.append((f"🏆 Челлендж {name} #{ch['attempt']}: ОБЕ ФАЗЫ ПРОЙДЕНЫ",
                           f"{day}: фаза 2 пройдена, эквити ${equity:,.2f}. Виртуальный челлендж завершён."))
            ch.update({"status": "passed", "passed_on": day, "positions": {}})
            set_limits(ch)
        return

    for rule, dist in (("max loss", equity - floor_max), ("daily loss", equity - floor_daily)):
        near = dist < CH_NEAR * b
        if near and (rule == "daily loss" or not ch["near_alerted"]):
            alerts.append((f"⚠️ Челлендж {name} #{ch['attempt']}: близко к лимиту «{RULE_RU[rule]}»",
                           f"{day}: эквити ${equity:,.2f}, до лимита «{RULE_RU[rule]}» осталось ${dist:,.2f} (фаза {ch['phase']})."))
        if rule == "max loss":
            ch["near_alerted"] = near      # re-arms once equity is back more than 1% above the floor
    ch["prev_close_equity"] = ch["equity"]
    set_limits(ch)


def setup_challenges(state, today):
    """One-time switch to the current challenge setup: archive the old accounts, start A and B fresh today."""
    if state.get("challenge_setup") == CHALLENGE_SETUP:
        return False
    archive = state.setdefault("challenge_archive", [])
    for key in ("challenge", "challenge_b"):
        if key in state:
            archive.append({"key": key, "archived_on": today, "setup": state.get("challenge_setup", "until 2026-11-08"),
                            "challenge": state.pop(key), "history": state.pop(key + "_history", [])})
    for key, name in CHALLENGES:
        state[key] = new_challenge(name, 1, today)
    state["challenge_setup"] = CHALLENGE_SETUP
    state["b_since"] = today                          # variant B takes entries from this day on
    state["followed_b"] = {}
    print(f"Challenges switched: {CHALLENGE_SETUP}; both start fresh on {today}")
    return True


def run_challenge(state, key, name, closes, journal):
    """Evaluate every day all symbols have processed but the account has not; returns alerts."""
    alerts = []
    through = min(st["last_processed"] for st in state["symbols"].values())
    while state[key]["status"] == "active":
        day = next_day(state[key]["last_day"])
        if day > through:
            break
        if any(day not in closes.get(s, {}) for s in state[key]["positions"]):
            print(f"Challenge {name}: no close for {day} for an open position; evaluated next run")
            break
        challenge_day(state, key, day, [r for r in journal if r["date"] == day], closes, alerts)
        ch = state[key]
        if ch.get("last_day") == day:                  # evaluated (a failed attempt restarts: nothing to log)
            log = state.setdefault("equity_log", {}).setdefault(name, {})
            log[day] = [ch["attempt"], ch["phase"], ch["equity"]]      # read by the weekly report
            for old in [d for d in log if d < (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=35)).strftime("%Y-%m-%d")]:
                del log[old]
    return alerts


# ---------- weekly report card (PNG, English, for X posts) ----------

def week_range(end_day):
    """(first day, last day, ISO week number) of the 7 closed days ending with `end_day`."""
    end = datetime.strptime(end_day, "%Y-%m-%d")
    return (end - timedelta(days=6)).strftime("%Y-%m-%d"), end_day, end.isocalendar()[1]


def week_challenge(state, key, name, start_day):
    """(equity, % this week, % since the phase start, target %) of a challenge, or None. "This week" is measured
    from the logged equity at the close before `start_day` if it belongs to the same attempt and phase, else from
    the phase's starting balance (the phase began this week, or nothing was logged yet)."""
    ch = state.get(key)
    if not ch:
        return None
    b, target = ch["start_balance"], PHASES[ch["phase"] - 1][0]
    before = state.get("equity_log", {}).get(name, {}).get(prev_day(start_day))
    base = before[2] if before and before[:2] == [ch["attempt"], ch["phase"]] else b
    return ch["equity"], 100 * (ch["equity"] / base - 1), 100 * (ch["equity"] / b - 1), 100 * target


def week_trades(journal, start_day, end_day):
    """([(coin, entry fill)] entries, [(coin, total R of the trade)] exits) of variant B in the week."""
    rows = [r for r in journal if r.get("variant", "A") == "B" and start_day <= r["date"] <= end_day]
    entries = [(coin_of(r["symbol"]), float(r["price"])) for r in rows if r["action"] == "OPEN"]
    exits = []
    for r in rows:
        if r["action"].startswith("CLOSE"):
            opens = [o["date"] for o in journal if o["symbol"] == r["symbol"] and o.get("variant", "A") == "B"
                     and o["action"] == "OPEN" and o["date"] <= r["date"]]
            exits.append((coin_of(r["symbol"]), trade_total(journal, r["symbol"], "B", max(opens), r["date"])
                          if opens else float(r["R"])))
    return entries, exits


def weekly_card(state, prices, journal, end_day, light, badge=None):
    """PNG bytes of the weekly report (1080x1350, dark, English labels). Needs Pillow."""
    from PIL import Image, ImageDraw
    start_day, _, week = week_range(end_day)
    img = Image.new("RGB", (CARD_W, CARD_H), C_BG)
    d = ImageDraw.Draw(img)
    f = card_font

    def bar(x, y, w, frac, col, h=14):
        d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=C_GRID)
        frac = max(0.0, min(1.0, frac))
        if frac > 0:
            d.rounded_rectangle((x, y, x + max(h, w * frac), y + h), h // 2, fill=col)

    def signed_col(v):
        return C_GREEN if v >= 0 else C_RED

    a, b = (datetime.strptime(x, "%Y-%m-%d") for x in (start_day, end_day))
    span = (f"{a:%b} {a.day} – {b:%b} {b.day}, {b.year}" if a.year == b.year else
            f"{a:%b} {a.day}, {a.year} – {b:%b} {b.day}, {b.year}")
    d.text((50, 62), "Meller Bot", font=f(60, True), fill=C_TEXT, anchor="lm")
    d.text((50 + d.textlength("Meller Bot ", font=f(60, True)), 62), f"· week {week}", font=f(44), fill=C_MUTED, anchor="lm")
    d.text((52, 122), span + " · daily closes, UTC", font=f(26), fill=C_MUTED, anchor="lm")
    if badge:
        bw = d.textlength(badge, font=f(34, True)) + 36
        d.rounded_rectangle((970 - bw, 32, 970, 92), 12, fill=C_GOLD)
        d.text((970 - bw / 2, 62), badge, font=f(34, True), fill=C_BG, anchor="mm")

    # market light
    if light:
        pct, price, sma = light
        col, word = ((C_GREEN, "bull") if pct > MARKET_BAND else (C_RED, "bear") if pct < -MARKET_BAND
                     else (C_GOLD, "sideways"))
        detail = f"BTC {px(price)} · 200-day {px(sma)} · {pct:+.1f}%"
    else:
        col, word, detail = C_MUTED, "no data", "BTC 200-day average unavailable"
    d.rounded_rectangle((40, 160, 1040, 240), 16, fill=C_PANEL)
    d.ellipse((66, 180, 106, 220), fill=col)
    d.text((126, 200), f"Market: {word}", font=f(36, True), fill=col, anchor="lm")
    d.text((1016, 200), detail, font=f(22), fill=C_MUTED, anchor="rm")

    # challenges
    for k, (key, name) in enumerate(CHALLENGES):
        x0, y0, w = 40 + k * 510, 260, 490
        d.rounded_rectangle((x0, y0, x0 + w, y0 + 300), 16, fill=C_PANEL)
        kind = "trailing exit" if name == "A" else "TP 2R + 4R"
        wc, ch = week_challenge(state, key, name, start_day), state.get(key)
        d.text((x0 + 24, y0 + 32), f"Challenge {name}", font=f(30, True), fill=C_TEXT, anchor="lm")
        if not wc:
            d.text((x0 + 24, y0 + 100), "not running", font=f(28), fill=C_MUTED, anchor="lm")
            continue
        equity, week_pct, total_pct, target = wc
        d.text((x0 + 24, y0 + 64), f"attempt #{ch['attempt']} · phase {ch['phase']} · {kind}", font=f(20), fill=C_MUTED, anchor="lm")
        d.text((x0 + 24, y0 + 112), f"${equity:,.2f}", font=f(42, True), fill=C_TEXT, anchor="lm")
        d.text((x0 + 24, y0 + 168), "this week", font=f(24), fill=C_MUTED, anchor="lm")
        d.text((x0 + w - 24, y0 + 168), f"{week_pct:+.2f}%", font=f(28, True), fill=signed_col(week_pct), anchor="rm")
        d.text((x0 + 24, y0 + 206), "since phase start", font=f(24), fill=C_MUTED, anchor="lm")
        d.text((x0 + w - 24, y0 + 206), f"{total_pct:+.2f}%", font=f(28, True), fill=signed_col(total_pct), anchor="rm")
        done = "passed" if ch["status"] == "passed" else f"{max(0.0, total_pct):.2f}% of +{target:g}%"
        d.text((x0 + 24, y0 + 246), f"target +{target:g}%", font=f(22, True), fill=C_TEXT, anchor="lm")
        d.text((x0 + w - 24, y0 + 246), done, font=f(22), fill=C_MUTED, anchor="rm")
        bar(x0 + 24, y0 + 266, w - 48, 1.0 if ch["status"] == "passed" else total_pct / target, C_GREEN)

    # trades this week (variant B)
    y0 = 580
    entries, exits = week_trades(journal, start_day, end_day)
    rows = [("entry", c, px(p), C_TEXT) for c, p in entries] + [("exit", c, f"{r:+.2f}R", signed_col(r)) for c, r in exits]
    box_h = 300
    d.rounded_rectangle((40, y0, 1040, y0 + box_h), 16, fill=C_PANEL)
    d.text((64, y0 + 34), "Trades this week", font=f(30, True), fill=C_TEXT, anchor="lm")
    d.text((1016, y0 + 34), f"{len(entries)} entries · {len(exits)} exits", font=f(22), fill=C_MUTED, anchor="rm")
    if not rows:
        d.text((540, y0 + 160), "no breakouts this week, the bot waited", font=f(32), fill=C_MUTED, anchor="mm")
    shown = rows[:5] if len(rows) <= 5 else rows[:4]
    for i, (kind, coin, value, colr) in enumerate(shown):
        ry = y0 + 88 + i * 42
        d.rounded_rectangle((64, ry - 15, 164, ry + 15), 8, fill=C_GRID)
        d.text((114, ry), kind, font=f(20, True), fill=C_GREEN if kind == "entry" else C_BLUE, anchor="mm")
        d.text((190, ry), coin, font=f(28, True), fill=C_TEXT, anchor="lm")
        d.text((1016, ry), value, font=f(28, True), fill=colr, anchor="rm")
    if len(rows) > len(shown):
        d.text((64, y0 + 88 + 4 * 42), f"and {len(rows) - len(shown)} more", font=f(22), fill=C_MUTED, anchor="lm")

    # closest coins to a breakout
    y0 = 900
    near = nearest_list(state, prices)
    d.rounded_rectangle((40, y0, 1040, 1250), 16, fill=C_PANEL)
    d.text((64, y0 + 34), "Closest to a breakout", font=f(30, True), fill=C_TEXT, anchor="lm")
    d.text((1016, y0 + 34), "full bar = at the entry level", font=f(20), fill=C_MUTED, anchor="rm")
    if not near:
        d.text((540, y0 + 175), "no data", font=f(30), fill=C_MUTED, anchor="mm")
    for i, (dist, sym, level) in enumerate(near):
        ry = y0 + 92 + i * 58
        d.text((64, ry), coin_of(sym), font=f(26, True), fill=C_TEXT, anchor="lm")
        d.text((250, ry), px(level), font=f(22), fill=C_MUTED, anchor="lm")
        bar(470, ry - 8, 400, 1 - max(dist, 0) / 20, C_GREEN if dist <= NEAR_PCT else C_BLUE if dist <= 10 else C_MUTED, h=16)
        d.text((1016, ry), f"{dist:+.1f}%", font=f(26, True), fill=C_GREEN if dist <= NEAR_PCT else C_TEXT, anchor="rm")

    # footer
    d.line((40, 1278, 1040, 1278), fill=C_GRID, width=2)
    d.text((540, 1314), "built with Claude Code · @meller_ai", font=f(26), fill=C_MUTED, anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def weekly_line(state, prices, journal, end_day):
    """One-line English message under the weekly card."""
    start_day, _, week = week_range(end_day)
    parts = [f"Week {week}:"]
    for key, name in CHALLENGES:
        wc = week_challenge(state, key, name, start_day)
        if wc:
            parts.append(f"{name} {wc[1]:+.2f}%")
    entries, exits = week_trades(journal, start_day, end_day)
    line = parts[0] + " " + ", ".join(parts[1:]) + f" · {len(entries)} entries, {len(exits)} exits"
    near = nearest_list(state, prices)
    return line + (f" · closest {coin_of(near[0][1])} {near[0][0]:.1f}%" if near else "")


def send_weekly(state, prices, journal, end_day, now_ms, badge=None):
    """Draw and push the weekly report for the 7 closed days ending with `end_day`; returns ntfy's error or None."""
    title = ("DEMO " if badge else "") + "📅 Weekly report"
    text = weekly_line(state, prices, journal, end_day)
    try:
        png = weekly_card(state, prices, journal, end_day, market_light(now_ms), badge)
    except Exception as e:
        print(f"weekly card: not drawn ({type(e).__name__}: {e}); text push only")
        png = None
    _, _, week = week_range(end_day)
    return ntfy_card(title, text, png, f"weekly_{end_day[:4]}_w{week:02d}.png")


def weekly_demo(now_ms):
    """One sample weekly report from the saved state and journal (prices = each symbol's last saved close)."""
    with open(STATE) as fh:
        state = json.load(fh)
    prices = {s: st["last_close"] for s, st in state["symbols"].items() if st.get("last_close")}
    end_day = max(st["last_processed"] for st in state["symbols"].values())
    return send_weekly(state, prices, read_journal(), end_day, now_ms, badge="DEMO")


def demo_dashboard(now_ms):
    """One sample dashboard card from the saved state (prices = each symbol's last saved close), marked DEMO."""
    with open(STATE) as fh:
        state = json.load(fh)
    prices = {s: st["last_close"] for s, st in state["symbols"].items() if st.get("last_close")}
    day = max(st["last_processed"] for st in state["symbols"].values())
    title, text = "DEMO 📊 Meller Bot: итог дня", summary_line(state, prices, [])
    png = try_dashboard(state, prices, day, now_ms, badge="DEMO")
    return ntfy_card(title, text, png, "demo_dashboard.png")


def demo_en():
    """Push one English sample BUY card for BTCUSDT, marked EXAMPLE, with self-consistent levels: entry just above
    the 20-day high (close 0.15% above it + slippage), stop = entry - 2 filtered ATR, TP1 = +2R, TP2 = +4R; sized
    as a real BUY at that entry. Touches no file. Real signals stay in Russian."""
    bars, _ = download("BTCUSDT", int(time.time() * 1000))
    atr = filtered_atr(bars, len(bars))
    level = max(b["high"] for b in bars[-LOOKBACK:])
    entry = level * 1.0015 * (1 + SLIPPAGE)
    stop = entry - STOP_ATR * atr
    title, text = buy_order("BTCUSDT", entry, entry, stop, atr, lang="en")
    title = f"EXAMPLE {title}"         # "EXAMPLE 🟢 LONG BTC"
    print(f"{title}\n{text}")
    png = try_card("BTCUSDT", bars, entry, entry, stop, level, lang="en", badge="EXAMPLE")
    return ntfy_card(title, text, png, "example_buy_btc.png")


# ---------- public web app data (site/data.json) ----------

def sig(x, digits=7):
    """`x` rounded to `digits` significant digits (smaller JSON, no float noise)."""
    return None if x is None else float(f"{x:.{digits}g}")


def secret_values():
    """Every value from .env and the secret environment variables: none may appear in a public file."""
    vals = set(load_env().values()) | {os.environ.get(k, "") for k in SECRET_ENV}
    return {v for v in vals if v and len(v) >= 6}


def level_path(bars, day, today=None, days=10):
    """The 20-day high (the breakout level) at the close of each of the `days` days after `day` (the day the current
    level is for), if no new highs come: the oldest days leave the window; today's high so far (`today`, the bar of
    `day`) stays in it. Display only: the strategy does not use it. [[date, level], ...]"""
    out = []
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    for k in range(1, days + 1):
        highs = [b["high"] for b in bars[len(bars) - LOOKBACK + k:]]
        if today is not None:
            highs.append(today["high"])
        if not highs:
            break
        out.append([(d + timedelta(days=k)).strftime("%Y-%m-%d"), sig(max(highs))])
    return out


def bot_results(state, journal):
    """Strategy B's results since it started (state["b_since"]), from the journal: every closed trade (entry, exit, take
    profits hit, total R with costs and funding) and every booked exit (date, R) for the balance line. Display only;
    the web app shows $ as R x the risk per trade on the $10,000 virtual balance."""
    since = state.get("b_since") or state.get("start_date")
    open_, trades, booked = {}, [], []
    for r in journal:
        if (r.get("variant") or "A") != "B" or (since and r["date"] < since):
            continue
        a, s = r["action"], r["symbol"]
        if a == "OPEN":
            open_[s] = {"symbol": s, "coin": coin_of(s), "entry_date": r["date"], "entry": sig(float(r["price"])), "r": 0.0, "hits": []}
        elif a in ("TP1", "TP2") or a.startswith("CLOSE"):
            R = float(r["R"]) if r.get("R") not in ("", None) else 0.0
            booked.append([r["date"], round(R, 4)])
            t = open_.get(s)
            if t is None:
                continue
            t["r"] += R
            if a.startswith("TP"):
                t["hits"].append(a)
            else:
                t.update(exit_date=r["date"], exit=sig(float(r["price"])), reason=a, r=round(t["r"], 4))
                trades.append(open_.pop(s))
    return {"since": since, "balance0": CH_BALANCE, "risk_usd": CH_RISK * CH_BALANCE, "trades": trades, "booked": booked}


def export_site(state, journal, now_ms, bars_of=None, light="?", setups=None, vol24=None):
    """Write SITE_DATA for the public web app from an explicit whitelist (never the raw state, never .env).
    Downloads the daily bars of any symbol missing from `bars_of`. Refuses to write if a secret value would
    appear in the file. Under --dry-run the file goes to the temp directory instead."""
    bars_of = dict(bars_of or {})
    symbols, last_px = [], {}
    for s in SCANNER_SYMBOLS:                           # bot = traded by strategy B (PAPER_SYMBOLS), else scanner only
        bars = bars_of.get(s)
        if bars is None:
            try:
                bars, _ = download(s, now_ms)
            except Exception as e:
                print(f"export {s}: daily candles failed ({type(e).__name__}: {e})")
                continue
        if len(bars) <= LOOKBACK:
            continue
        w, last = watch(bars), bars[-1]["close"]
        last_px[s] = last
        symbols.append({"symbol": s, "coin": coin_of(s), "name": hh_name(s), "bot": s in PAPER_SYMBOLS,
                        "level": sig(w["breakout_above"]),
                        "atr": sig(w["atr"]), "dist_pct": round(100 * (w["breakout_above"] / last - 1), 3),
                        "last_close": sig(last), "last_day": bars[-1]["time"],
                        "today": ([TODAY_BAR[s]["time"], sig(TODAY_BAR[s]["open"]), sig(TODAY_BAR[s]["high"]),
                                   sig(TODAY_BAR[s]["low"]), sig(TODAY_BAR[s]["close"])] if s in TODAY_BAR else None),
                        "level_path": level_path(bars, w["day"], TODAY_BAR[s] if s in TODAY_BAR and TODAY_BAR[s]["time"] == w["day"] else None),
                        "vol20": sig(sum(b["volume"] for b in bars[-20:]) / 20),
                        "vol24": sig((vol24 or {}).get(s)),
                        "closes": [sig(b["close"]) for b in bars[-60:]],
                        "ohlc": [[b["time"], sig(b["open"]), sig(b["high"]), sig(b["low"]), sig(b["close"])]
                                 for b in bars[-60:]]})
    positions = []
    for s, st in sorted(state["symbols"].items()):
        for v, key in POS_KEY.items():
            p = st.get(key)
            if not p:
                continue
            ch_key = next(k for k, n in CHALLENGES if n == v)          # variant A -> "challenge", B -> "challenge_b"
            chp = (state.get(ch_key) or {}).get("positions", {}).get(s)
            in_ch = bool(chp and chp.get("entry_date") == p["entry_date"])
            price = last_px.get(s, st.get("last_close"))
            positions.append({"symbol": s, "coin": coin_of(s), "variant": v, "entry_date": p["entry_date"],
                              "entry": sig(p["entry"]), "stop": sig(p["stop"]), "risk": sig(p["risk"]),
                              "tp": [sig(x) for x in p.get("tp") or []], "hit": p.get("hit", []), "be": p.get("be", False),
                              "rem": p.get("rem", 1.0), "booked_r": round(p.get("booked_r", 0.0), 4),
                              "unbooked_r": round(unbooked(p), 4), "trail": sig(p.get("trail")),
                              "r_at_close": round(open_r(p, price), 3) if price else None,
                              "risk_usd": round(chp["risk_usd"], 2) if in_ch else CH_RISK * CH_BALANCE,
                              "in_challenge": in_ch})
    challenges = []
    for key, name in CHALLENGES:
        ch = state.get(key)
        if not ch:
            continue
        b = ch["start_balance"]
        target, max_loss = PHASES[ch["phase"] - 1]
        log = state.get("equity_log", {}).get(name, {})
        curve = [[d, eq] for d, (att, ph, eq) in sorted(log.items()) if [att, ph] == [ch["attempt"], ch["phase"]]]
        challenges.append({"name": name, "attempt": ch["attempt"], "phase": ch["phase"], "status": ch["status"],
                           "start_balance": b, "balance": round(ch["balance"], 2), "equity": round(ch["equity"], 2),
                           "target_pct": 100 * target, "max_loss_pct": 100 * max_loss, "daily_loss_pct": 100 * DAILY_LOSS,
                           "daily_used_pct": round(max(0.0, 100 * DAILY_LOSS - 100 * ch.get("to_daily_loss", 0) / b), 3),
                           "max_used_pct": round(max(0.0, 100 * (b - ch["equity"]) / b), 3),
                           "trading_days": ch["trading_days"], "min_days": MIN_DAYS, "phase_start": ch["phase_start"],
                           "last_day": ch.get("last_day"), "curve": curve,
                           "history": [{k: h.get(k) for k in ("attempt", "result", "end", "equity")}
                                       for h in state.get(key + "_history", [])[-5:]]})
    events = [{"date": r["date"], "coin": coin_of(r["symbol"]), "symbol": r["symbol"], "variant": r.get("variant", "A"),
               "action": r["action"], "price": sig(float(r["price"])), "r": float(r["R"]) if r.get("R") not in ("", None) else None}
              for r in journal if r["action"] == "OPEN" or r["action"].startswith(("CLOSE", "TP"))][-20:]
    light = market_light(now_ms) if light == "?" else light
    market = None
    if light:
        pct, price, sma = light
        market = {"state": "bull" if pct > MARKET_BAND else "bear" if pct < -MARKET_BAND else "side",
                  "pct": round(pct, 2), "btc": sig(price), "sma200": sig(sma), "band": MARKET_BAND}
    data = {"updated": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_processed": max(st["last_processed"] for st in state["symbols"].values()),
            "rules": {"lookback": LOOKBACK, "stop_atr": STOP_ATR, "skip_range_atr": SKIP_RANGE_ATR, "trail_atr": TRAIL_ATR, "tp_r": [m for m, _ in TPS["B"]],
                      "fee": HH_FEE, "slippage": SLIPPAGE, "leverage": LEVERAGE, "near_pct": NEAR_PCT},
            "market": market, "symbols": symbols, "positions": positions, "challenges": challenges, "events": events,
            "bot": bot_results(state, journal), "setups": setups_export(setups or load_setups(), now_ms)}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    leaked = [v for v in secret_values() if v in text]
    if leaked:
        print("export: a secret value would be published; site/data.json NOT written")
        return None
    path = os.path.join(tempfile.gettempdir(), "data.json") if DRY_RUN else SITE_DATA
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)
    print(f"export: {len(symbols)} symbols, {len(positions)} positions -> {path} ({len(text) // 1024} KB)")
    return path


def try_export(*args, **kwargs):
    try:
        return export_site(*args, **kwargs)
    except Exception as e:      # the web app must never break a run
        print(f"export: failed ({type(e).__name__}: {e})")
        return None


# ---------- news headlines (site/news.json): titles and links only, never article text or images ----------

NEWS_PUBLISHED = "https://alex198514.github.io/meller-bot/news.json"   # last published file: keeps 7 days across runs
NEWS_DAYS, NEWS_MAX, NEWS_TIMEOUT = 7, 300, 15
NEWS_FEEDS = (("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss"),
              ("Cointelegraph", "https://cointelegraph.com/rss"),
              ("Decrypt", "https://decrypt.co/feed"))
BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={}&pageNo=1&pageSize=20"   # 30 is rejected (400)
BINANCE_CATALOGS = ((48, False), (161, True))         # (catalog, delisting?): 48 new listings, 161 delisting
BINANCE_LINK = "https://www.binance.com/en/support/announcement/detail/{}"
DELISTING_RE = re.compile(r"\b(delist\w*|monitoring tag|removal of (spot|margin) trading pairs|will remove)\b", re.I)
# Coin names matched case-sensitively with word boundaries (longest first, so "Bitcoin Cash" is not also Bitcoin)
COIN_NAMES = {
    "BTC": ["Bitcoin"], "ETH": ["Ethereum", "Ether"], "SOL": ["Solana"], "BNB": ["BNB Chain"], "XRP": ["Ripple"],
    "ADA": ["Cardano"], "DOGE": ["Dogecoin"], "LINK": ["Chainlink"], "LTC": ["Litecoin"], "AVAX": ["Avalanche"],
    "DOT": ["Polkadot"], "TRX": ["Tron", "TRON"], "ATOM": ["Cosmos Hub"], "XLM": ["Stellar"], "SHIB": ["Shiba Inu"],
    "AAVE": ["Aave"], "LDO": ["Lido"], "UNI": ["Uniswap"], "ZEC": ["Zcash"], "BCH": ["Bitcoin Cash"], "APT": ["Aptos"],
    "OP": ["OP Mainnet", "Optimism Foundation", "Optimism Superchain"], "ACH": ["Alchemy Pay"], "ANKR": ["Ankr"],
    "APE": ["ApeCoin"], "AR": ["Arweave"], "AUCTION": ["Bounce Finance"], "BEL": ["Bella Protocol"],
    "BICO": ["Biconomy"], "CAKE": ["PancakeSwap"], "CFX": ["Conflux"], "CHZ": ["Chiliz"], "CKB": ["Nervos"],
    "COMP": ["Compound Finance"], "DUSK": ["Dusk Network"], "EGLD": ["MultiversX", "Elrond"], "ENJ": ["Enjin"],
    "ENS": ["Ethereum Name Service"], "FET": ["Fetch.ai", "Artificial Superintelligence Alliance"],
    "FIL": ["Filecoin"], "GMT": ["STEPN"], "GRT": ["The Graph"], "HBAR": ["Hedera"], "ICP": ["Internet Computer"],
    "ILV": ["Illuvium"], "IMX": ["Immutable X", "ImmutableX", "Immutable zkEVM"], "INJ": ["Injective"],
    "JASMY": ["JasmyCoin"], "JOE": ["Trader Joe"], "LPT": ["Livepeer"], "LSK": ["Lisk"], "MANA": ["Decentraland"],
    "MASK": ["Mask Network"], "ONG": ["Ontology Gas"], "PEOPLE": ["ConstitutionDAO"], "POLYX": ["Polymesh"],
    "ROSE": ["Oasis Network", "Oasis Protocol"], "RSR": ["Reserve Rights"], "RUNE": ["THORChain"],
    "SAND": ["The Sandbox"], "SPELL": ["Spell Token"], "STX": ["Stacks"], "TRB": ["Tellor"], "VET": ["VeChain"],
    "YGG": ["Yield Guild Games"], "ZRX": ["0x Protocol"], "1INCH": ["1inch"],
}
# Tickers that are ordinary words or abbreviations in headlines: matched only as $TICKER, TICKERUSDT/USDC or by name
RISKY_TICKERS = {"OP", "AR", "GMT", "ACH", "BEL", "ONG", "JOE", "ROSE", "PEOPLE", "MASK", "STX", "UNI", "ENS", "APE"}


def news_patterns():
    pats = []
    for s in PAPER_SYMBOLS:
        tk = s[:-4]
        names = [re.escape(n) for n in COIN_NAMES.get(tk, [])]
        ticks = [r"\$" + re.escape(tk), re.escape(s), re.escape(tk + "USDC")] + ([] if tk in RISKY_TICKERS else [re.escape(tk)])
        for alt in names + ticks:
            pats.append((len(alt), re.compile(r"(?<![\w$])" + alt + r"(?![\w])"), s))
    return sorted(pats, key=lambda x: -x[0])


_NEWS_PATTERNS = []


def match_symbols(title):
    """Our symbols named in `title`: tickers (uppercase) and coin names with word boundaries, longest match first."""
    if not _NEWS_PATTERNS:
        _NEWS_PATTERNS.extend(news_patterns())
    text, found = title, []
    for _, rx, sym in _NEWS_PATTERNS:
        if rx.search(text):
            if sym not in found:
                found.append(sym)
            text = rx.sub(" ", text)                  # a longer name ("Bitcoin Cash") hides its parts
    return [s for s in PAPER_SYMBOLS if s in found]


def http_get(url, limit=3_000_000, hops=3):
    """GET with a timeout and a size cap; follows 307/308 too (urllib before Python 3.11 does not)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MellerBot/1.0)", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=NEWS_TIMEOUT) as resp:
            return resp.read(limit)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") if e.code in (307, 308) else None
        if loc and hops > 0:
            return http_get(urllib.parse.urljoin(url, loc), limit, hops - 1)
        raise


def clean_title(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()[:300]


def rss_items(source, url):
    """[(title, link, published ms)] from an RSS 2.0 or Atom feed: titles and links only."""
    root = ET.fromstring(http_get(url))
    out = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.rsplit("}", 1)[-1] == name), None)
        title, link = get("title"), get("link")
        href = (link.get("href") or link.text or "").strip() if link is not None else ""
        when = get("pubDate") if tag == "item" else (get("published") or get("updated"))
        try:
            ms = (int(parsedate_to_datetime(when.text.strip()).timestamp() * 1000) if tag == "item" else
                  int(datetime.fromisoformat(when.text.strip().replace("Z", "+00:00")).timestamp() * 1000))
        except Exception:
            continue
        if title is not None and href.startswith(("https://", "http://")):
            out.append((clean_title(title.text), href, ms))
    return out


def binance_items(catalog):
    data = json.loads(http_get(BINANCE_CMS.format(catalog)))
    out = []
    for cat in (data.get("data") or {}).get("catalogs") or []:
        for a in cat.get("articles") or []:
            if a.get("code") and a.get("title") and a.get("releaseDate"):
                out.append((clean_title(a["title"]), BINANCE_LINK.format(a["code"]), int(a["releaseDate"])))
    return out


def build_news(now_ms):
    """Merge the latest headlines into SITE_NEWS (last NEWS_DAYS days, at most NEWS_MAX, deduped by link)."""
    items = {}
    previous = None
    try:
        with open(SITE_NEWS) as fh:
            previous = json.load(fh)
    except (OSError, ValueError):
        try:
            previous = json.loads(http_get(NEWS_PUBLISHED))
        except Exception as e:
            print(f"news: no previous news.json ({type(e).__name__})")
    for it in (previous or {}).get("items", []):
        if str(it.get("link", "")).startswith(("https://", "http://")):
            items[it["link"]] = it
    sources = [(name, lambda u=url, n=name: rss_items(n, u), False) for name, url in NEWS_FEEDS]
    sources += [("Binance", lambda c=cat: binance_items(c), delist) for cat, delist in BINANCE_CATALOGS]
    for name, fetch, delist_catalog in sources:
        try:
            got = fetch()
        except Exception as e:                            # a failing source is skipped, the others still count
            print(f"news: {name} skipped ({type(e).__name__}: {str(e)[:80]})")
            continue
        new = 0
        for title, link, ms in got:
            if not title or link in items:
                continue
            items[link] = {"title": title, "source": name, "link": link,
                           "published": datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "delisting": bool(name == "Binance" and (delist_catalog or DELISTING_RE.search(title)))}
            new += 1
        print(f"news: {name} {len(got)} items, {new} new")
    cutoff = datetime.fromtimestamp(now_ms / 1000 - NEWS_DAYS * 86400, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    keep = sorted((it for it in items.values() if it["published"] >= cutoff), key=lambda it: it["published"], reverse=True)
    keep = keep[:NEWS_MAX]
    for it in keep:                                       # re-match every run: the matching may have improved
        it["symbols"] = match_symbols(it["title"])
        it.pop("text", None)
        it.pop("image", None)
    data = {"updated": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days": NEWS_DAYS, "items": [{k: it[k] for k in ("title", "source", "link", "published", "symbols", "delisting")}
                                         for it in keep]}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if any(v in text for v in secret_values()):
        print("news: a secret value would be published; site/news.json NOT written")
        return None
    path = os.path.join(tempfile.gettempdir(), "news.json") if DRY_RUN else SITE_NEWS
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)
    print(f"news: {len(keep)} items ({sum(bool(i['symbols']) for i in keep)} about our coins, "
          f"{sum(i['delisting'] for i in keep)} delisting) -> {path}")
    return path


def try_news(now_ms):
    try:
        return build_news(now_ms)
    except Exception as e:      # news must never break a run
        print(f"news: failed ({type(e).__name__}: {e})")
        return None


# ---------- --watch: intraday alerts from hourly candles ----------

def load_alerts():
    try:
        with open(ALERTS) as fh:
            a = json.load(fh)
    except (OSError, ValueError):
        a = {}
    a.setdefault("positions", {})                   # "<variant>:<symbol>:<entry date>" -> ["TP1", "TP2", "STOP"]
    a.setdefault("near", {})                        # coin -> UTC day of the last "near breakout" alert
    return a


def candle_atr(bar, atr):
    """A daily candle's range (high - low) in filtered ATRs, or None."""
    return (bar["high"] - bar["low"]) / atr if bar and atr else None


def filter_line(ratio):
    """The 2 ATR candle filter for today's candle so far, in Russian (empty if unknown)."""
    if ratio is None:
        return ""
    if ratio > SKIP_RANGE_ATR:
        return (f"Свеча уже {ratio:.1f} ATR (фильтр {SKIP_RANGE_ATR:g} ATR). "
                f"Если закроется выше уровня, вход будет пропущен.")
    return f"Свеча {ratio:.1f} ATR, фильтр пройден. Если закроется выше уровня, будет сигнал BUY."


def near_alert(coin, dist, level, live, ratio):
    """(title, text) of the watch alert for a flat symbol near (or above) its breakout level."""
    title = f"👀 {coin} в {dist:.1f}% от входа" if dist > 0 else f"👀 {coin} уже выше уровня входа"
    text = f"Сигнал будет после дневного закрытия в 01:00, если закроется выше {px(level)}. Сейчас {px(live)}."
    line = filter_line(ratio)
    return title, text + ("\n" + line if line else "")


def skip_alert(coin, ratio):
    """(title, text) of the daily push for a breakout the 2 ATR filter skipped."""
    return (f"⏸ {coin}: пробой без входа",
            f"{coin}: пробой без входа. Свеча {ratio:.1f} ATR больше {SKIP_RANGE_ATR:g} ATR, вход пропущен по правилам.")


def watch_alerts(state, now_ms, alerts, hourly, daily):
    """[(alert id, title, text)] not sent yet. `hourly(symbol, start_ms)` -> hourly candles from start_ms to now;
    `daily(symbol)` -> (closed daily bars, live price). Updates nothing."""
    today, out = day_str(now_ms), []
    for s, st in sorted(state["symbols"].items()):
        open_pos = [(v, st[key]) for v, key in POS_KEY.items() if st.get(key)]
        if not open_pos:
            continue
        coin = coin_of(s)
        try:
            hours = hourly(s, close_ms(st["last_processed"]))      # everything after the last processed close
        except Exception as e:
            print(f"watch {s}: hourly candles failed ({type(e).__name__}: {e})")
            continue
        if not hours:
            continue
        hi, lo = max(float(k[2]) for k in hours), min(float(k[3]) for k in hours)
        for v, pos in open_pos:
            pid = f"{v}:{s}:{pos['entry_date']}"
            tps, hit = pos.get("tp") or [], pos.get("hit", [])
            where = f"Вариант {v}, вход {pos['entry_date']} по {px(pos['entry'])}."
            checks = []
            if len(tps) > 0 and 0 not in hit and hi >= tps[0]:
                checks.append(("TP1", f"🎯 TP1 {coin}: закрой 1/3 и перенеси стоп в безубыток ({px(pos['entry'])})",
                               f"Максимум {px(hi)} коснулся TP1 {px(tps[0])}. {where}"))
            if len(tps) > 1 and 1 not in hit and hi >= tps[1]:
                checks.append(("TP2", f"🎯 TP2 {coin}: закрой ещё 1/3",
                               f"Максимум {px(hi)} коснулся TP2 {px(tps[1])}. {where}"))
            if lo <= pos["stop"]:
                checks.append(("STOP", f"⚪ {coin} у стопа",
                               f"Минимум {px(lo)} коснулся стопа {px(pos['stop'])}. {where} "
                               f"Проверьте в «Позиции», что позиция закрыта."))
            sent = alerts["positions"].get(pid, [])
            out += [((pid, kind), title, text) for kind, title, text in checks if kind not in sent]
    for s in PAPER_SYMBOLS:                         # all 75 (retired symbols are not in it)
        st, coin = state["symbols"].get(s), coin_of(s)
        if not st or st.get("position_b") or alerts["near"].get(coin) == today:
            continue                                # B holds it (no new entry possible), or already told today
        try:
            bars, live = daily(s)
        except Exception as e:
            print(f"watch {s}: daily candles failed ({type(e).__name__}: {e})")
            continue
        level = watch(bars)["breakout_above"]
        dist = 100 * (level / live - 1)
        if dist > NEAR_PCT:
            continue
        # the 2 ATR filter on today's candle so far, with the ATR process_day would use at today's close
        ratio = candle_atr(TODAY_BAR.get(s), filtered_atr(bars, len(bars)))
        title, text = near_alert(coin, dist, level, live, ratio)
        out.append((("near", coin), title, text))
    return out


# ---------- intraday setup scanner (1H / 4H): labelled setups, NOT tested signals; strategy B is not affected ----------

SETUPS = "setups.json"            # every setup and its outcome (committed by the watch run)
SETUP_TF_MS = {"1h": 3_600_000, "4h": 14_400_000}
SETUP_LOOKBACK = 20               # close beyond the high / low of the previous 20 candles
SETUP_VOL_X = 1.5                 # candle volume at least 1.5x the previous 20 candles' average
SETUP_RANGE_ATR = 2.5             # candle range under 2.5 ATR(14) of the timeframe
SETUP_ATR_N = 14                  # ATR = mean true range of the 14 candles before the setup candle
SETUP_STOP_ATR = 1.5
SETUP_TP_R = (1.5, 3.0)           # half the position at each take profit; stop to breakeven after TP1
SETUP_EXPIRE_BARS = 48            # old rule (setups made before exit_ms existed): closed at the 48th candle
SETUP_EXIT_MS = DAY_MS            # intraday exit: not closed by TP or stop within 24 hours -> closed at that close
SETUP_FEE_RT = 0.0006             # round trip, on the notional at entry
SETUP_RISK_USD = CH_RISK * CH_BALANCE     # $50 on the $10,000 account
SETUP_TRACK = ("5m", 300_000)     # candles the outcomes are checked on
SETUP_CARD_BARS = 60
SETUP_SCAN_BARS = 1000            # candles fetched per symbol and timeframe (Binance maximum, incl. the open one)
WAVE_TITLE = "🌊 Волна 3 (эксперимент)"   # second signal type (wave_test.py rules), one target, same 24 h exit
SETUP_NOTE = "Новая стратегия, статистика копится."
SETUP_PUSH_TFS = ("1h", "4h")     # pushed timeframes
SETUP_PUSH = True                 # 17.11.2026, confirmed by the user (CLAUDE.md): training pushes for all three types
SETUP_PUSH_RISK_USD = 10.0        # the push's size is for this risk (training on small sums); records keep SETUP_RISK_USD
TRAINING_TITLE = "🧪 Тренировка"
TRAINING_LINE = "Наблюдение, не рекомендация. Риск не больше $10."
FRIEND_TITLE = "🤝 Сетап друга"
SETUP_PUSH_MAX = 3                # pushes per run in total: the highest relative volume (vol_x) first
SETUP_PUSH_GAP_MS = 12 * 3_600_000    # no second push for a symbol within 12 hours
SETUP_LIVE_SINCE = "2026-11-15"   # live tracking started (stats in the app count only setups from this day)
SETUP_DRY_RUN = {"from": "2026-11-08", "to": "2026-11-15", "stats": {"all": {"n": 963, "closed": 963, "win": 56.5, "avg_r": 0.407, "total_r": 392.236}, "1h": {"n": 708, "closed": 708, "win": 54.8, "avg_r": 0.423, "total_r": 299.454}, "4h": {"n": 255, "closed": 255, "win": 61.2, "avg_r": 0.364, "total_r": 92.782}, "long": {"n": 165, "closed": 165, "win": 20.6, "avg_r": -0.591, "total_r": -97.499}, "short": {"n": 798, "closed": 798, "win": 63.9, "avg_r": 0.614, "total_r": 489.735}, "with": {"n": 926, "closed": 926, "win": 58.5, "avg_r": 0.46, "total_r": 425.894}, "against": {"n": 37, "closed": 37, "win": 5.4, "avg_r": -0.91, "total_r": -33.658}, "breakout": {"n": 751, "closed": 751, "win": 56.9, "avg_r": 0.471, "total_r": 353.976}, "wave": {"n": 212, "closed": 212, "win": 55.2, "avg_r": 0.18, "total_r": 38.26}}, "days30": {"from": "2026-10-17", "to": "2026-11-16", "stats": {"all": {"n": 3246, "closed": 3237, "win": 43.5, "avg_r": -0.005, "total_r": -15.003}, "1h": {"n": 2542, "closed": 2535, "win": 44.9, "avg_r": 0.031, "total_r": 79.349}, "4h": {"n": 704, "closed": 702, "win": 38.6, "avg_r": -0.134, "total_r": -94.352}, "long": {"n": 1001, "closed": 999, "win": 26.3, "avg_r": -0.45, "total_r": -449.831}, "short": {"n": 2245, "closed": 2238, "win": 51.2, "avg_r": 0.194, "total_r": 434.828}, "with": {"n": 1762, "closed": 1755, "win": 43.9, "avg_r": 0.045, "total_r": 78.704}, "against": {"n": 1484, "closed": 1482, "win": 43.0, "avg_r": -0.063, "total_r": -93.707}, "breakout": {"n": 2516, "closed": 2509, "win": 41.9, "avg_r": -0.002, "total_r": -4.764}, "wave": {"n": 730, "closed": 728, "win": 49.2, "avg_r": -0.014, "total_r": -10.239}}}, "note": "replay of the live scanner (126 coins, breakout + wave-3); 14.11 alone gave +411.9R of the week's +392.2R"}   # replay before / around going live (setups_replay, 2026-11-16)


def kline_bars(raw, now_ms):
    """Closed candles from Binance klines as dicts (t = open time ms, ct = close time ms)."""
    return [{"t": k[0], "ct": k[6], "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
             "close": float(k[4]), "volume": float(k[5])} for k in raw if k[6] < now_ms]


def setup_at(bars, i):
    """The setup on the closed candle bars[i] (dict without symbol / tf), or None."""
    if i < max(SETUP_LOOKBACK, SETUP_ATR_N + 1):
        return None
    b, prev = bars[i], bars[i - SETUP_LOOKBACK:i]
    trs = [max(bars[j]["high"] - bars[j]["low"], abs(bars[j]["high"] - bars[j - 1]["close"]),
               abs(bars[j]["low"] - bars[j - 1]["close"])) for j in range(i - SETUP_ATR_N, i)]
    atr, avg_vol = sum(trs) / len(trs), sum(x["volume"] for x in prev) / len(prev)
    if atr <= 0 or avg_vol <= 0 or b["volume"] < SETUP_VOL_X * avg_vol or b["high"] - b["low"] >= SETUP_RANGE_ATR * atr:
        return None
    hi, lo = max(x["high"] for x in prev), min(x["low"] for x in prev)
    side = "long" if b["close"] > hi else "short" if b["close"] < lo else None
    if not side:
        return None
    sgn, entry, risk = (1 if side == "long" else -1), b["close"], SETUP_STOP_ATR * atr
    qty = SETUP_RISK_USD / risk
    return {"side": side, "t": b["t"], "close_ms": b["ct"] + 1, "entry": entry, "stop": entry - sgn * risk,
            "tp": [entry + sgn * m * risk for m in SETUP_TP_R], "atr": atr, "level": hi if side == "long" else lo,
            "vol_x": round(b["volume"] / avg_vol, 2), "range_atr": round((b["high"] - b["low"]) / atr, 2),
            "notional": round(qty * entry, 2), "margin": round(qty * entry / LEVERAGE, 2)}


def new_setup(symbol, tf, s):
    """A setups.json record of the setup `s` found by setup_at()."""
    rec = {"id": f"{'wave:' if s.get('type') == 'wave' else ''}{tf}:{symbol}:{s['t']}", "symbol": symbol, "coin": coin_of(symbol), "name": hh_name(symbol), "tf": tf,
           "time": datetime.fromtimestamp(s["close_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "exit_ms": s["close_ms"] + SETUP_EXIT_MS,
           "expires": datetime.fromtimestamp((s["close_ms"] + SETUP_EXIT_MS) / 1000,
                                             tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "status": "open", "tp1_hit": False, "checked_ms": s["close_ms"], "last": sig(s["entry"])}
    rec.update({k: sig(s[k]) for k in ("entry", "stop", "level", "atr", "notional", "margin")})
    rec.update({k: s[k] for k in ("side", "close_ms", "vol_x", "range_atr")})
    rec["tp"] = [sig(x) for x in s["tp"]]
    if s.get("type") == "wave":
        rec.update({"type": "wave", "ret": s["ret"], "rr": s["rr"]})
    return rec


def wave_at(bars):
    """The wave-3 entry on the last closed candle of `bars` (wave_test.run rules, unchanged: ZigZag 3 ATR on closes,
    wave 2 retraces 38.2-78.6% without breaking the start of wave 1, stop order at the top of wave 1, stop = wave 2
    low, target = wave 2 low + 1.618 x wave 1; short mirrored), as a setup dict like setup_at(), or None."""
    import wave_test
    b = [{"t": x["t"], "o": x["open"], "h": x["high"], "l": x["low"], "c": x["close"]} for x in bars]
    hits, last = [], len(b) - 1
    wave_test.run(b, "", on_entry=lambda i, st, fill: hits.append((st, fill)) if i == last else None)
    if not hits:
        return None
    st, entry = hits[-1]
    x, sgn = bars[last], st["side"]
    risk = sgn * (entry - st["inv"])
    a = wave_test.atrs(b)[last] or 0
    prev = bars[last - SETUP_LOOKBACK:last]
    avg_vol = sum(y["volume"] for y in prev) / len(prev) if prev else 0
    qty = SETUP_RISK_USD / risk
    return {"type": "wave", "side": "long" if sgn == 1 else "short", "t": x["t"], "close_ms": x["ct"] + 1,
            "entry": entry, "stop": st["inv"], "tp": [st["tp"]], "atr": a, "level": st["trig"],
            "ret": round(st["ret"], 3), "rr": round(sgn * (st["tp"] - entry) / risk, 2),
            "vol_x": round(x["volume"] / avg_vol, 2) if avg_vol else 0,
            "range_atr": round((x["high"] - x["low"]) / a, 2) if a else 0,
            "notional": round(qty * entry, 2), "margin": round(qty * entry / LEVERAGE, 2),
            "same_bar_stop": (x["low"] <= st["inv"]) if sgn == 1 else (x["high"] >= st["inv"])}


def setup_type(rec):
    """"breakout" or "wave"; records made before the field existed are breakouts."""
    return rec.get("type") or "breakout"


def setup_r(rec, exit_px=None):
    """R of a setup after the round-trip fee: half off at TP1, half at TP2 (or at `exit_px` on expiry / open).
    A wave setup has one target: all of it at the target ("tp"), the stop or `exit_px`."""
    sgn, risk = (1 if rec["side"] == "long" else -1), abs(rec["entry"] - rec["stop"])
    move = lambda p: sgn * (p - rec["entry"]) / risk
    st = rec["status"]
    if len(rec["tp"]) == 1:
        r = -1.0 if st == "stop" else move(rec["tp"][0]) if st == "tp" else move(exit_px)
        return r - SETUP_FEE_RT * rec["entry"] / risk
    if st == "stop":
        r = -1.0
    elif st == "tp1_be":
        r = 0.5 * SETUP_TP_R[0]
    elif st == "tp2":
        r = 0.5 * SETUP_TP_R[0] + 0.5 * SETUP_TP_R[1]
    else:                                           # time exit / open: the rest at exit_px
        r = 0.5 * SETUP_TP_R[0] + 0.5 * move(exit_px) if rec["tp1_hit"] else move(exit_px)
    return r - SETUP_FEE_RT * rec["entry"] / risk


def setup_exit_ms(rec):
    """When an open setup is closed at the market: 24 hours after its candle (older records: 48 candles)."""
    return rec.get("exit_ms") or rec["close_ms"] + SETUP_EXPIRE_BARS * SETUP_TF_MS[rec["tf"]]


def track_setup(rec, candles):
    """Advance an open setup over `candles` (closed SETUP_TRACK candles as dicts, oldest first). Stop and a take
    profit touched in the same candle: the stop counts. In the candle that touches TP1 a dip to the entry counts as
    TP1 then breakeven. Still open at setup_exit_ms() (24 hours): closed at the close of the last candle before it,
    status "time". A single target that is not beyond the entry (a gap fill past it) is no target: stop or time only."""
    if rec["status"] != "open":
        return rec
    sgn = 1 if rec["side"] == "long" else -1
    one = len(rec["tp"]) == 1                       # wave: one target, no breakeven step
    tp1, tp2 = (rec["tp"][0], rec["tp"][0]) if one else rec["tp"]
    valid_tp = not one or sgn * (tp1 - rec["entry"]) > 0
    expires = setup_exit_ms(rec)
    reached = lambda price, c: (c["high"] >= price) if sgn > 0 else (c["low"] <= price)   # in the trade's favour
    against = lambda price, c: (c["low"] <= price) if sgn > 0 else (c["high"] >= price)
    when = lambda c: datetime.fromtimestamp(c["ct"] / 1000 + 0.001, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    for c in candles:
        if c["t"] < rec["checked_ms"] or c["t"] >= expires:
            continue
        rec["checked_ms"], rec["last"] = c["ct"] + 1, sig(c["close"])
        done = None
        if one:
            if against(rec["stop"], c):
                done = ("stop", rec["stop"])
            elif valid_tp and reached(tp1, c):
                done = ("tp", tp1)
        elif not rec["tp1_hit"]:
            if against(rec["stop"], c):
                done = ("stop", rec["stop"])
            elif reached(tp2, c):
                rec["tp1_hit"], done = True, ("tp2", tp2)
            elif reached(tp1, c):
                rec["tp1_hit"], rec["tp1_time"] = True, when(c)
                if against(rec["entry"], c):
                    done = ("tp1_be", rec["entry"])
        elif against(rec["entry"], c):
            done = ("tp1_be", rec["entry"])
        elif reached(tp2, c):
            done = ("tp2", tp2)
        if not done and c["ct"] + 1 >= expires:
            done = ("time", c["close"])
        if done:
            rec["status"], rec["exit"], rec["exit_time"] = done[0], sig(done[1]), when(c)
            rec["r"] = round(setup_r(rec, done[1]), 3)
            break
    return rec


def load_setups():
    try:
        with open(SETUPS) as fh:
            d = json.load(fh)
        return d if isinstance(d.get("setups"), list) else {"setups": []}
    except (OSError, ValueError, AttributeError):
        return {"setups": []}


def save_setups(book):
    tmp = SETUPS + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)
    os.replace(tmp, SETUPS)


def setup_stats(setups):
    """Closed setups: count, win rate (R > 0), average and total R; overall and per timeframe and side."""
    def one(rows):
        rs = [x["r"] for x in rows if x["status"] != "open" and x.get("r") is not None]
        return {"n": len(rows), "closed": len(rs), "win": round(100 * sum(r > 0 for r in rs) / len(rs), 1) if rs else None,
                "avg_r": round(sum(rs) / len(rs), 3) if rs else None, "total_r": round(sum(rs), 3)}
    out = {"all": one(setups)}
    for k, f in (("1h", lambda x: x["tf"] == "1h"), ("4h", lambda x: x["tf"] == "4h"),
                 ("long", lambda x: x["side"] == "long"), ("short", lambda x: x["side"] == "short"),
                 ("with", lambda x: not x.get("against")), ("against", lambda x: bool(x.get("against"))),
                 ("breakout", lambda x: setup_type(x) == "breakout"), ("wave", lambda x: setup_type(x) == "wave")):
        out[k] = one([x for x in setups if f(x)])
    return out


def push_size(rec):
    """(notional, margin at 5x) of a setup for the push risk SETUP_PUSH_RISK_USD ($10)."""
    k = SETUP_PUSH_RISK_USD / SETUP_RISK_USD
    return rec["notional"] * k, rec["margin"] * k


def setup_text(rec):
    """(title, text) of the Russian training push: "🧪 Тренировка · <type> · ...", first line TRAINING_LINE,
    entry, stop, targets, size for SETUP_PUSH_RISK_USD."""
    kind = setup_type(rec)
    title = f"СИГНАЛ {rec['tf'].upper()} · {rec['side'].upper()} {rec['name']}"
    wave = kind == "wave"
    title = f"{TRAINING_TITLE} · {WAVE_TITLE if wave else FRIEND_TITLE if kind == 'friend' else 'Пробой'} · {title}"
    notional, margin = push_size(rec)
    size = f"Размер {notional:,.0f} USDT · маржа 5x {margin:,.0f} USDT (риск ${SETUP_PUSH_RISK_USD:g})\n"
    if kind == "friend":
        return title, (f"{TRAINING_LINE}\nЛимитная заявка на линии {px(rec['entry'])} (цена идёт за линией, 12 свечей 15m) · "
                       f"стоп {px(rec['stop'])}\nTP1 {px(rec['tp'][0])} (половина, затем стоп в безубыток) · TP2 {px(rec['tp'][1])}\n"
                       f"{size}Максимум 48 часов в сделке.")
    warn = ""
    if rec.get("against"):
        title += f" {SETUP_AGAINST}"
        warn = f"{SETUP_AGAINST}: {'лонг на медвежьем' if rec['side'] == 'long' else 'шорт на бычьем'} рынке\n"
    tps = (f"Цель {px(rec['tp'][0])} (R:R 1:{rec['rr']:.1f}) · откат волны 2 {100 * rec['ret']:.0f}%\n" if wave else
           f"TP1 {px(rec['tp'][0])} · TP2 {px(rec['tp'][1])}\n")
    lo = rec["side"] == "long"
    text = (f"{TRAINING_LINE}\n{warn}{('Вход стоп-ордером на пробое ' + ('вершины' if lo else 'дна') + ' волны 1: ') if wave else 'Вход '}"
            f"{px(rec['entry'])} · стоп {px(rec['stop'])}{(' (' + ('дно' if lo else 'вершина') + ' волны 2)') if wave else ''}"
            f"\n{tps}"
            f"{size}Максимум 24 часа в сделке.")
    return title, text


def setup_card(rec, bars):
    """PNG bytes of the intraday signal card (the BUY card's layout, badge "СИГНАЛ 1H" / "СИГНАЛ 4H"): coin, side · timeframe · R:R, volume chip;
    entry | stop; TP1, TP2, risk; the last SETUP_CARD_BARS candles of its timeframe with the levels; one line of
    context; size in USDT and margin at 5x; the "not a tested signal" line. Needs Pillow."""
    from PIL import Image, ImageDraw
    f, long_ = card_font, rec["side"] == "long"
    wave = setup_type(rec) == "wave"
    entry, stop = rec["entry"], rec["stop"]
    tp1, tp2 = (rec["tp"][0], rec["tp"][0]) if wave else rec["tp"]
    side_col = C_GREEN if long_ else C_RED
    pct = lambda p: 100 * (p / entry - 1)
    img = Image.new("RGB", (CARD_W, CARD_H), C_BG)
    d = ImageDraw.Draw(img)
    d.text((50, 62), rec["name"], font=f(64, True), fill=C_TEXT, anchor="lm")
    badge = f"{'ВОЛНА 3' if wave else 'СИГНАЛ'} {rec['tf'].upper()}"
    bw = d.textlength(badge, font=f(34, True)) + 36
    d.rounded_rectangle((1030 - bw, 32, 1030, 92), 12, fill=C_GOLD)
    d.text((1030 - bw / 2, 62), badge, font=f(34, True), fill=C_BG, anchor="mm")
    x = 50
    rr = f"{rec['rr']:.1f}" if wave else f"{SETUP_TP_R[1]:g}"
    for text, col, filled in ((f"{rec['side'].upper()} · {rec['tf'].upper()} · R:R 1:{rr}", side_col, True),
                              (f"объём ×{rec['vol_x']:.1f}", C_GOLD, False)):
        w = d.textlength(text, font=f(28, True)) + 40
        if filled:
            d.rounded_rectangle((x, 112, x + w, 162), 12, fill=col)
            d.text((x + w / 2, 137), text, font=f(28, True), fill=C_BG, anchor="mm")
        else:
            d.rounded_rectangle((x, 112, x + w, 162), 12, outline=col, width=3)
            d.text((x + w / 2, 137), text, font=f(28, True), fill=col, anchor="mm")
        x += w + 16
    d.text((1030, 137), rec["time"].replace("T", " ").replace("Z", " UTC"), font=f(24), fill=C_MUTED, anchor="rm")
    d.rounded_rectangle((40, 185, 1040, 285), 16, fill=C_PANEL)
    d.line((540, 205, 540, 265), fill=C_GRID, width=2)
    d.text((70, 215), "Вход", font=f(24), fill=C_MUTED, anchor="lm")
    d.text((70, 255), px(entry), font=f(38, True), fill=C_TEXT, anchor="lm")
    d.text((570, 215), "Стоп", font=f(24), fill=C_MUTED, anchor="lm")
    d.text((570, 255), px(stop), font=f(38, True), fill=C_RED, anchor="lm")
    d.text((1010, 255), f"{pct(stop):+.2f}%", font=f(30, True), fill=C_RED, anchor="rm")
    boxes = ((f"Тейк 1 · {SETUP_TP_R[0]:g}R", f"{pct(tp1):+.2f}%", px(tp1), C_GREEN),
             (f"Тейк 2 · {SETUP_TP_R[1]:g}R", f"{pct(tp2):+.2f}%", px(tp2), C_GREEN),
             ("Риск", f"${SETUP_PUSH_RISK_USD:g}", "тренировка", C_GOLD))
    if wave:
        boxes = ((f"Цель · {rec['rr']:.1f}R", f"{pct(tp1):+.2f}%", px(tp1), C_GREEN),
                 ("Откат волны 2", f"{100 * rec['ret']:.0f}%", "38–79% волны 1", C_GOLD),
                 boxes[2])
    for k, (label, big, small, col) in enumerate(boxes):
        x0 = 40 + k * 340
        d.rounded_rectangle((x0, 305, x0 + 320, 435), 16, fill=C_PANEL, outline=col if k < 2 else C_GRID, width=2)
        d.text((x0 + 24, 335), label, font=f(24), fill=C_MUTED, anchor="lm")
        d.text((x0 + 24, 375), big, font=f(34, True), fill=col, anchor="lm")
        d.text((x0 + 24, 412), small, font=f(24), fill=C_TEXT, anchor="lm")
    levels = [(tp2, C_GREEN, "TP2"), (tp1, C_GREEN, "TP1"), (entry, C_BLUE, "ВХОД"), (stop, C_RED, "СТОП")]
    if wave:
        levels = [(tp1, C_GREEN, "ЦЕЛЬ"), (entry, C_BLUE, "ВХОД"), (stop, C_RED, "СТОП")]
    card_chart(d, bars[-SETUP_CARD_BARS:], levels if long_ else levels[::-1], min(stop, tp2), max(stop, tp2))
    where = "выше максимума" if long_ else "ниже минимума"
    sentence = (f"Закрытие {where} 20 свечей {rec['tf'].upper()}, объём ×{rec['vol_x']:.1f} среднего, "
                f"свеча {rec['range_atr']:.1f} ATR. Максимум 24 часа в сделке.")
    if wave:
        sentence = (f"Волна 2 откатила {100 * rec['ret']:.0f}% волны 1, цена пробила "
                    f"{'вершину' if long_ else 'дно'} волны 1. Эксперимент. Максимум 24 часа в сделке.")
    words, cur, wrapped = sentence.split(), "", []
    for w_ in words:
        nxt = f"{cur} {w_}".strip()
        if d.textlength(nxt, font=f(30)) > 980 and cur:
            wrapped.append(cur)
            cur = w_
        else:
            cur = nxt
    wrapped.append(cur)
    for i, line in enumerate(wrapped[:2]):
        d.text((50, 1100 + i * 40), line, font=f(30), fill=C_TEXT, anchor="lm")
    d.line((40, 1200, 1040, 1200), fill=C_GRID, width=2)
    notional, margin = push_size(rec)
    d.text((50, 1250), f"Размер: {notional:,.0f} USDT", font=f(42, True), fill=C_TEXT, anchor="lm")
    d.text((1030, 1250), f"маржа 5x: {margin:,.0f} USDT", font=f(30), fill=C_GOLD, anchor="rm")
    d.text((50, 1305), TRAINING_LINE, font=f(26, True), fill=C_GOLD, anchor="lm")
    if rec.get("against"):                              # the card font has no emoji: plain text label
        d.text((1030, 1305), "ПРОТИВ РЫНКА", font=f(26, True), fill=C_RED, anchor="rm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def setup_klines(symbol, tf, now_ms):
    """Closed candles of `symbol` on `tf`, enough for the scan and the card."""
    raw = fetch_json(f"/api/v3/klines?symbol={symbol}&interval={tf}&limit={SETUP_SCAN_BARS}")
    return kline_bars(raw, now_ms)


def setup_filter(state):
    """The market direction for new intraday signals: {"market": state, "allowed": "short" / "long" / "both"}.
    Bear market (BTC under its SMA200 band): shorts are with the market; bull: longs; sideways or unknown: both.
    Nothing is skipped: a signal against it is stored and pushed with "against": true."""
    return {"market": state, "allowed": {"bear": "short", "bull": "long"}.get(state, "both")}


SETUP_AGAINST = "⚠️ против рынка"


def backfill_against(book):
    """Records made before "against" existed get it from the market (market_light) at the time of their candle."""
    states = {}
    for rec in book["setups"]:
        if "against" in rec:
            continue
        day = rec["time"][:10]
        if day not in states:
            light = market_light(rec["close_ms"])
            states[day] = None if not light else ("bull" if light[0] > MARKET_BAND else
                                                   "bear" if light[0] < -MARKET_BAND else "side")
        allowed = setup_filter(states[day])["allowed"]
        rec["against"] = allowed != "both" and rec["side"] != allowed
        print(f"setups {rec['id']}: against = {rec['against']} (market {states[day]} at {rec['time']})")


def fix_setup_statuses(book):
    """Old records: "expired" -> "time" (the 24-hour exit), and a single-target record closed as "tp" although its
    target was not beyond the entry (a gap fill past it, e.g. DASH 4H wave short 15.11) is tracked again from its
    candle with stop and time only (track_setup ignores such a target)."""
    for rec in book["setups"]:
        if rec["status"] == "expired":
            rec["status"] = "time"
        sgn = 1 if rec["side"] == "long" else -1
        if rec["status"] == "tp" and len(rec["tp"]) == 1 and sgn * (rec["tp"][0] - rec["entry"]) <= 0:
            for k in ("exit", "exit_time", "r"):
                rec.pop(k, None)
            rec.update(status="open", checked_ms=rec["close_ms"], last=rec["entry"])
            print(f"setups {rec['id']}: was 'tp' with the target not beyond the entry; tracked again (stop / time)")


def run_setups(now_ms, book, symbols=SCANNER_SYMBOLS, push=True):
    """One watch-run pass: advance every open setup on SETUP_TRACK candles up to now, then scan the last closed
    1H and 4H candle of every symbol; a symbol with an open setup on that timeframe is skipped. A new signal
    against the market (setup_filter: long in a bear market, short in a bull one) is kept and pushed as usual with
    "against": true and the SETUP_AGAINST label. Each symbol and timeframe is also scanned for a wave-3 entry
    (wave_at, "type": "wave", one target) on the same SETUP_SCAN_BARS candles; open setups block only their own
    type. Pushes each new setup (card + text). Returns (new setups, {symbol: 24h volume from the hourly candles})."""
    tf_name, tf_ms = SETUP_TRACK
    flt = setup_filter(market_state(now_ms))
    backfill_against(book)
    fix_setup_statuses(book)
    against = 0
    for rec in book["setups"]:
        if rec["status"] != "open" or setup_type(rec) == "friend":
            continue
        end = min(now_ms, setup_exit_ms(rec))
        try:
            candles = kline_bars(fetch_candles(rec["symbol"], rec["checked_ms"], end, tf_name), now_ms)
        except Exception as e:
            print(f"setups {rec['id']}: {tf_name} candles failed ({type(e).__name__}: {e}); checked next run")
            continue
        track_setup(rec, candles)
        if rec["status"] != "open":
            print(f"setups {rec['id']}: {rec['status']} at {rec['exit']} ({rec['r']:+.2f}R)")
    known = {r["id"] for r in book["setups"]}
    busy = {(r["symbol"], r["tf"], setup_type(r)) for r in book["setups"] if r["status"] == "open" and setup_type(r) != "friend"}
    found, vol24 = [], {}
    for s in symbols:
        for tf in SETUP_TF_MS:
            try:
                bars = setup_klines(s, tf, now_ms)
            except Exception as e:
                print(f"setups {s} {tf}: candles failed ({type(e).__name__}: {e})")
                continue
            if tf == "1h" and len(bars) >= 24:
                vol24[s] = sum(b["volume"] for b in bars[-24:])
            if not bars:
                continue
            hits = []
            if (s, tf, "breakout") not in busy:
                hits.append(("breakout", setup_at(bars, len(bars) - 1)))
            if (s, tf, "wave") not in busy:
                try:
                    hits.append(("wave", wave_at(bars)))
                except Exception as e:
                    print(f"setups {s} {tf}: wave scan failed ({type(e).__name__}: {e})")
            for kind, hit in hits:
                if not hit:
                    continue
                if kind == "wave" and hit["rr"] <= 0:       # the stop-order fill (a gap) is already past the target
                    print(f"setups {s} {tf}: wave-3 skipped, target {px(hit['tp'][0])} not beyond the entry "
                          f"{px(hit['entry'])} (R:R {hit['rr']:.2f})")
                    continue
                rec = new_setup(s, tf, hit)
                if rec["id"] in known:
                    continue
                rec["against"] = flt["allowed"] != "both" and hit["side"] != flt["allowed"]
                busy.add((s, tf, kind))
                if hit.get("same_bar_stop"):            # the entry candle also hit the stop (wave_test rule): stopped
                    c = bars[-1]
                    rec.update(status="stop", exit=rec["stop"], exit_time=rec["time"], checked_ms=c["ct"] + 1)
                    rec["r"] = round(setup_r(rec), 3)
                    book["setups"].append(rec)
                    print(f"setups {rec['id']}: entry and stop in the same candle, closed at the stop (not pushed)")
                    continue
                against += rec["against"]
                book["setups"].append(rec)
                found.append((rec, bars))
    if against:
        print(f"setups: {against} against the market ({flt['market']}: {'longs' if flt['allowed'] == 'short' else 'shorts'}"
              f" labelled)")
    picked, more = pick_setup_pushes(book, found, now_ms) if SETUP_PUSH else ([], 0)
    for k, (rec, bars) in enumerate(picked):
        title, text = setup_text(rec)
        if more and k == len(picked) - 1:
            text += f"\nещё {more} сигнал{'ов' if more % 10 in (0, 5, 6, 7, 8, 9) or 11 <= more % 100 <= 14 else 'а' if more % 10 in (2, 3, 4) else ''} в приложении"
        if not push:
            print(f"(dry run) would push: {title}\n" + "\n".join("    " + x for x in text.splitlines()))
            continue
        try:
            png = setup_card(rec, bars) if bars else None   # friend: text only
        except Exception as e:
            print(f"setup card {rec['id']}: not drawn ({type(e).__name__}: {e}); text push only")
            png = None
        ntfy_card(title, text, png, f"setup_{rec['tf']}_{rec['symbol']}.png")
        rec["pushed_ms"] = now_ms
    waves = sum(setup_type(r) == "wave" for r, _ in found)
    print(f"setups: {len(found)} new ({waves} wave-3), {len(picked) if SETUP_PUSH else 'pushes off, 0'} pushed{f' (+{more} only in the app)' if more else ''}, "
          f"{sum(r['status'] == 'open' for r in book['setups'])} open, {len(book['setups'])} in total")
    return [r for r, _ in found], vol24


FRIEND_STATUS = {"pending": "pending", "open": "open", "cancelled": "cancelled", "gap": "gap"}


def friend_apply(rec, o):
    """Write confluence_test.order_outcome() into a "friend" record."""
    st = o["state"]
    if st == "closed":
        rec["status"] = o["why"]
    else:
        rec["status"] = FRIEND_STATUS[st]
    if "entry" in o:
        rec["entry"], rec["fill_time"] = sig(o["entry"]), _zt(o["fill_ms"])
    if "tp1" in o:
        rec["tp"] = [sig(o["tp1"]), sig(o["tp2"])]
        rec["expires"] = _zt(o["fill_ms"] + FRIEND_HOLD_MS)
        risk = abs(o["entry"] - rec["stop"])
        qty = SETUP_RISK_USD / risk
        rec["notional"], rec["margin"] = round(qty * o["entry"], 2), round(qty * o["entry"] / LEVERAGE, 2)
    rec["tp1_hit"] = bool(o.get("tp1_hit")) or rec["status"] in ("tp2", "tp1_be", "tp1_time")
    if st == "closed":
        rec.update(exit=sig(o["exit_px"]), exit_time=_zt(o["exit_ms"]), r=round(o["r"], 3), r_gross=round(o["gross"], 3))
    if "busy_ms" in o:
        rec["busy_ms"] = o["busy_ms"]


_zt = lambda t: datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
FRIEND_HOLD_MS = 48 * 3_600_000                     # set from the config variant in run_friend


def run_friend(now_ms, book, fetch=None, log=print):
    """Third intraday type "friend": confluence_test.py variant v4 (config live_friend: its coins, shorts only),
    run by friend_mode() (--friend, every 15 minutes). Follows every pending order / open trade with live_track(), then scans the
    15m candles closed since the last run with live_scan() (the same run_coin / order_outcome / simulate code as
    the backtest). Records: "type": "friend", status pending (limit order on the line) / open / stop / tp2 /
    tp1_be / time / tp1_time / cancelled (not filled in time) / gap (filled beyond the stop).
    Returns the push events [(record, kind)]: new / filled / tp1 / stop / tp1_be / tp2 / time / tp1_time /
    cancelled / gap."""
    global FRIEND_HOLD_MS
    import confluence_test as CF
    lf = CF.CFG["live_friend"]
    CF.set_variant(lf["variant"])
    FRIEND_HOLD_MS = CF.VC["max_hold_h"] * 3_600_000
    checked = book.setdefault("friend_checked", {})
    new, done, events = 0, 0, []
    for sym in lf["symbols"]:
        try:
            data = CF.live_candles(sym, now_ms, fetch)
        except Exception as e:
            log(f"friend {sym}: candles failed ({type(e).__name__}: {e})")
            continue
        mine = [r for r in book["setups"] if setup_type(r) == "friend" and r["symbol"] == sym]
        for rec in mine:
            if rec["status"] in ("pending", "open"):
                o = CF.live_track(rec, data)
                if o is None:
                    log(f"friend {rec['id']}: break candle not in the candles, kept")
                    continue
                before, tp0 = rec["status"], rec.get("tp1_hit", False)
                friend_apply(rec, o)
                events += [(rec, k) for k in friend_events(before, tp0, rec)]
                if rec["status"] != before:
                    done += 1
                    log(f"friend {rec['id']}: {before} -> {rec['status']}" + (f" ({rec['r']:+.2f}R)" if rec.get("r") is not None else ""))
        busy = max([float("inf") if r["status"] in ("pending", "open") else r.get("busy_ms", 0) for r in mine] or [0])
        t_from = checked.get(sym, now_ms - 3_600_000)
        rows, last = CF.live_scan(sym, data, t_from, busy)
        checked[sym] = max(t_from, last)
        known = {r["id"] for r in book["setups"]}
        for row in rows:
            if row["status"] == "rejected" and row["reason"] != f"limit not filled within {CF.VC['limit_bars']} candles" \
                    and not row["reason"].startswith("filled beyond"):
                continue                            # confirmations / risk / coin busy: not an order
            rid = f"friend:15m:{sym}:{row['k_t']}"
            if rid in known:
                continue
            t = row["t_ms"]
            rec = {"id": rid, "type": "friend", "symbol": sym, "coin": coin_of(sym), "name": hh_name(sym), "tf": "15m",
                   "side": row["side"], "time": _zt(t), "close_ms": t, "status": "pending", "stop": sig(row["stop_px"]),
                   "stop_x": row["stop_px"],
                   "entry": sig(float(row["entry"])), "line": row["line"], "k_t": row["k_t"], "conf": row["conf"],
                   "factors": {k: row[k] for k in ("E", "F", "G", "H")}, "struct": row["struct"],
                   "expires": _zt(row["k_t"] + (CF.VC["limit_bars"] + 1) * 15 * 60_000), "tp1_hit": False}
            plan_risk = abs(rec["entry"] - rec["stop"])
            rec["tp"] = [sig(rec["entry"] - CF.CFG["trade"]["tp1_r"] * plan_risk), sig(rec["entry"] - CF.CFG["trade"]["tp2_r"] * plan_risk)]
            o = CF.live_track(rec, data)                # the candles after the break that are already closed
            if o is not None:
                friend_apply(rec, o)
            book["setups"].append(rec)
            new += 1
            if rec["status"] == "pending":
                events.append((rec, "new"))
            else:                                   # found late (an outage): the order's time has passed, no push
                log(f"friend {rid}: found after its order was {rec['status']}, not pushed")
            log(f"friend {rid}: new short, {rec['status']} (line {rec['entry']}, stop {rec['stop']}, {rec['conf']} confirmations)")
    log(f"friend: {new} new, {done} resolved, {sum(setup_type(r) == 'friend' and r['status'] in ('pending', 'open') for r in book['setups'])} pending / open")
    return events


def friend_events(st0, tp0, rec):
    """Push kinds for a tracked friend record that went from (status st0, tp1_hit tp0) to its current state."""
    st, out = rec["status"], []
    if st == st0 and rec.get("tp1_hit") == tp0:
        return out
    if st0 == "pending":
        if st in ("cancelled", "gap"):
            return [st]
        if st != "pending":
            out.append("filled")
    if rec.get("tp1_hit") and not tp0:
        out.append("tp1")
    if st in ("stop", "tp1_be", "tp2", "time", "tp1_time"):
        out.append(st)
    return out


FRIEND_FAST = True                # --friend every 15 minutes: the friend's setup pushed right after the break (user, 21.11.2026)
FRIEND_FILE = "friend.json"       # friend records + friend_checked; written only by --friend (no clash with the hourly run)
FRIEND_PUSH = "🧪 Тренировка · 🤝 Сетап друга"


def load_friend():
    try:
        with open(FRIEND_FILE) as fh:
            d = json.load(fh)
        if isinstance(d.get("setups"), list):
            return d
    except (OSError, ValueError, AttributeError):
        pass
    return {"setups": [], "friend_checked": {}}


def save_friend(book):
    tmp = FRIEND_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)
    os.replace(tmp, FRIEND_FILE)


def friend_push(rec, kind):
    """(title, text) of a friend push: the order right after the break, then one short push per event."""
    coin, hm = rec["coin"], lambda t: datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%H:%M")
    if kind == "new":
        t1, x1, t2, x2 = rec["line"]
        step = 15 * 60_000
        slope = (x2 - x1) / ((t2 - t1) / step)          # per 15m candle
        k1_end = rec["close_ms"] + step                 # the candle after the break: the order's first candle
        risk = rec["stop"] - rec["entry"]
        size = SETUP_PUSH_RISK_USD / risk * rec["entry"]
        expiry = rec["close_ms"] + 12 * step
        return (f"{FRIEND_PUSH} · SHORT {coin}",
                f"Поставь лимитную заявку на продажу: {px(rec['entry'])} (до {hm(k1_end)} UTC; линия сдвигается на "
                f"{'+' if slope >= 0 else '−'}{px(abs(slope))} за 15 мин, переставляй заявку)\n"
                f"Стоп: {px(rec['stop'])}\n"
                f"Цель 1: {px(rec['tp'][0])} → закрыть половину, стоп в безубыток\n"
                f"Цель 2: {px(rec['tp'][1])}\n"
                f"Риск ${SETUP_PUSH_RISK_USD:g} · позиция {size:,.0f} USDT\n"
                f"Заявка действует до {hm(expiry)} UTC (12 свечей 15m)\n"
                f"Наблюдение, не рекомендация")
    short = {"filled": (f"Заявка {coin} исполнилась", f"Заявка {coin} исполнилась по {px(rec['entry'])}, стоп и цели как в сигнале: стоп {px(rec['stop'])}, "
                                                    f"цель 1 {px(rec['tp'][0])}, цель 2 {px(rec['tp'][1])} (цели от цены исполнения)."),
             "cancelled": (f"Отмени заявку {coin}", f"Отмени заявку {coin}: за 12 свечей 15m цена не дошла до линии."),
             "gap": (f"{coin}: заявка за стопом", f"Заявка {coin} исполнилась уже за стопом: закрой позицию."),
             "tp1": (f"{coin}: цель 1", f"{coin}: цель 1 {px(rec['tp'][0])} взята → закрой половину, стоп в безубыток {px(rec['entry'])}."),
             "tp2": (f"{coin}: цель 2", f"{coin}: цель 2 {px(rec['tp'][1])} взята, сделка закрыта."),
             "stop": (f"{coin}: стоп", f"{coin}: стоп {px(rec['stop'])}, сделка закрыта."),
             "tp1_be": (f"{coin}: безубыток", f"{coin}: остаток закрыт в безубытке {px(rec['entry'])}."),
             "time": (f"{coin}: 48 часов", f"{coin}: прошло 48 часов, закрой позицию по рынку."),
             "tp1_time": (f"{coin}: 48 часов", f"{coin}: прошло 48 часов, закрой остаток по рынку.")}[kind]
    return f"{FRIEND_PUSH} · {short[0]}", short[1] + ("" if kind in ("cancelled",) else "\nНаблюдение, не рекомендация")


def friend_mode(now_ms=None, fetch=None, log=print):
    """--friend (every 15 minutes, a minute after each 15m close): the friend's setup alone, on its 30 coins.
    Pushes a new order right after its break candle and every event after it; saves friend.json (not in a
    dry run). FRIEND_FAST = False: does nothing. Returns the events."""
    if not FRIEND_FAST:
        print("friend: FRIEND_FAST is off, nothing to do")
        return []
    now_ms = now_ms or int(time.time() * 1000)
    book = load_friend()
    events = run_friend(now_ms, book, fetch, log)
    for rec, kind in events:
        title, text = friend_push(rec, kind)
        ntfy(title, text)
    if not DRY_RUN:
        save_friend(book)
    print(f"friend {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {len(events)} push(es)")
    return events


def pick_setup_pushes(book, found, now_ms):
    """([(setup, bars)] to push, how many more pushable setups were left out): only SETUP_PUSH_TFS, no symbol pushed
    within SETUP_PUSH_GAP_MS (12 hours), at most SETUP_PUSH_MAX per run, the highest relative volume first."""
    recent = {r["symbol"] for r in book["setups"] if now_ms - r.get("pushed_ms", 0) < SETUP_PUSH_GAP_MS}
    ok = sorted([(r, b) for r, b in found if (r["tf"] in SETUP_PUSH_TFS or setup_type(r) == "friend")
                 and r["symbol"] not in recent], key=lambda x: -x[0].get("vol_x", 0))
    picked, seen = [], set()
    for r, b in ok:                                 # one push per symbol per run as well
        if r["symbol"] not in seen:
            picked.append((r, b))
            seen.add(r["symbol"])
    return picked[:SETUP_PUSH_MAX], max(0, len(picked) - SETUP_PUSH_MAX)


def setups_export(book, now_ms=None):
    """The web app's "setups": open ones, the last 300 closed (newest first), the live stats since SETUP_LIVE_SINCE
    and over the last 7 days (public, no secrets)."""
    keys = ("id", "symbol", "coin", "tf", "side", "time", "expires", "entry", "stop", "tp", "status", "tp1_hit",
            "tp1_time", "exit", "exit_time", "r", "last", "vol_x", "notional", "margin", "against", "type", "ret", "rr")
    recs = [r for r in book["setups"] if setup_type(r) != "friend"] + load_friend()["setups"]   # friend: friend.json
    rows = [dict({k: r.get(k) for k in keys}, type=setup_type(r)) for r in recs
            if not (setup_type(r) == "friend" and r["status"] in ("cancelled", "gap"))]   # unfilled orders: not shown
    closed = [r for r in rows if r["status"] not in ("open", "pending")]
    live = [r for r in book["setups"] if r["time"][:10] >= SETUP_LIVE_SINCE and setup_type(r) != "friend"]
    friend = [r for r in recs if setup_type(r) == "friend" and r["status"] not in ("cancelled", "gap")]
    week = datetime.fromtimestamp(((now_ms or int(time.time() * 1000)) - 7 * DAY_MS) / 1000,
                                  tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return {"open": [r for r in rows if r["status"] in ("open", "pending")], "closed": closed[::-1][:300],
            "stats": setup_stats(live), "stats_friend": setup_stats(friend), "stats_7d": setup_stats([r for r in live if r["time"] >= week]),
            "live_since": SETUP_LIVE_SINCE, "dry_run": SETUP_DRY_RUN, "filter": {"market": market_state(now_ms)},
            "rules": {"tp_r": list(SETUP_TP_R), "fee_rt": SETUP_FEE_RT, "exit_hours": SETUP_EXIT_MS // 3_600_000,
                      "risk_usd": SETUP_RISK_USD, "push_risk_usd": SETUP_PUSH_RISK_USD}}


def watch_mode():
    """Intraday alerts (TP1 / TP2 / stop touched by the hourly candles for open A and B positions, flat symbols
    within NEAR_PCT of their breakout). Reads state.json, never writes it; remembers sent alerts in alerts.json."""
    now_ms = int(time.time() * 1000)
    today = day_str(now_ms)
    with open(STATE) as fh:
        state = json.load(fh)
    alerts = load_alerts()
    hourly = lambda s, start: fetch_candles(s, start, now_ms, "1h")
    daily_cache = {}

    def daily(s):
        bars, live = download(s, now_ms)
        daily_cache[s] = bars
        return bars, live
    found = watch_alerts(state, now_ms, alerts, hourly, daily)
    book, vol24 = load_setups(), {}
    try:                                                # labelled 1H / 4H setups: never touch strategy B
        _, vol24 = run_setups(now_ms, book, push=not DRY_RUN)
        if not DRY_RUN:
            save_setups(book)
    except Exception as e:
        print(f"setups: failed ({type(e).__name__}: {e})")
    try_export(state, read_journal(), now_ms, daily_cache, setups=book, vol24=vol24)
    try_news(now_ms)
    for (pid, kind), title, text in found:
        if ntfy(title, text) is None:                   # not sent: try again next time
            if pid == "near":
                alerts["near"][kind] = today
            else:
                alerts["positions"].setdefault(pid, []).append(kind)
    open_ids = {f"{v}:{s}:{st[key]['entry_date']}" for s, st in state["symbols"].items()
                for v, key in POS_KEY.items() if st.get(key)}
    alerts["positions"] = {k: v for k, v in alerts["positions"].items() if k in open_ids}   # closed: forget
    alerts["near"] = {c: d for c, d in alerts["near"].items() if d == today}
    print(f"watch {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {len(found)} alert(s)"
          + ("" if found else ", nothing to report (no push)"))
    if DRY_RUN:
        print("(dry run: alerts.json not written, nothing pushed)")
        return
    os.makedirs(PAPER_DIR, exist_ok=True)
    tmp = ALERTS + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(alerts, fh, indent=1, sort_keys=True)
    os.replace(tmp, ALERTS)


def main():
    global DRY_RUN
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notify", action="store_true", help="send the report to Telegram even if no new day")
    parser.add_argument("--demo", action="store_true", help="print and push one sample BUY for BTCUSDT; changes nothing")
    parser.add_argument("--export", action="store_true", help="only write site/data.json for the web app")
    parser.add_argument("--weekly-demo", action="store_true", help="push one sample weekly report card; changes nothing")
    parser.add_argument("--watch", action="store_true", help="intraday alerts only (TP / stop touched, near breakout); "
                                                             "never writes state.json")
    parser.add_argument("--demo-en", action="store_true", help="push one English EXAMPLE BUY card for BTCUSDT; changes nothing")
    parser.add_argument("--friend", action="store_true", help="the friend's setup only (every 15 minutes): pushes orders "
                                                              "right after the break; writes friend.json")
    parser.add_argument("--dry-run", action="store_true", help="run everything, save nothing, send no push")
    parser.add_argument("--watchdog", metavar="OUTCOME", help="only the watchdog check; OUTCOME = result of the paper.py step")
    args = parser.parse_args()
    DRY_RUN = args.dry_run              # with --demo / --demo-en: print and save the card instead of pushing
    if args.demo:
        return demo()
    if args.demo_en:
        return demo_en()
    if args.watch:
        return watch_mode()
    if args.friend:
        return friend_mode()
    if args.weekly_demo:
        return weekly_demo(int(time.time() * 1000))
    if args.export:
        with open(STATE) as fh:
            export_site(json.load(fh), read_journal(), int(time.time() * 1000))
        return build_news(int(time.time() * 1000))
    if args.watchdog:
        return watchdog(args.watchdog)

    os.makedirs(PAPER_DIR, exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)   # two runs at once wait for each other instead of racing
        run(args)


def behind(state, day):
    """Symbols that have not processed `day` yet (a symbol not tracked yet counts)."""
    tracked = list(PAPER_SYMBOLS) + [s for s in RETIRED if s in state["symbols"]]
    return [s for s in tracked if state["symbols"].get(s, {}).get("last_processed", "") < day]


def watchdog(outcome):
    """Push a warning if the latest closed day is not processed or its summary push failed; at most once a day."""
    now_ms = int(time.time() * 1000)
    if (now_ms // 3_600_000) % 24 < WATCHDOG_HOUR:
        print(f"Watchdog: before {WATCHDOG_HOUR:02d}:00 UTC, not checking yet")
        return
    day = prev_day(day_str(now_ms))
    state = json.load(open(STATE))
    if state.get("watchdog_sent") == day:
        print(f"Watchdog: warning for {day} already sent")
        return
    late, rec = behind(state, day), state.get("summary_push") or {}
    if late:
        reason = (f"День {day} не обработан: {len(late)} симв. ({', '.join(late[:5])}{'…' if len(late) > 5 else ''})."
                  + (f" Шаг paper.py: {outcome}." if outcome != "success" else ""))
    elif rec.get("day") != day:
        reason = f"День {day} обработан, но нет записи об отправке сводки."
    elif rec.get("error"):
        reason = f"День {day} обработан, но сводка не отправлена: {rec['error']}"
    else:
        print(f"Watchdog: OK, {day} processed and its summary was pushed")
        return
    print(f"Watchdog: {reason}")
    if ntfy(WATCHDOG_TITLE, reason) is None and not DRY_RUN:
        state["watchdog_sent"] = day
        save_state(state)


def run(args):
    now_ms = int(time.time() * 1000)
    today = day_str(now_ms)
    if not sys.stdout.isatty():   # launchd / Actions logs: mark where each run starts
        print(f"\n===== run {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC{' (dry run)' if DRY_RUN else ''} =====")
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    state.setdefault("strategy", "trend_breakout")
    state.setdefault("lookback", LOOKBACK)
    state.setdefault("start_date", today)
    state.setdefault("slippage", SLIPPAGE)
    state.setdefault("symbols", {})
    if state.get("fee") != HH_FEE:
        state["fee"] = HH_FEE        # HashHedge taker fee from 2026-11-08 (no trade had closed before)
        state["funding"] = "real Binance USDT-M funding, added to open positions every run"
    if state["lookback"] != LOOKBACK:
        raise SystemExit(f"state.json was made with lookback {state['lookback']}, not {LOOKBACK}")
    changed = setup_challenges(state, today) or not os.path.exists(STATE)
    latest_closed = prev_day(today)
    if not changed and not behind(state, latest_closed):
        if not DRY_RUN and not args.notify:
            print(f"Latest closed day {latest_closed} already processed: nothing to do")
            return
        if DRY_RUN:
            print(f"(dry run: {latest_closed} already processed, a real run would exit here)")
    b_since = state["b_since"]

    new_events, processed, prices, closes, bars_of = [], [], {}, {}, {}
    for s in list(PAPER_SYMBOLS) + [s for s in RETIRED if s in state["symbols"]]:
        if s in RETIRED and not state["symbols"][s].get("position") and not state["symbols"][s].get("position_b"):
            del state["symbols"][s]                # retired and flat: stop tracking
            print(f"{s}: retired (not on HashHedge), no open position; no longer tracked")
            changed = True
            continue
        # A new symbol starts flat on today's UTC day (no backfill): its first processable day is today
        if s not in state["symbols"]:
            state["symbols"][s] = {"since": today, "position": None, "position_b": None,
                                   "last_processed": (datetime.strptime(today, "%Y-%m-%d")
                                                      - timedelta(days=1)).strftime("%Y-%m-%d")}
            changed = True
        st = state["symbols"][s]
        st.setdefault("position_b", None)
        try:
            bars, prices[s] = download(s, now_ms)
        except Exception as e:
            print(f"{s}: download failed ({e}); skipped this run, nothing changed")
            continue
        closes[s] = {b["time"]: b["close"] for b in bars}
        bars_of[s] = bars
        if bars[0]["time"] > next_day(st["last_processed"]):
            print(f"{s}: last processed {st['last_processed']} is older than the downloaded history; skipped")
            continue
        price_at = lambda t, s=s: closes[s].get(prev_day(day_str(t)), prices[s])   # the day's open
        fund = lambda pos, until, s=s, price_at=price_at: accrue_funding(s, pos, until, now_ms, price_at)
        pos = {v: st[key] for v, key in POS_KEY.items()}
        for t, bar in enumerate(bars):
            if bar["time"] <= st["last_processed"]:
                continue           # never process a day twice
            if s in RETIRED and not pos["A"] and not pos["B"]:
                break              # retired: no new entries after its last position closed
            for v in POS_KEY:
                before = pos[v]
                may_enter = s not in RETIRED and (v == "A" or bar["time"] >= b_since)
                pos[v], events = process_day(s, pos[v], bars, t, fund, v, may_enter)
                if before and not pos[v] and before.get("funding_est"):   # closed with estimated funding
                    state.setdefault("funding_pending", []).append(
                        {"symbol": s, "variant": v, "entry_date": before["entry_date"], "close_date": bar["time"],
                         "risk": before["risk"], "windows": before["funding_est"]})
                new_events += events
            st["last_processed"] = bar["time"]
            processed.append((s, bar["time"]))
        for v, key in POS_KEY.items():
            if pos[v]:
                before = pos[v].get("funding_through_ms")
                fund(pos[v], now_ms + 1)           # funding paid since the last run, up to now
                changed = changed or pos[v].get("funding_through_ms") != before
            st[key] = pos[v]
        st["last_close"] = bars[-1]["close"]
        st["watch"] = watch(bars)
        if s in RETIRED and not pos["A"] and not pos["B"]:
            del state["symbols"][s]
            print(f"{s}: retired (not on HashHedge), position closed; no longer tracked")

    if (processed or not os.path.exists(JOURNAL)) and not DRY_RUN:
        append_journal(new_events)   # also creates the journal (header only) on the first run
    journal = journal_with(new_events)
    rows_changed, note = correct_funding(state, journal)
    if note:
        state.setdefault("funding_notes", []).append(f"{today}: {note}")
        changed = True
    if rows_changed and not DRY_RUN:
        write_journal(journal)
    alerts = []
    for key, name in CHALLENGES:
        alerts += run_challenge(state, key, name, closes, journal)
    if processed:
        state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    text = report(state, prices, new_events, processed)
    print(text)
    if processed or args.notify:
        telegram(text)
    if processed or DRY_RUN:
        ntfy_events(state, prices, new_events, journal, bars_of)   # after the challenges: a BUY needs challenge B's decision
        title, text_ = summary_text(state, prices, new_events, processed)
        day = max(d for _, d in processed) if processed else max(st["last_processed"] for st in state["symbols"].values())
        png = try_dashboard(state, prices, day, now_ms)
        error = ntfy_card(title, summary_line(state, prices, new_events), png, f"summary_{day}.png", fallback=text_)
        if processed:
            state["summary_push"] = {"day": max(d for _, d in processed), "error": error}   # read by the watchdog
        if state.get("funding_notes"):
            state["funding_notes"] = []              # pushed with this summary
        saturdays = sorted(d for _, d in processed if datetime.strptime(d, "%Y-%m-%d").weekday() == 5)
        if saturdays and state.get("weekly_sent") != saturdays[-1]:      # the Sunday run closes Saturday
            if send_weekly(state, prices, journal, saturdays[-1], now_ms) is None and not DRY_RUN:
                state["weekly_sent"] = saturdays[-1]
    for title, text_ in alerts:
        print(f"ALERT {title}: {text_}")
        ntfy(title, text_)
    if (processed or changed) and not DRY_RUN:
        save_state(state)
    if processed or DRY_RUN:
        try_export(state, journal, now_ms, bars_of)
        try_news(now_ms)
    if DRY_RUN:
        print("\n(dry run: state.json and journal.csv not written, nothing pushed)")


if __name__ == "__main__":
    main()
