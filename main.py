import os
import time
import math
import requests

from datetime import datetime, timezone
from threading import Lock

from flask import Flask, render_template, jsonify, request


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")

CACHE_SECONDS = 8
API_MIN_GAP = 12

market_cache = {}
quote_cache = {}

last_api_request = 0
last_quote_request = 0

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
    "AUD/NZD OTC", "CAD/JPY OTC", "CAD/CHF OTC",
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
# HELPERS
# =========================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(symbol):
    if not symbol:
        return "EUR/USD"

    symbol = str(symbol).strip()

    if symbol.upper().endswith(" OTC"):
        symbol = symbol[:-4].strip()

    return symbol


def is_otc_symbol(symbol):
    return str(symbol).strip().upper().endswith(" OTC")


def forex_weekend_closed():
    now = datetime.now(timezone.utc)

    if now.weekday() == 5:
        return True

    if now.weekday() == 6 and now.hour < 21:
        return True

    if now.weekday() == 4 and now.hour >= 21:
        return True

    return False


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
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


# =========================================================
# EMA
# =========================================================

def calculate_ema(prices, period):

    if len(prices) < period:
        return None

    ema = sum(prices[:period]) / period

    multiplier = 2 / (period + 1)

    for price in prices[period:]:
        ema = ((price - ema) * multiplier) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(prices, period=14):

    if len(prices) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(prices)):

        change = prices[i] - prices[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================================================
# BOLLINGER
# =========================================================

def calculate_bollinger(
    prices,
    period=20,
    multiplier=2
):

    if len(prices) < period:
        return None

    values = prices[-period:]

    middle = sum(values) / period

    variance = sum(
        (x - middle) ** 2
        for x in values
    ) / period

    std = math.sqrt(variance)

    upper = middle + multiplier * std
    lower = middle - multiplier * std

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "width": upper - lower
    }


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_sr(candles, lookback=80):

    if len(candles) < 10:
        return None

    recent = candles[-lookback:]

    highs = [
        safe_float(c["high"])
        for c in recent
    ]

    lows = [
        safe_float(c["low"])
        for c in recent
    ]

    resistance = max(highs)
    support = min(lows)

    return {
        "support": support,
        "resistance": resistance
    }


# =========================================================
# SWING SUPPORT / RESISTANCE
# =========================================================

def calculate_swing_levels(candles):

    if len(candles) < 15:
        return {
            "support": None,
            "resistance": None
        }

    recent = candles[-60:]

    swing_highs = []
    swing_lows = []

    for i in range(2, len(recent) - 2):

        h = safe_float(recent[i]["high"])
        l = safe_float(recent[i]["low"])

        left_h = safe_float(recent[i - 1]["high"])
        right_h = safe_float(recent[i + 1]["high"])

        left_l = safe_float(recent[i - 1]["low"])
        right_l = safe_float(recent[i + 1]["low"])

        if h >= left_h and h >= right_h:
            swing_highs.append(h)

        if l <= left_l and l <= right_l:
            swing_lows.append(l)

    return {
        "support": max(swing_lows[-5:]) if swing_lows else None,
        "resistance": min(swing_highs[-5:]) if swing_highs else None
    }


# =========================================================
# CANDLE ANALYSIS
# =========================================================

def analyze_candle(candle):

    o = safe_float(candle.get("open"))
    h = safe_float(candle.get("high"))
    l = safe_float(candle.get("low"))
    c = safe_float(candle.get("close"))

    candle_range = max(h - l, 0)

    body = abs(c - o)

    upper_wick = max(
        h - max(o, c),
        0
    )

    lower_wick = max(
        min(o, c) - l,
        0
    )

    if candle_range > 0:

        body_ratio = body / candle_range
        close_position = (c - l) / candle_range

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
        "direction": direction,
        "range": candle_range,
        "body": body,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "close_position": close_position
    }


# =========================================================
# RECENT CANDLE MOMENTUM
# =========================================================

def recent_momentum(candles, count=5):

    recent = candles[-count:]

    bullish = 0
    bearish = 0

    for candle in recent:

        o = safe_float(candle["open"])
        c = safe_float(candle["close"])

        if c > o:
            bullish += 1

        elif c < o:
            bearish += 1

    if bullish > bearish:
        return "BULLISH"

    if bearish > bullish:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# CANDLE PATTERN
# =========================================================

def candle_signal(info):

    bullish = 0
    bearish = 0
    reasons = []

    body_ratio = info["body_ratio"]
    close_position = info["close_position"]

    upper = info["upper_wick"]
    lower = info["lower_wick"]
    body = info["body"]

    # Strong bullish candle
    if (
        info["direction"] == "BULLISH"
        and body_ratio >= 0.60
        and close_position >= 0.70
    ):

        bullish += 8

        reasons.append(
            "Strong bullish candle"
        )

    # Strong bearish candle
    if (
        info["direction"] == "BEARISH"
        and body_ratio >= 0.60
        and close_position <= 0.30
    ):

        bearish += 8

        reasons.append(
            "Strong bearish candle"
        )

    # Lower wick rejection
    if (
        lower > body * 1.4
        and close_position >= 0.55
    ):

        bullish += 10

        reasons.append(
            "Lower-wick bullish rejection"
        )

    # Upper wick rejection
    if (
        upper > body * 1.4
        and close_position <= 0.45
    ):

        bearish += 10

        reasons.append(
            "Upper-wick bearish rejection"
        )

    # Doji warning
    if body_ratio < 0.20:

        reasons.append(
            "Small-body / indecision candle"
        )

    return bullish, bearish, reasons


# =========================================================
# DATA AGE
# =========================================================

def candle_age_seconds(candle):

    dt = parse_market_datetime(
        candle.get("datetime")
    )

    if dt is None:
        return None

    return max(
        0,
        (
            datetime.now(timezone.utc) - dt
        ).total_seconds()
    )


# =========================================================
# CURRENT 1-MINUTE CANDLE WINDOW
# =========================================================

def current_candle_window():

    now = datetime.now(timezone.utc)

    seconds = (
        now.minute * 60
        + now.second
        + now.microsecond / 1000000
    )

    elapsed = seconds % 60

    remaining = 60 - elapsed

    return {
        "elapsed_seconds": round(elapsed, 2),
        "remaining_seconds": round(
            remaining,
            2
        ),
        "first_30_seconds": elapsed < 30
    }


# =========================================================
# TWELVE DATA CANDLES
# =========================================================

def get_market_candles(symbol, minutes):

    global last_api_request

    symbol = clean_symbol(symbol)

    cache_key = (
        symbol,
        minutes
    )

    now = time.time()

    # CACHE
    with cache_lock:

        cached = market_cache.get(
            cache_key
        )

        if cached:

            if (
                now - cached["time"]
                < CACHE_SECONDS
            ):

                return cached["data"]

    # RATE LIMIT
    with cache_lock:

        now = time.time()

        elapsed = (
            now - last_api_request
        )

        if elapsed < API_MIN_GAP:

            cached = market_cache.get(
                cache_key
            )

            if cached:
                return cached["data"]

            time.sleep(
                API_MIN_GAP - elapsed
            )

        last_api_request = time.time()

    if not API_KEY:

        raise Exception(
            "TWELVEDATA_API_KEY is missing."
        )

    if minutes == 60:
        interval = "1h"

    elif minutes == 240:
        interval = "4h"

    else:
        interval = "1min"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": 250,
        "apikey": API_KEY
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

    # NATIVE
    if minutes in [1, 60, 240]:

        for item in raw:

            candles.append({

                "datetime":
                    item.get("datetime"),

                "open":
                    safe_float(
                        item.get("open")
                    ),

                "high":
                    safe_float(
                        item.get("high")
                    ),

                "low":
                    safe_float(
                        item.get("low")
                    ),

                "close":
                    safe_float(
                        item.get("close")
                    )
            })

    # AGGREGATION
    else:

        for i in range(
            0,
            len(raw) - minutes + 1,
            minutes
        ):

            group = raw[
                i:i + minutes
            ]

            if len(group) < minutes:
                continue

            candles.append({

                "datetime":
                    group[0].get(
                        "datetime"
                    ),

                "open":
                    safe_float(
                        group[0].get("open")
                    ),

                "high":
                    max(
                        safe_float(
                            x.get("high")
                        )
                        for x in group
                    ),

                "low":
                    min(
                        safe_float(
                            x.get("low")
                        )
                        for x in group
                    ),

                "close":
                    safe_float(
                        group[-1].get("close")
                    )
            })

    if len(candles) < 30:

        raise Exception(
            "Not enough candle data."
        )

    with cache_lock:

        market_cache[cache_key] = {
            "time": time.time(),
            "data": candles
        }

    return candles


# =========================================================
# LIVE QUOTE
# =========================================================

def get_live_quote(symbol):

    global last_quote_request

    symbol = clean_symbol(symbol)

    cache_key = (
        "quote",
        symbol
    )

    now = time.time()

    cached = quote_cache.get(
        cache_key
    )

    if cached:

        if now - cached["time"] < 8:
            return cached["price"]

    with cache_lock:

        now = time.time()

        elapsed = (
            now - last_quote_request
        )

        if elapsed < API_MIN_GAP:

            cached = quote_cache.get(
                cache_key
            )

            if cached:
                return cached["price"]

            return None

        last_quote_request = time.time()

    if not API_KEY:
        return None

    try:

        response = requests.get(
            "https://api.twelvedata.com/quote",
            params={
                "symbol": symbol,
                "apikey": API_KEY
            },
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()

        price = safe_float(
            data.get("close"),
            None
        )

        if price is None:
            return None

        quote_cache[cache_key] = {
            "time": time.time(),
            "price": price
        }

        return price

    except Exception:
        return None


# =========================================================
# PRICE DISTANCE
# =========================================================

def percentage_distance(price, level):

    if price is None or level is None:
        return None

    if level == 0:
        return None

    return abs(
        price - level
    ) / level * 100


# =========================================================
# MAIN SCANNER
# =========================================================

def analyze_market(symbol, timeframe):

    minutes = TIMEFRAMES.get(
        str(timeframe),
        1
    )

    original_symbol = symbol

    clean = clean_symbol(symbol)

    otc = is_otc_symbol(
        original_symbol
    )

    candles = get_market_candles(
        clean,
        minutes
    )

    if len(candles) < 30:
        raise Exception(
            "Insufficient candle data."
        )

    # -----------------------------------------------------
    # CLOSED CANDLE DATA
    # -----------------------------------------------------

    closes = [
        safe_float(c["close"])
        for c in candles
    ]

    current_candle = candles[-1]

    last_closed_price = safe_float(
        current_candle["close"]
    )

    # -----------------------------------------------------
    # LIVE PRICE
    # -----------------------------------------------------

    live_price = get_live_quote(
        clean
    )

    if live_price is None:
        live_price = last_closed_price

    # -----------------------------------------------------
    # INDICATORS
    # -----------------------------------------------------

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    rsi = calculate_rsi(
        closes,
        14
    )

    bb = calculate_bollinger(
        closes,
        20,
        2
    )

    sr = calculate_sr(
        candles,
        80
    )

    swings = calculate_swing_levels(
        candles
    )

    candle = analyze_candle(
        current_candle
    )

    momentum = recent_momentum(
        candles,
        5
    )

    # -----------------------------------------------------
    # LEVELS
    # -----------------------------------------------------

    support = sr["support"] if sr else None
    resistance = sr["resistance"] if sr else None

    swing_support = swings["support"]
    swing_resistance = swings["resistance"]

    # Prefer nearby swing levels
    if swing_support is not None:

        if (
            support is None
            or abs(live_price - swing_support)
            < abs(live_price - support)
        ):
            support = swing_support

    if swing_resistance is not None:

        if (
            resistance is None
            or abs(live_price - swing_resistance)
            < abs(live_price - resistance)
        ):
            resistance = swing_resistance

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    bullish = 0
    bearish = 0

    bull_reasons = []
    bear_reasons = []

    # -----------------------------------------------------
    # EMA TREND
    # -----------------------------------------------------

    if ema20 is not None:

        if live_price > ema20:

            bullish += 8

            bull_reasons.append(
                "Price above EMA20"
            )

        elif live_price < ema20:

            bearish += 8

            bear_reasons.append(
                "Price below EMA20"
            )

    if ema50 is not None:

        if live_price > ema50:

            bullish += 8

            bull_reasons.append(
                "Price above EMA50"
            )

        elif live_price < ema50:

            bearish += 8

            bear_reasons.append(
                "Price below EMA50"
            )

    if ema200 is not None:

        if live_price > ema200:

            bullish += 8

            bull_reasons.append(
                "Price above EMA200"
            )

        elif live_price < ema200:

            bearish += 8

            bear_reasons.append(
                "Price below EMA200"
            )

    # EMA alignment
    if (
        ema20 is not None
        and ema50 is not None
    ):

        if ema20 > ema50:

            bullish += 8

            bull_reasons.append(
                "EMA20 above EMA50"
            )

        elif ema20 < ema50:

            bearish += 8

            bear_reasons.append(
                "EMA20 below EMA50"
            )

    if (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
    ):

        if (
            ema20 > ema50
            and ema50 > ema200
        ):

            bullish += 10

            bull_reasons.append(
                "EMA bullish alignment"
            )

        elif (
            ema20 < ema50
            and ema50 < ema200
        ):

            bearish += 10

            bear_reasons.append(
                "EMA bearish alignment"
            )

    # -----------------------------------------------------
    # BOLLINGER BAND
    # -----------------------------------------------------

    bb_position = "UNKNOWN"

    if bb:

        upper = bb["upper"]
        middle = bb["middle"]
        lower = bb["lower"]

        if live_price <= lower:

            bb_position = "LOWER BAND"

            bullish += 12

            bull_reasons.append(
                "Price at/below lower Bollinger Band"
            )

        elif live_price >= upper:

            bb_position = "UPPER BAND"

            bearish += 12

            bear_reasons.append(
                "Price at/above upper Bollinger Band"
            )

        elif live_price > middle:

            bb_position = "ABOVE MIDDLE"

            bullish += 5

            bull_reasons.append(
                "Price above Bollinger middle"
            )

        elif live_price < middle:

            bb_position = "BELOW MIDDLE"

            bearish += 5

            bear_reasons.append(
                "Price below Bollinger middle"
            )

    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

    if support is not None:

        support_distance = (
            percentage_distance(
                live_price,
                support
            )
        )

        if (
            support_distance is not None
            and support_distance <= 0.15
        ):

            bullish += 15

            bull_reasons.append(
                "Price near support"
            )

    # -----------------------------------------------------
    # RESISTANCE
    # -----------------------------------------------------

    if resistance is not None:

        resistance_distance = (
            percentage_distance(
                live_price,
                resistance
            )
        )

        if (
            resistance_distance is not None
            and resistance_distance <= 0.15
        ):

            bearish += 15

            bear_reasons.append(
                "Price near resistance"
            )

    # -----------------------------------------------------
    # CANDLE PATTERN
    # -----------------------------------------------------

    candle_bull, candle_bear, candle_reasons = (
        candle_signal(candle)
    )

    bullish += candle_bull
    bearish += candle_bear

    for reason in candle_reasons:

        if "bullish" in reason.lower():
            bull_reasons.append(reason)

        elif "bearish" in reason.lower():
            bear_reasons.append(reason)

    # -----------------------------------------------------
    # MOMENTUM
    # -----------------------------------------------------

    if momentum == "BULLISH":

        bullish += 8

        bull_reasons.append(
            "Recent candle momentum bullish"
        )

    elif momentum == "BEARISH":

        bearish += 8

        bear_reasons.append(
            "Recent candle momentum bearish"
        )

    # -----------------------------------------------------
    # RSI — CONFIRMATION ONLY
    # -----------------------------------------------------

    if rsi is not None:

        if 52 <= rsi <= 68:

            bullish += 5

            bull_reasons.append(
                "RSI confirms bullish momentum"
            )

        elif 32 <= rsi <= 48:

            bearish += 5

            bear_reasons.append(
                "RSI confirms bearish momentum"
            )

        # Oversold reversal
        if rsi < 30:

            bullish += 4

            bull_reasons.append(
                "RSI oversold reversal zone"
            )

        # Overbought reversal
        if rsi > 70:

            bearish += 4

            bear_reasons.append(
                "RSI overbought reversal zone"
            )

    # -----------------------------------------------------
    # SCORE DIFFERENCE
    # -----------------------------------------------------

    total = bullish + bearish

    difference = abs(
        bullish - bearish
    )

    if total > 0:

        strength = round(
            difference / total * 100,
            1
        )

    else:

        strength = 0

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    if bullish > bearish:

        direction = "CALL / UP"

        dominant = bullish
        opposite = bearish

        selected_reasons = bull_reasons

    elif bearish > bullish:

        direction = "PUT / DOWN"

        dominant = bearish
        opposite = bullish

        selected_reasons = bear_reasons

    else:

        direction = "NO TRADE"

        dominant = 0
        opposite = 0

        selected_reasons = [
            "Bullish and bearish scores are balanced"
        ]

    # -----------------------------------------------------
    # CONFIDENCE
    # -----------------------------------------------------

    if total > 0:

        confidence = (
            50
            + (
                difference
                / total
            ) * 45
        )

        confidence = round(
            confidence
        )

    else:

        confidence = 50

    confidence = max(
        50,
        min(
            95,
            confidence
        )
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    if (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
    ):

        if (
            ema20 > ema50
            and ema50 > ema200
        ):

            trend = "STRONG BULLISH"

        elif (
            ema20 < ema50
            and ema50 < ema200
        ):

            trend = "STRONG BEARISH"

        elif ema20 > ema50:

            trend = "BULLISH"

        elif ema20 < ema50:

            trend = "BEARISH"

        else:

            trend = "SIDEWAYS"

    else:

        trend = "UNKNOWN"

    # -----------------------------------------------------
    # FIRST 30 SECOND WINDOW
    # -----------------------------------------------------

    window = current_candle_window()

    # -----------------------------------------------------
    # DATA AGE
    # -----------------------------------------------------

    age = candle_age_seconds(
        current_candle
    )

    if age is not None:

        data_recent = age <= max(
            180,
            minutes * 60 * 2
        )

    else:

        data_recent = False

    # -----------------------------------------------------
    # MARKET STATUS
    # -----------------------------------------------------

    if otc:

        market_status = (
            "OTC / PROXY DATA"
        )

    else:

        if forex_weekend_closed():

            market_status = (
                "FOREX MARKET CLOSED"
            )

        else:

            market_status = (
                "LIVE MARKET"
            )

    # -----------------------------------------------------
    # SCANNER STATUS
    # -----------------------------------------------------

    if window["first_30_seconds"]:

        scan_status = (
            "FIRST 30 SECONDS"
        )

    else:

        scan_status = (
            "AFTER 30 SECONDS"
        )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    return {

        "success": True,

        "symbol": original_symbol,

        "clean_symbol": clean,

        "timeframe": str(timeframe),

        "minutes": minutes,

        "signal": direction,

        "direction": direction,

        "confidence": confidence,

        "bullish_score": bullish,

        "bearish_score": bearish,

        "score_difference": difference,

        "strength": strength,

        "price": round(
            live_price,
            8
        ),

        "last_candle_close": round(
            last_closed_price,
            8
        ),

        "trend": trend,

        "momentum": momentum,

        "market_status": market_status,

        "scan_status": scan_status,

        "first_30_seconds":
            window["first_30_seconds"],

        "elapsed_seconds":
            window["elapsed_seconds"],

        "remaining_seconds":
            window["remaining_seconds"],

        "data_recent":
            data_recent,

        "candle_age_seconds":
            round(age, 2)
            if age is not None
            else None,

        "rsi":
            round(rsi, 2)
            if rsi is not None
            else None,

        "ema20":
            round(ema20, 8)
            if ema20 is not None
            else None,

        "ema50":
            round(ema50, 8)
            if ema50 is not None
            else None,

        "ema200":
            round(ema200, 8)
            if ema200 is not None
            else None,

        "bollinger": {

            "upper":
                round(bb["upper"], 8),

            "middle":
                round(bb["middle"], 8),

            "lower":
                round(bb["lower"], 8),

            "width":
                round(bb["width"], 8)

        } if bb else None,

        "bollinger_position":
            bb_position,

        "support":
            round(support, 8)
            if support is not None
            else None,

        "resistance":
            round(resistance, 8)
            if resistance is not None
            else None,

        "candle": candle,

        "reasons":
            selected_reasons[:8],

        "bullish_reasons":
            bull_reasons[:8],

        "bearish_reasons":
            bear_reasons[:8],

        "candle_time":
            current_candle.get(
                "datetime"
            ),

        "is_otc":
            otc,

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat()
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "template.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=OTC_PAIRS,
        timeframes=TIMEFRAMES
    )


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({

        "status": "ok",

        "service":
            "Ai-Signal-pro",

        "scanner":
            "chart-analysis-engine",

        "api_key_configured":
            bool(API_KEY),

        "time":
            datetime.now(
                timezone.utc
            ).isoformat()
    })


# =========================================================
# PAIRS
# =========================================================

@app.route("/api/pairs")
def api_pairs():

    return jsonify({

        "success": True,

        "real": REAL_PAIRS,

        "otc": OTC_PAIRS,

        "timeframes":
            list(TIMEFRAMES.keys())
    })


# =========================================================
# SIGNAL API
# =========================================================

@app.route("/api/signal")
def api_signal():

    symbol = request.args.get(
        "symbol",
        "EUR/USD"
    )

    timeframe = request.args.get(
        "timeframe",
        "1"
    )

    if str(timeframe) not in TIMEFRAMES:

        return jsonify({

            "success": False,

            "error":
                "Invalid timeframe."

        }), 400

    try:

        result = analyze_market(
            symbol,
            timeframe
        )

        return jsonify(result)

    except Exception as e:

        return jsonify({

            "success": False,

            "symbol": symbol,

            "timeframe": timeframe,

            "error": str(e),

            "message":
                "Unable to scan market."

        }), 500


# =========================================================
# SIGNAL PAGE
# =========================================================

@app.route("/signal")
def signal_page():

    return render_template(
        "template.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=OTC_PAIRS,
        timeframes=TIMEFRAMES
    )


# =========================================================
# ERRORS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "success": False,

        "error": "Not found."

    }), 404


@app.errorhandler(500)
def internal_error(error):

    return jsonify({

        "success": False,

        "error":
            "Internal server error."

    }), 500


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
