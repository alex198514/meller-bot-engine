"""Symbol-aware file names and price formatting shared by all scripts.

BTCUSDT keeps the original file names (data/btc_1h.csv, data/waves.json, ...) so the HTML pages
keep working. Other symbols get their own files: ETHUSDT -> data/eth_1h.csv, data/waves_eth.json, ...
"""

import os

DEFAULT_SYMBOL = "BTCUSDT"


def base(symbol):
    """'ETHUSDT' -> 'eth'."""
    s = symbol.upper()
    return (s[:-4] if s.endswith("USDT") else s).lower()


def candles_path(symbol, years3=False):
    """Hourly candles: data/btc_1h.csv (90 days, live tools) or data/btc_1h_3y.csv (backtest)."""
    return os.path.join("data", f"{base(symbol)}_1h{'_3y' if years3 else ''}.csv")


def data_path(name, ext, symbol, tag=None):
    """Output file for a symbol: data/<name>[_<base>][_<tag>].<ext>; BTCUSDT has no symbol suffix."""
    parts = [name]
    if symbol.upper() != DEFAULT_SYMBOL:
        parts.append(base(symbol))
    if tag:
        parts.append(tag)
    return os.path.join("data", "_".join(parts) + "." + ext)


def price_round(p):
    """Keep enough decimals for cheap coins (XRP ~$0.5) while BTC stays at cents."""
    if p is None:
        return None
    return round(p, 2) if abs(p) >= 100 else round(p, 6)


def usd(p):
    if abs(p) >= 100:
        return f"${p:,.2f}"
    return f"${p:,.4f}" if abs(p) >= 1 else f"${p:,.6f}"
