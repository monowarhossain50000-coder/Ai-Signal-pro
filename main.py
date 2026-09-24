import os
import time
import requests

from datetime import datetime, timezone
from threading import Lock

from flask import Flask, render_template, jsonify, request


app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")

CACHE_SECONDS = 5
API_MIN_GAP = 12

market_cache = {}
last_api_request = 0

cache_lock = Lock()


# =========================================================
# PAIRS
# =========================================================

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD",
    "EUR/CAD", "EUR/NZD", "EUR/SGD",
    "GBP/JPY", "GBP/CHF", "GBP/AUD",
    "GBP/CAD", "GBP/NZD",
    "AUD/JPY", "AUD/CHF", "AUD/CAD",
    "AUD/NZD", "CAD/JPY", "CAD/CHF",
    "CHF/JPY", "NZD/JPY", "NZD/CAD",
    "NZD/CHF", "USD/SGD", "USD/HKD",
    "USD/SEK", "USD/NOK", "USD/DKK",
    "USD/ZAR", "USD/TRY"
]


OTC_PAIRS = [
    "EUR/USD OTC", "GBP/USD OTC", "USD/JPY OTC",
    "USD/CHF OTC", "AUD/USD OTC", "USD/CAD OTC",
    "NZD/USD OTC", "EUR/GBP OTC", "EUR/JPY OTC",
    "EUR/CHF OTC", "EUR/AUD OTC", "EUR/CAD OTC",
    "EUR/NZD OTC", "EUR/SGD OTC",
    "GBP/JPY OTC", "GBP/CHF OTC", "GBP/AUD OTC",
    "GBP/CAD OTC", "GBP/NZD OTC",
    "AUD/JPY OTC", "AUD/CHF OTC", "AUD/CAD OTC",
    "AUD/NZD OTC", "CAD/JPY OTC", "CAD/CHF",
    "CHF/JPY OTC", "NZD/JPY OTC", "NZD/CAD OTC",
    "NZD/CHF OTC",
    "USD/BDT OTC", "USD/INR OTC", "USD/PKR OTC",
    "USD/MXN OTC", "USD/COP OTC", "USD/EGP OTC",
    "USD/IDR OTC", "USD/NGN OTC", "USD/PHP OTC",
    "USD/ZAR OTC", "USD/TRY OTC", "USD/ARS OTC",
    "USD/DZD OTC", "USD/BRL OTC",
    "XAU/USD OTC", "XAG/USD OTC",
    "US Crude OTC", "UK Brent OTC",
    "BTC/USD OTC", "ETH/USD OTC", "BCH/USD OTC",
    "BNB/USD OTC", "XRP/USD OTC", "LTC/USD OTC",
    "ADA/USD OTC", "DOT/USD OTC", "DOGE/USD OTC",
    "SOL/USD OTC", "TON/USD OTC", "ETC/USD OTC",
    "ZEC/USD OTC", "TRX/USD OTC", "AXS/USD OTC",
    "AVAX/USD OTC", "APT/USD OTC", "ARB/USD OTC",
    "Microsoft OTC", "Intel OTC",
    "Johnson & Johnson OTC", "McDonald's OTC",
    "Pfizer OTC", "Boeing OTC",
    "American Express OTC", "Facebook OTC"
]


# =========================================================
# TIMEFRAMES
# =========================================================

TIMEFRAMES = {
    "1": 1,
    "2": 2,
    "3": 3,
    "5": 5,
    "10": 10,
    "15": 15,
    "30": 30,
    "60": 60,
    "240": 240
}


# =========================================================
# MARKET STATUS
# =========================================================

def forex_weekend_closed():

    now = datetime.now(timezone.utc)

    # Saturday
    if now.weekday() == 5:
        return True

    # Sunday before 21:00 UTC
    if now.weekday() == 6 and now.hour < 21:
        return True

    # Friday from 21:00 UTC
    if now.weekday() == 4 and now.hour >= 21:
        return True

    return False


# =========================================================
# DATETIME PARSER
# =========================================================

def parse_market_datetime(value):

    if not value:
        return None

    text = str(value).strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M"
    ]

    for fmt in formats:

        try:

            dt = datetime.strptime(
                text,
                fmt
            )

            return dt.replace(
                tzinfo=timezone.utc
            )

        except ValueError:
            continue

    return None


# =========================================================
# CHECK LIVE DATA
# =========================================================

def is_recent_market_data(candle, timeframe):

    if not candle:
        return False, "No candle data."

    candle_time = parse_market_datetime(
        candle.get("datetime")
    )

    if candle_time is None:

        return False, "Candle time unavailable."

    now = datetime.now(timezone.utc)

    age_seconds = (
        now - candle_time
    ).total_seconds()

    # Allow a small delay from data provider.
    allowed_delay = max(
        180,
        TIMEFRAMES[timeframe] * 60 * 2
    )

    if age_seconds < -60:

        return False, "Invalid future candle."

    if age_seconds > allowed_delay:

        return False, (
            "Live market candle is too old."
        )

    return True, None


# =========================================================
# EMA
# =========================================================

def calculate_ema(prices, period):

    if len(prices) < period:
        return None

    ema = sum(
        prices[:period]
    ) / period

    multiplier = 2 / (
        period + 1
    )

    for price in prices[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(
    prices,
    period=14
):

    if len(prices) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(prices)
    ):

        change = (
            prices[i]
            - prices[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# BOLLINGER BANDS
# =========================================================

def calculate_bollinger(
    prices,
    period=20,
    multiplier=2
):

    if len(prices) < period:
        return None

    values = prices[-period:]

    middle = (
        sum(values)
        / period
    )

    variance = sum(
        (x - middle) ** 2
        for x in values
    ) / period

    std = variance ** 0.5

    upper = (
        middle
        + multiplier * std
    )

    lower = (
        middle
        - multiplier * std
    )

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower
    }


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    candles,
    lookback=50
):

    if len(candles) < lookback:
        return None

    recent = candles[-lookback:]

    highs = [
        float(c["high"])
        for c in recent
    ]

    lows = [
        float(c["low"])
        for c in recent
    ]

    return {
        "resistance": max(highs),
        "support": min(lows)
    }


# =========================================================
# CANDLE INFO
# =========================================================

def candle_info(candle):

    o = float(
        candle["open"]
    )

    h = float(
        candle["high"]
    )

    l = float(
        candle["low"]
    )

    c = float(
        candle["close"]
    )

    candle_range = h - l

    body = abs(
        c - o
    )

    if candle_range > 0:

        body_ratio = (
            body
            / candle_range
        )

        close_position = (
            (c - l)
            / candle_range
        )

    else:

        body_ratio = 0
        close_position = 0.5

    if c > o:

        direction = "BULLISH"

    elif c < o:

        direction = "BEARISH"

    else:

        direction = "DOJI"

    return {

        "direction":
            direction,

        "body_ratio":
            body_ratio,

        "range":
            candle_range,

        "close_position":
            close_position
    }


# =========================================================
# MARKET DATA
# =========================================================

def get_market_candles(
    symbol,
    minutes
):

    global last_api_request

    cache_key = (
        symbol,
        minutes
    )

    now = time.time()

    with cache_lock:

        cached = market_cache.get(
            cache_key
        )

        if cached:

            age = (
                now
                - cached["time"]
            )

            if age < CACHE_SECONDS:

                return cached["data"]

    with cache_lock:

        now = time.time()

        elapsed = (
            now
            - last_api_request
        )

        if elapsed < API_MIN_GAP:

            cached = market_cache.get(
                cache_key
            )

            if cached:

                return cached["data"]

            time.sleep(
                API_MIN_GAP
                - elapsed
            )

        last_api_request = time.time()

    if minutes == 60:

        interval = "1h"

    elif minutes == 240:

        interval = "4h"

    else:

        interval = "1min"

    params = {

        "symbol":
            symbol,

        "interval":
            interval,

        "outputsize":
            250,

        "apikey":
            API_KEY
    }

    response = requests.get(

        "https://api.twelvedata.com/time_series",

        params=params,

        timeout=20
    )

    if response.status_code == 429:

        cached = market_cache.get(
            cache_key
        )

        if cached:

            return cached["data"]

        raise Exception(
            "Twelve Data rate limit reached."
        )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:

        raise Exception(
            data.get(
                "message",
                "Market data unavailable."
            )
        )

    raw = list(
        reversed(
            data["values"]
        )
    )

    candles = []

    if minutes in [
        1,
        60,
        240
    ]:

        for item in raw:

            candles.append({

                "datetime":
                    item.get(
                        "datetime"
                    ),

                "open":
                    float(
                        item["open"]
                    ),

                "high":
                    float(
                        item["high"]
                    ),

                "low":
                    float(
                        item["low"]
                    ),

                "close":
                    float(
                        item["close"]
                    )
            })

    else:

        for i in range(
            0,
            len(raw) - minutes
