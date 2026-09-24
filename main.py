import os
import time
import math
import requests

from datetime import datetime, timezone
from threading import Lock

from flask import Flask, render_template, jsonify, request


# =========================================================
# FLASK APP
# =========================================================

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
# DATETIME
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
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


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

    allowed_delay = max(
        180,
        TIMEFRAMES.get(
            str(timeframe),
            1
        ) * 60 * 2
    )

    if age_seconds < -60:
        return False, "Invalid future candle."

    if age_seconds > allowed_delay:
        return False, "Live market candle is too old."

    return True, None


# =========================================================
# EMA
# =========================================================

def calculate_ema(prices, period):

    if len(prices) < period:
        return None

    ema = sum(prices[:period]) / period

    multiplier = 2 / (period + 1)

    for price in prices[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

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

        change = (
            prices[i] - prices[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period]) / period
    )

    avg_loss = (
        sum(losses[:period]) / period
    )

    for i in range(period, len(gains)):

        avg_gain = (
            (
                avg_gain * (period - 1)
            ) + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss * (period - 1)
            ) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

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
        safe_float(c["high"])
        for c in recent
    ]

    lows = [
        safe_float(c["low"])
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

    o = safe_float(
        candle.get("open")
    )

    h = safe_float(
        candle.get("high")
    )

    l = safe_float(
        candle.get("low")
    )

    c = safe_float(
        candle.get("close")
    )

    candle_range = h - l

    body = abs(c - o)

    if candle_range > 0:

        body_ratio = (
            body / candle_range
        )

        close_position = (
            (c - l) / candle_range
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
        "direction": direction,
        "body_ratio": body_ratio,
        "range": candle_range,
        "close_position": close_position
    }


# =========================================================
# MARKET DATA
# =========================================================

def get_market_candles(symbol, minutes):

    global last_api_request

    symbol = clean_symbol(symbol)

    cache_key = (
        symbol,
        minutes
    )

    now = time.time()

    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    with cache_lock:

        cached = market_cache.get(
            cache_key
        )

        if cached:

            age = (
                now - cached["time"]
            )

            if age < CACHE_SECONDS:
                return cached["data"]

    # -----------------------------------------------------
    # API RATE LIMIT
    # -----------------------------------------------------

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

            wait_time = (
                API_MIN_GAP - elapsed
            )

            time.sleep(
                wait_time
            )

        last_api_request = time.time()

    # -----------------------------------------------------
    # INTERVAL
    # -----------------------------------------------------

    if minutes == 60:

        interval = "1h"

    elif minutes == 240:

        interval = "4h"

    else:

        interval = "1min"

    # -----------------------------------------------------
    # API KEY
    # -----------------------------------------------------

    if not API_KEY:

        raise Exception(
            "TWELVEDATA_API_KEY environment variable is missing."
        )

    # -----------------------------------------------------
    # TWELVE DATA
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # RATE LIMIT
    # -----------------------------------------------------

    if response.status_code == 429:

        cached = market_cache.get(
            cache_key
        )

        if cached:
            return cached["data"]

        raise Exception(
            "Twelve Data rate limit reached."
        )

    # -----------------------------------------------------
    # HTTP ERROR
    # -----------------------------------------------------

    response.raise_for_status()

    data = response.json()

    # -----------------------------------------------------
    # API ERROR
    # -----------------------------------------------------

    if "values" not in data:

        raise Exception(
            data.get(
                "message",
                "Market data unavailable."
            )
        )

    # -----------------------------------------------------
    # RAW DATA
    # -----------------------------------------------------

    raw = list(
        reversed(
            data["values"]
        )
    )

    candles = []

    # -----------------------------------------------------
    # NATIVE TIMEFRAMES
    # -----------------------------------------------------

    if minutes in [1, 60, 240]:

        for item in raw:

            candles.append({
                "datetime": item.get(
                    "datetime"
                ),

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
                )
            })

    # -----------------------------------------------------
    # AGGREGATED TIMEFRAMES
    # -----------------------------------------------------

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
                        group[0].get(
                            "open"
                        )
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
                        group[-1].get(
                            "close"
                        )
                    )
            })

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if len(candles) < 30:

        raise Exception(
            "Not enough market candles."
        )

    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    with cache_lock:

        market_cache[cache_key] = {
            "time": time.time(),
            "data": candles
        }

    return candles


# =========================================================
# SIGNAL ANALYSIS
# =========================================================

def analyze_market(
    symbol,
    timeframe
):

    minutes = TIMEFRAMES.get(
        str(timeframe),
        1
    )

    clean = clean_symbol(symbol)

    candles = get_market_candles(
        clean,
        minutes
    )

    if len(candles) < 30:

        raise Exception(
            "Insufficient candle data."
        )

    closes = [
        safe_float(c["close"])
        for c in candles
    ]

    current = candles[-1]

    price = safe_float(
        current["close"]
    )

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

    bollinger = calculate_bollinger(
        closes,
        20,
        2
    )

    sr = calculate_support_resistance(
        candles,
        min(50, len(candles))
    )

    candle = candle_info(
        current
    )

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    bullish_score = 0
    bearish_score = 0

    reasons = []

    # EMA 20
    if ema20 is not None:

        if price > ema20:

            bullish_score += 15

            reasons.append(
                "Price above EMA20"
            )

        elif price < ema20:

            bearish_score += 15

            reasons.append(
                "Price below EMA20"
            )

    # EMA 50
    if ema50 is not None:

        if price > ema50:

            bullish_score += 15

            reasons.append(
                "Price above EMA50"
            )

        elif price < ema50:

            bearish_score += 15

            reasons.append(
                "Price below EMA50"
            )

    # EMA 200
    if ema200 is not None:

        if price > ema200:

            bullish_score += 15

            reasons.append(
                "Price above EMA200"
            )

        elif price < ema200:

            bearish_score += 15

            reasons.append(
                "Price below EMA200"
            )

    # EMA trend
    if (
        ema20 is not None
        and ema50 is not None
    ):

        if ema20 > ema50:

            bullish_score += 10

            reasons.append(
                "EMA20 above EMA50"
            )

        elif ema20 < ema50:

            bearish_score += 10

            reasons.append(
                "EMA20 below EMA50"
            )

    # RSI
    if rsi is not None:

        if rsi >= 55:

            bullish_score += 15

            reasons.append(
                "RSI bullish"
            )

        elif rsi <= 45:

            bearish_score += 15

            reasons.append(
                "RSI bearish"
            )

    # Bollinger
    if bollinger:

        if price > bollinger["middle"]:

            bullish_score += 10

            reasons.append(
                "Price above Bollinger middle"
            )

        elif price < bollinger["middle"]:

            bearish_score += 10

            reasons.append(
                "Price below Bollinger middle"
            )

    # Candle
    if candle["direction"] == "BULLISH":

        bullish_score += 10

        reasons.append(
            "Current candle bullish"
        )

    elif candle["direction"] == "BEARISH":

        bearish_score += 10

        reasons.append(
            "Current candle bearish"
        )

    # Support / Resistance
    if sr:

        support = sr["support"]
        resistance = sr["resistance"]

        distance_support = abs(
            price - support
        )

        distance_resistance = abs(
            resistance - price
        )

        if (
            distance_support
            < distance_resistance
        ):

            bullish_score += 5

            reasons.append(
                "Price closer to support"
            )

        elif (
            distance_resistance
            < distance_support
        ):

            bearish_score += 5

            reasons.append(
                "Price closer to resistance"
            )

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    total_score = (
        bullish_score
        + bearish_score
    )

    if total_score <= 0:

        direction = "NO TRADE"
        confidence = 50

    elif bullish_score > bearish_score:

        direction = "CALL / UP"

        confidence = round(
            50
            + (
                bullish_score
                / max(total_score, 1)
            ) * 50
        )

    elif bearish_score > bullish_score:

        direction = "PUT / DOWN"

        confidence = round(
            50
            + (
                bearish_score
                / max(total_score, 1)
            ) * 50
        )

    else:

        direction = "NO TRADE"
        confidence = 50

    confidence = max(
        50,
        min(99, confidence)
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

    elif (
        ema20 is not None
        and ema50 is not None
    ):

        if ema20 > ema50:

            trend = "BULLISH"

        elif ema20 < ema50:

            trend = "BEARISH"

        else:

            trend = "SIDEWAYS"

    else:

        trend = "UNKNOWN"

    # -----------------------------------------------------
    # MARKET STATUS
    # -----------------------------------------------------

    otc = is_otc_symbol(symbol)

    if otc:

        market_status = (
            "OTC / Proxy Market Data"
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
    # CANDLE STATUS
    # -----------------------------------------------------

    recent_ok, recent_message = (
        is_recent_market_data(
            current,
            str(timeframe)
        )
    )

    if not recent_ok and not otc:

        market_status = (
            "DATA DELAYED"
        )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    result = {

        "success": True,

        "symbol": symbol,

        "clean_symbol": clean,

        "timeframe": str(timeframe),

        "minutes": minutes,

        "direction": direction,

        "signal": direction,

        "confidence": confidence,

        "price": price,

        "trend": trend,

        "market_status": market_status,

        "is_otc": otc,

        "data_recent": recent_ok,

        "data_message": recent_message,

        "rsi": round(
            rsi,
            2
        ) if rsi is not None else None,

        "ema20": round(
            ema20,
            8
        ) if ema20 is not None else None,

        "ema50": round(
            ema50,
            8
        ) if ema50 is not None else None,

        "ema200": round(
            ema200,
            8
        ) if ema200 is not None else None,

        "bollinger": {
            "upper": round(
                bollinger["upper"],
                8
            ),
            "middle": round(
                bollinger["middle"],
                8
            ),
            "lower": round(
                bollinger["lower"],
                8
            )
        } if bollinger else None,

        "support": round(
            sr["support"],
            8
        ) if sr else None,

        "resistance": round(
            sr["resistance"],
            8
        ) if sr else None,

        "candle": candle,

        "bullish_score": bullish_score,

        "bearish_score": bearish_score,

        "total_score": total_score,

        "strength": round(
            abs(
                bullish_score
                - bearish_score
            )
            / max(total_score, 1)
            * 100,
            1
        ),

        "reasons": reasons,

        "candle_time": current.get(
            "datetime"
        ),

        "updated_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    return result


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
        "service": "Ai-Signal-pro",
        "api_key_configured": bool(
            API_KEY
        ),
        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })


# =========================================================
# PAIRS API
# =========================================================

@app.route("/api/pairs")
def api_pairs():

    return jsonify({

        "success": True,

        "real": REAL_PAIRS,

        "otc": OTC_PAIRS,

        "timeframes": list(
            TIMEFRAMES.keys()
        )
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

            "error": (
                "Invalid timeframe."
            )
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

            "message": (
                "Unable to generate signal."
            )
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
# ERROR HANDLERS
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

        "error": "Internal server error."

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
