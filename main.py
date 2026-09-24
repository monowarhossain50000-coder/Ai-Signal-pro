import os
import time
import math
import requests

from datetime import datetime, timezone
from threading import Lock

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)


# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("TWELVEDATA_API_KEY")

TWELVE_DATA_URL = "https://api.twelvedata.com"

CACHE_SECONDS = 8
API_MIN_GAP = 12

market_cache = {}
quote_cache = {}

last_api_request = 0.0
last_quote_request = 0.0

cache_lock = Lock()
quote_lock = Lock()


# ============================================================
# SYMBOLS
# ============================================================

REAL_PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
    "EUR/GBP",
    "EUR/JPY",
    "GBP/JPY",
    "AUD/JPY",
    "EUR/AUD",
    "EUR/CAD",
    "GBP/CAD",
    "CHF/JPY",
    "CAD/JPY",
    "AUD/CAD",
    "NZD/JPY",
    "GBP/CHF",
    "EUR/CHF",
]


OTC_PAIRS = [
    "EUR/USD OTC",
    "GBP/USD OTC",
    "USD/JPY OTC",
    "USD/CHF OTC",
    "AUD/USD OTC",
    "USD/CAD OTC",
    "NZD/USD OTC",
    "EUR/GBP OTC",
    "EUR/JPY OTC",
    "GBP/JPY OTC",
    "AUD/JPY OTC",
    "EUR/AUD OTC",
    "EUR/CAD OTC",
    "GBP/CAD OTC",
    "USD/BDT OTC",
    "USD/INR OTC",
    "USD/PKR OTC",
    "USD/TRY OTC",
    "USD/ZAR OTC",
    "XAU/USD OTC",
    "XAG/USD OTC",
    "BTC/USD OTC",
    "ETH/USD OTC",
    "AAPL OTC",
    "TSLA OTC",
    "AMZN OTC",
    "MSFT OTC",
    "GOOGL OTC",
]


TIMEFRAMES = {
    "1": 1,
    "2": 2,
    "3": 3,
    "5": 5,
    "10": 10,
    "15": 15,
    "30": 30,
    "60": 60,
    "240": 240,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(symbol):
    symbol = (symbol or "EUR/USD").strip().upper()
    symbol = symbol.replace(" OTC", "").strip()
    return symbol


def is_otc_symbol(symbol):
    return " OTC" in (symbol or "").upper()


def utc_now():
    return datetime.now(timezone.utc)


def clamp(value, low, high):
    return max(low, min(high, value))


def round_price(value):
    if value is None:
        return None

    if abs(value) >= 100:
        return round(value, 3)

    if abs(value) >= 1:
        return round(value, 5)

    return round(value, 8)


def parse_market_datetime(value):
    if not value:
        return None

    text = str(value).strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):
    if not values:
        return None

    if len(values) < period:
        period = len(values)

    if period <= 0:
        return None

    sma = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    ema = sma

    for price in values[period:]:
        ema = ((price - ema) * multiplier) + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            ((avg_gain * (period - 1)) + gains[i])
            / period
        )

        avg_loss = (
            ((avg_loss * (period - 1)) + losses[i])
            / period
        )

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# BOLLINGER BANDS
# ============================================================

def calculate_bollinger(values, period=20, multiplier=2):
    if len(values) < period:
        return None

    window = values[-period:]

    middle = sum(window) / period

    variance = sum(
        (price - middle) ** 2
        for price in window
    ) / period

    std = math.sqrt(variance)

    upper = middle + (multiplier * std)
    lower = middle - (multiplier * std)

    return {
        "lower": round_price(lower),
        "middle": round_price(middle),
        "upper": round_price(upper),
        "width": round_price(upper - lower),
    }


# ============================================================
# CANDLE ANALYSIS
# ============================================================

def analyze_candle(candle):

    if not candle:
        return None

    o = safe_float(candle.get("open"))
    h = safe_float(candle.get("high"))
    l = safe_float(candle.get("low"))
    c = safe_float(candle.get("close"))

    if None in (o, h, l, c):
        return None

    candle_range = max(h - l, 0)

    body = abs(c - o)

    if candle_range > 0:
        body_ratio = body / candle_range
        close_position = (c - l) / candle_range
    else:
        body_ratio = 0
        close_position = 0.5

    upper_wick = max(h - max(o, c), 0)
    lower_wick = max(min(o, c) - l, 0)

    if c > o:
        direction = "BULLISH"
    elif c < o:
        direction = "BEARISH"
    else:
        direction = "DOJI"

    return {
        "open": round_price(o),
        "high": round_price(h),
        "low": round_price(l),
        "close": round_price(c),

        "body": round_price(body),
        "range": round_price(candle_range),

        "body_ratio": round(body_ratio, 4),
        "close_position": round(close_position, 4),

        "upper_wick": round_price(upper_wick),
        "lower_wick": round_price(lower_wick),

        "direction": direction,
    }


# ============================================================
# CANDLE SIGNAL
# ============================================================

def candle_signal(candle):

    result = analyze_candle(candle)

    if not result:
        return {
            "signal": None,
            "score": 0,
            "reasons": [],
        }

    direction = result["direction"]
    body_ratio = result["body_ratio"]
    close_position = result["close_position"]

    reasons = []
    score = 0
    signal = None

    if direction == "BULLISH":

        if body_ratio >= 0.70 and close_position >= 0.75:
            signal = "CALL"
            score = 18
            reasons.append("Strong bullish candle")

        elif (
            result["lower_wick"] is not None
            and result["range"]
            and result["lower_wick"] >= result["range"] * 0.35
            and close_position >= 0.65
        ):
            signal = "CALL"
            score = 14
            reasons.append("Lower-wick bullish rejection")

        elif close_position >= 0.70:
            signal = "CALL"
            score = 9
            reasons.append("Bullish close near candle high")

    elif direction == "BEARISH":

        if body_ratio >= 0.70 and close_position <= 0.25:
            signal = "PUT"
            score = 18
            reasons.append("Strong bearish candle")

        elif (
            result["upper_wick"] is not None
            and result["range"]
            and result["upper_wick"] >= result["range"] * 0.35
            and close_position <= 0.35
        ):
            signal = "PUT"
            score = 14
            reasons.append("Upper-wick bearish rejection")

        elif close_position <= 0.30:
            signal = "PUT"
            score = 9
            reasons.append("Bearish close near candle low")

    return {
        "signal": signal,
        "score": score,
        "reasons": reasons,
    }


# ============================================================
# MOMENTUM
# ============================================================

def recent_momentum(candles, lookback=5):

    if len(candles) < 2:
        return {
            "direction": "NEUTRAL",
            "score": 0,
            "reasons": [],
        }

    recent = candles[-lookback:]

    bullish = 0
    bearish = 0

    for candle in recent:
        o = safe_float(candle.get("open"))
        c = safe_float(candle.get("close"))

        if o is None or c is None:
            continue

        if c > o:
            bullish += 1

        elif c < o:
            bearish += 1

    if bullish > bearish:
        return {
            "direction": "BULLISH",
            "score": 8,
            "reasons": ["Recent candle momentum bullish"],
        }

    if bearish > bullish:
        return {
            "direction": "BEARISH",
            "score": 8,
            "reasons": ["Recent candle momentum bearish"],
        }

    return {
        "direction": "NEUTRAL",
        "score": 0,
        "reasons": [],
    }


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def find_support_resistance(candles, current_price):

    if not candles or current_price is None:
        return {
            "support": None,
            "resistance": None,
            "support_distance_pct": None,
            "resistance_distance_pct": None,
        }

    highs = []
    lows = []

    for candle in candles[-120:]:

        h = safe_float(candle.get("high"))
        l = safe_float(candle.get("low"))

        if h is not None:
            highs.append(h)

        if l is not None:
            lows.append(l)

    below = [
        x for x in lows
        if x < current_price
    ]

    above = [
        x for x in highs
        if x > current_price
    ]

    support = max(below) if below else None
    resistance = min(above) if above else None

    support_distance = None
    resistance_distance = None

    if support is not None and current_price:
        support_distance = (
            abs(current_price - support)
            / current_price
        ) * 100

    if resistance is not None and current_price:
        resistance_distance = (
            abs(resistance - current_price)
            / current_price
        ) * 100

    return {
        "support": round_price(support),
        "resistance": round_price(resistance),

        "support_distance_pct": (
            round(support_distance, 4)
            if support_distance is not None
            else None
        ),

        "resistance_distance_pct": (
            round(resistance_distance, 4)
            if resistance_distance is not None
            else None
        ),
    }


# ============================================================
# TIME WINDOW
# ============================================================

def current_minute_window():

    now = utc_now()

    elapsed = now.second + (
        now.microsecond / 1_000_000
    )

    remaining = 60 - elapsed

    return {
        "elapsed_seconds": round(elapsed, 2),
        "remaining_seconds": round(remaining, 2),
        "first_30_seconds": elapsed < 30,
        "minute_start": now.replace(
            second=0,
            microsecond=0
        ).isoformat(),
    }


# ============================================================
# TWELVE DATA API CONTROL
# ============================================================

def wait_for_api_gap():

    global last_api_request

    with cache_lock:

        now = time.time()

        gap = now - last_api_request

        if gap < API_MIN_GAP:

            time.sleep(
                API_MIN_GAP - gap
            )

        last_api_request = time.time()


def twelve_data_request(endpoint, params):

    if not API_KEY:
        raise RuntimeError(
            "TWELVEDATA_API_KEY is not configured"
        )

    wait_for_api_gap()

    params = dict(params)

    params["apikey"] = API_KEY

    response = requests.get(
        f"{TWELVE_DATA_URL}/{endpoint}",
        params=params,
        timeout=15,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Twelve Data HTTP {response.status_code}"
        )

    data = response.json()

    if isinstance(data, dict) and data.get("status") == "error":

        raise RuntimeError(
            data.get(
                "message",
                "Twelve Data API error"
            )
        )

    return data


# ============================================================
# MARKET CANDLES
# ============================================================

def get_market_candles(symbol, timeframe):

    cache_key = (
        f"{symbol}|{timeframe}"
    )

    now = time.time()

    with cache_lock:

        cached = market_cache.get(cache_key)

        if cached:

            age = now - cached["time"]

            if age < CACHE_SECONDS:

                return cached["data"]

    interval_minutes = TIMEFRAMES.get(
        str(timeframe),
        1
    )

    if interval_minutes == 1:

        interval = "1min"

    elif interval_minutes == 2:

        interval = "2min"

    elif interval_minutes == 3:

        interval = "3min"

    elif interval_minutes == 5:

        interval = "5min"

    elif interval_minutes == 10:

        interval = "10min"

    elif interval_minutes == 15:

        interval = "15min"

    elif interval_minutes == 30:

        interval = "30min"

    elif interval_minutes == 60:

        interval = "1h"

    elif interval_minutes == 240:

        interval = "4h"

    else:

        interval = "1min"

    data = twelve_data_request(
        "time_series",
        {
            "symbol": clean_symbol(symbol),
            "interval": interval,
            "outputsize": 250,
            "format": "JSON",
        },
    )

    values = data.get("values", [])

    candles = []

    for item in reversed(values):

        candle = {
            "datetime": item.get("datetime"),

            "open": safe_float(
                item.get("open")
            ),

            "high": safe_float(
                item.get("high")
            ),

            "low": safe_float(
                item.get("low")
            ),

            "close": safe_float(
                item.get("close")
            ),

            "volume": safe_float(
                item.get("volume")
            ),
        }

        if None not in (
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
        ):
            candles.append(candle)

    if not candles:

        raise RuntimeError(
            "No candle data returned"
        )

    with cache_lock:

        market_cache[cache_key] = {
            "time": time.time(),
            "data": candles,
        }

    return candles


# ============================================================
# LIVE QUOTE
# ============================================================

def get_live_quote(symbol):

    cache_key = clean_symbol(symbol)

    now = time.time()

    with quote_lock:

        cached = quote_cache.get(cache_key)

        if cached:

            age = now - cached["time"]

            if age < CACHE_SECONDS:

                return cached["data"]

    data = twelve_data_request(
        "quote",
        {
            "symbol": clean_symbol(symbol),
        },
    )

    price = safe_float(
        data.get("close")
        or data.get("price")
    )

    if price is None:

        raise RuntimeError(
            "Live quote unavailable"
        )

    result = {
        "price": price,

        "open": safe_float(
            data.get("open")
        ),

        "high": safe_float(
            data.get("high")
        ),

        "low": safe_float(
            data.get("low")
        ),

        "previous_close": safe_float(
            data.get("previous_close")
        ),

        "change": safe_float(
            data.get("change")
        ),

        "percent_change": safe_float(
            data.get("percent_change")
        ),

        "timestamp": data.get(
            "timestamp"
        ),
    }

    with quote_lock:

        quote_cache[cache_key] = {
            "time": time.time(),
            "data": result,
        }

    return result


# ============================================================
# RUNNING CANDLE
# ============================================================

def build_running_candle(
    candles,
    live_price
):

    now = utc_now()

    current_minute = now.replace(
        second=0,
        microsecond=0
    )

    current_time_text = (
        current_minute.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    if not candles:

        return {
            "datetime": current_time_text,
            "open": live_price,
            "high": live_price,
            "low": live_price,
            "close": live_price,
            "source": "LIVE_QUOTE",
        }

    last = candles[-1]

    last_dt = parse_market_datetime(
        last.get("datetime")
    )

    if last_dt:

        last_minute = last_dt.replace(
            second=0,
            microsecond=0
        )

        if last_minute == current_minute:

            o = safe_float(
                last.get("open"),
                live_price
            )

            h = safe_float(
                last.get("high"),
                live_price
            )

            l = safe_float(
                last.get("low"),
                live_price
            )

            return {
                "datetime": current_time_text,

                "open": o,

                "high": max(
                    h,
                    live_price
                ),

                "low": min(
                    l,
                    live_price
                ),

                "close": live_price,

                "source":
                    "LIVE_QUOTE_UPDATED_CANDLE",
            }

    previous_close = safe_float(
        last.get("close"),
        live_price
    )

    return {
        "datetime": current_time_text,

        "open": previous_close,

        "high": max(
            previous_close,
            live_price
        ),

        "low": min(
            previous_close,
            live_price
        ),

        "close": live_price,

        "source":
            "RECONSTRUCTED_FROM_LIVE_QUOTE",
    }


# ============================================================
# MAIN MARKET ANALYSIS
# ============================================================

def analyze_market(
    symbol,
    timeframe
):

    requested_symbol = symbol or "EUR/USD"

    market_symbol = clean_symbol(
        requested_symbol
    )

    timeframe = str(
        timeframe or "1"
    )

    if timeframe not in TIMEFRAMES:

        timeframe = "1"

    candles = get_market_candles(
        market_symbol,
        timeframe
    )

    live = get_live_quote(
        market_symbol
    )

    live_price = live["price"]

    running = build_running_candle(
        candles,
        live_price
    )

    analysis_candles = list(candles)

    if timeframe == "1":

        if analysis_candles:

            last_dt = parse_market_datetime(
                analysis_candles[-1].get(
                    "datetime"
                )
            )

            now_minute = utc_now().replace(
                second=0,
                microsecond=0
            )

            if (
                last_dt
                and
                last_dt.replace(
                    second=0,
                    microsecond=0
                ) == now_minute
            ):

                analysis_candles[-1] = running

            else:

                analysis_candles.append(
                    running
                )

        else:

            analysis_candles = [
                running
            ]

    closes = [
        safe_float(c.get("close"))
        for c in analysis_candles
        if safe_float(c.get("close"))
        is not None
    ]

    if len(closes) < 20:

        raise RuntimeError(
            "Not enough candle history"
        )

    # --------------------------------------------------------
    # INDICATORS
    # --------------------------------------------------------

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

    bollinger = calculate_bollinger(
        closes,
        20,
        2
    )

    sr = find_support_resistance(
        analysis_candles,
        live_price
    )

    candle_info = analyze_candle(
        running
    )

    candle_vote = candle_signal(
        running
    )

    momentum = recent_momentum(
        analysis_candles,
        5
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    bullish_score = 0
    bearish_score = 0

    bullish_reasons = []
    bearish_reasons = []

    def bull(points, reason):

        nonlocal bullish_score

        bullish_score += points

        if reason:
            bullish_reasons.append(
                reason
            )

    def bear(points, reason):

        nonlocal bearish_score

        bearish_score += points

        if reason:
            bearish_reasons.append(
                reason
            )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema20 is not None:

        if live_price > ema20:
            bull(8, "Price above EMA20")

        elif live_price < ema20:
            bear(8, "Price below EMA20")

    if ema50 is not None:

        if live_price > ema50:
            bull(8, "Price above EMA50")

        elif live_price < ema50:
            bear(8, "Price below EMA50")

    if ema200 is not None:

        if live_price > ema200:
            bull(8, "Price above EMA200")

        elif live_price < ema200:
            bear(8, "Price below EMA200")

    if (
        ema20 is not None
        and ema50 is not None
    ):

        if ema20 > ema50:

            bull(
                8,
                "EMA20 above EMA50"
            )

        elif ema20 < ema50:

            bear(
                8,
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

            bull(
                10,
                "EMA bullish alignment"
            )

        elif (
            ema20 < ema50
            and ema50 < ema200
        ):

            bear(
                10,
                "EMA bearish alignment"
            )

    # --------------------------------------------------------
    # BOLLINGER
    # --------------------------------------------------------

    bollinger_position = "UNKNOWN"

    if bollinger:

        upper = bollinger["upper"]
        middle = bollinger["middle"]
        lower = bollinger["lower"]

        if live_price >= upper:

            bollinger_position = "ABOVE UPPER"

            bear(
                12,
                "Price at/above upper Bollinger Band"
            )

        elif live_price <= lower:

            bollinger_position = "BELOW LOWER"

            bull(
                12,
                "Price at/below lower Bollinger Band"
            )

        elif live_price > middle:

            bollinger_position = "ABOVE MIDDLE"

            bull(
                5,
                "Price above Bollinger middle"
            )

        elif live_price < middle:

            bollinger_position = "BELOW MIDDLE"

            bear(
                5,
                "Price below Bollinger middle"
            )

        else:

            bollinger_position = "AT MIDDLE"

    # --------------------------------------------------------
    # SUPPORT / RESISTANCE
    # --------------------------------------------------------

    support = sr["support"]
    resistance = sr["resistance"]

    support_distance = (
        sr["support_distance_pct"]
    )

    resistance_distance = (
        sr["resistance_distance_pct"]
    )

    if (
        support is not None
        and support_distance is not None
        and support_distance <= 0.15
    ):

        bull(
            15,
            "Price near support"
        )

    if (
        resistance is not None
        and resistance_distance is not None
        and resistance_distance <= 0.15
    ):

        bear(
            15,
            "Price near resistance"
        )

    # --------------------------------------------------------
    # CANDLE
    # --------------------------------------------------------

    if candle_vote["signal"] == "CALL":

        bull(
            candle_vote["score"],
            candle_vote["reasons"][0]
            if candle_vote["reasons"]
            else "Bullish candle pattern"
        )

    elif candle_vote["signal"] == "PUT":

        bear(
            candle_vote["score"],
            candle_vote["reasons"][0]
            if candle_vote["reasons"]
            else "Bearish candle pattern"
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if momentum["direction"] == "BULLISH":

        bull(
            momentum["score"],
            "Recent candle momentum bullish"
        )

    elif momentum["direction"] == "BEARISH":

        bear(
            momentum["score"],
            "Recent candle momentum bearish"
        )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi is not None:

        if rsi >= 70:

            bear(
                4,
                "RSI overbought"
            )

        elif rsi <= 30:

            bull(
                4,
                "RSI oversold"
            )

        elif rsi >= 55:

            bull(
                5,
                "RSI bullish confirmation"
            )

        elif rsi <= 45:

            bear(
                5,
                "RSI bearish confirmation"
            )

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if bullish_score > bearish_score:

        signal = "CALL"
        direction = "UP"

    elif bearish_score > bullish_score:

        signal = "PUT"
        direction = "DOWN"

    else:

        # Balanced market.
        # We still return a direction based on the
        # latest candle, but confidence remains low.

        if candle_info:

            if candle_info["direction"] == "BULLISH":

                signal = "CALL"
                direction = "UP"

            elif candle_info["direction"] == "BEARISH":

                signal = "PUT"
                direction = "DOWN"

            else:

                signal = "CALL"
                direction = "UP"

        else:

            signal = "CALL"
            direction = "UP"

    total_score = (
        bullish_score
        + bearish_score
    )

    if total_score > 0:

        score_difference = abs(
            bullish_score
            - bearish_score
        )

        confidence = 50 + (
            score_difference
            / total_score
            * 45
        )

    else:

        confidence = 50

    confidence = int(
        round(
            clamp(
                confidence,
                50,
                95
            )
        )
    )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

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

    timing = current_minute_window()

    # --------------------------------------------------------
    # DATA QUALITY
    # --------------------------------------------------------

    data_source = (
        "Twelve Data live quote + candle history"
    )

    if is_otc_symbol(requested_symbol):

        market_status = (
            "OTC PROXY DATA"
        )

        data_source = (
            "Twelve Data proxy data; "
            "NOT direct Quotex OTC feed"
        )

    else:

        market_status = "LIVE MARKET"

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {

        "success": True,

        "symbol": requested_symbol,

        "market_symbol": market_symbol,

        "market_status": market_status,

        "data_source": data_source,

        "timeframe": timeframe,

        "signal": signal,

        "direction": direction,

        "confidence": confidence,

        "price": round_price(
            live_price
        ),

        "trend": trend,

        "strength": round(
            abs(
                bullish_score
                - bearish_score
            )
            / max(
                total_score,
                1
            )
            * 100,
            1
        ),

        "scores": {

            "bullish": bullish_score,

            "bearish": bearish_score,

        },

        "bullish_score": bullish_score,

        "bearish_score": bearish_score,

        "bullish_reasons":
            bullish_reasons,

        "bearish_reasons":
            bearish_reasons,

        "ema": {

            "ema20": round_price(
                ema20
            ),

            "ema50": round_price(
                ema50
            ),

            "ema200": round_price(
                ema200
            ),

        },

        "rsi14": (
            round(rsi, 2)
            if rsi is not None
            else None
        ),

        "bollinger": bollinger,

        "bollinger_position":
            bollinger_position,

        "support":
            support,

        "resistance":
            resistance,

        "support_distance_pct":
            support_distance,

        "resistance_distance_pct":
            resistance_distance,

        "candle": candle_info,

        "running_candle": {

            **running,

            "open":
                round_price(
                    running["open"]
                ),

            "high":
                round_price(
                    running["high"]
                ),

            "low":
                round_price(
                    running["low"]
                ),

            "close":
                round_price(
                    running["close"]
                ),

        },

        "running_candle_source":
            running.get("source"),

        "timing": timing,

        "elapsed_seconds":
            timing["elapsed_seconds"],

        "remaining_seconds":
            timing["remaining_seconds"],

        "first_30_seconds":
            timing["first_30_seconds"],

        "candle_age_seconds":
            timing["elapsed_seconds"],

        "candle_time":
            running.get("datetime"),

        "candles_scanned":
            len(analysis_candles),

        "data_recent": True,

        "updated_at":
            utc_now().isoformat(),

    }


# ============================================================
# ERROR RESPONSE
# ============================================================

def error_response(message, status=500):

    return jsonify({

        "success": False,

        "error": str(message),

        "updated_at":
            utc_now().isoformat(),

    }), status


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():

    try:

        return render_template(
            "template.html"
        )

    except Exception as exc:

        return f"""
        <html>
        <head>
            <title>AI Signal Pro</title>
        </head>
        <body>
            <h1>AI SIGNAL PRO</h1>
            <p>Scanner backend is running.</p>
            <p>Template error: {exc}</p>
        </body>
        </html>
        """


@app.route("/health")
def health():

    return jsonify({

        "status": "ok",

        "service":
            "Ai-Signal-pro",

        "api_key_configured":
            bool(API_KEY),

        "time":
            utc_now().isoformat(),

    })


@app.route("/api/pairs")
def api_pairs():

    return jsonify({

        "success": True,

        "real": REAL_PAIRS,

        "otc": OTC_PAIRS,

        "timeframes":
            list(TIMEFRAMES.keys()),

    })


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

    try:

        result = analyze_market(
            symbol,
            timeframe
        )

        return jsonify(result)

    except Exception as exc:

        return error_response(
            exc,
            500
        )


@app.route("/signal")
def signal_page():

    symbol = request.args.get(
        "symbol",
        "EUR/USD"
    )

    timeframe = request.args.get(
        "timeframe",
        "1"
    )

    try:

        result = analyze_market(
            symbol,
            timeframe
        )

        return jsonify(result)

    except Exception as exc:

        return error_response(
            exc,
            500
        )


# ============================================================
# GLOBAL ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "success": False,

        "error":
            "Route not found",

        "available_routes": [

            "/",

            "/health",

            "/api/pairs",

            "/api/signal",

            "/signal",

        ],

    }), 404


@app.errorhandler(500)
def internal_error(error):

    return jsonify({

        "success": False,

        "error":
            "Internal server error",

    }), 500


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
