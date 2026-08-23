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
# FOREX WEEKEND
# =========================================================

def forex_weekend_closed():

    now = datetime.now(timezone.utc)

    if now.weekday() == 5:
        return True

    if now.weekday() == 6 and now.hour < 21:
        return True

    if now.weekday() == 4 and now.hour >= 21:
        return True

    return False


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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================================================
# CANDLE INFO
# =========================================================

def candle_info(candle):

    o = float(candle["open"])
    h = float(candle["high"])
    l = float(candle["low"])
    c = float(candle["close"])

    candle_range = h - l
    body = abs(c - o)

    if candle_range > 0:

        body_ratio = body / candle_range

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

    cache_key = (symbol, minutes)

    now = time.time()

    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    with cache_lock:

        cached = market_cache.get(cache_key)

        if cached:

            age = now - cached["time"]

            if age < CACHE_SECONDS:
                return cached["data"]

    # -----------------------------------------------------
    # API GAP
    # -----------------------------------------------------

    with cache_lock:

        now = time.time()

        elapsed = now - last_api_request

        if elapsed < API_MIN_GAP:

            cached = market_cache.get(cache_key)

            if cached:
                return cached["data"]

            time.sleep(API_MIN_GAP - elapsed)

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
    # REQUEST
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

    if response.status_code == 429:

        cached = market_cache.get(cache_key)

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

    raw = list(reversed(data["values"]))

    candles = []

    # -----------------------------------------------------
    # NORMAL TIMEFRAMES
    # -----------------------------------------------------

    if minutes in [1, 60, 240]:

        for item in raw:

            candles.append({

                "datetime":
                    item.get("datetime"),

                "open":
                    float(item["open"]),

                "high":
                    float(item["high"]),

                "low":
                    float(item["low"]),

                "close":
                    float(item["close"])
            })

    # -----------------------------------------------------
    # CUSTOM TIMEFRAMES
    # -----------------------------------------------------

    else:

        for i in range(
            0,
            len(raw) - minutes + 1,
            minutes
        ):

            group = raw[i:i + minutes]

            candles.append({

                "datetime":
                    group[0].get("datetime"),

                "open":
                    float(group[0]["open"]),

                "high":
                    max(
                        float(x["high"])
                        for x in group
                    ),

                "low":
                    min(
                        float(x["low"])
                        for x in group
                    ),

                "close":
                    float(group[-1]["close"])
            })

    # -----------------------------------------------------
    # CACHE SAVE
    # -----------------------------------------------------

    with cache_lock:

        market_cache[cache_key] = {
            "time": time.time(),
            "data": candles
        }

    return candles


# =========================================================
# RUNNING CANDLE SIGNAL
# =========================================================

def generate_running_signal(
    candles,
    symbol,
    timeframe,
    market_type
):

    if len(candles) < 220:

        raise Exception(
            "Not enough candle data."
        )

    running = candles[-1]

    completed = candles[:-1]

    closes = [
        float(c["close"])
        for c in completed[-250:]
    ]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    rsi14 = calculate_rsi(closes, 14)

    if (
        ema20 is None
        or ema50 is None
        or ema200 is None
        or rsi14 is None
    ):

        raise Exception(
            "Indicator calculation failed."
        )

    # =====================================================
    # RUNNING CANDLE
    # =====================================================

    rc = candle_info(running)

    running_direction = rc["direction"]

    running_strength = rc["body_ratio"] * 100

    running_position = rc["close_position"]

    price = float(running["close"])

    # =====================================================
    # RECENT CANDLES
    # =====================================================

    recent = completed[-6:]

    infos = [
        candle_info(c)
        for c in recent
    ]

    bullish_count = sum(
        1
        for x in infos
        if x["direction"] == "BULLISH"
    )

    bearish_count = sum(
        1
        for x in infos
        if x["direction"] == "BEARISH"
    )

    # =====================================================
    # SCORES
    # =====================================================

    call_score = 0
    put_score = 0

    # EMA 20 / 50

    if ema20 > ema50:
        call_score += 2
    else:
        put_score += 2

    # EMA 50 / 200

    if ema50 > ema200:
        call_score += 2
    else:
        put_score += 2

    # PRICE VS EMA50

    if price >= ema50:
        call_score += 2
    else:
        put_score += 2

    # PRICE VS EMA200

    if price >= ema200:
        call_score += 1
    else:
        put_score += 1

    # =====================================================
    # RSI
    # =====================================================

    if rsi14 >= 55:

        call_score += 3

    elif rsi14 >= 50:

        call_score += 1

    elif rsi14 <= 45:

        put_score += 3

    else:

        put_score += 1

    # =====================================================
    # RECENT CANDLE MOMENTUM
    # =====================================================

    if bullish_count > bearish_count:

        call_score += 2

    elif bearish_count > bullish_count:

        put_score += 2

    # =====================================================
    # RECENT PRICE MOMENTUM
    # =====================================================

    momentum_prices = [
        float(c["close"])
        for c in completed[-5:]
    ]

    rising = 0
    falling = 0

    for i in range(1, len(momentum_prices)):

        if momentum_prices[i] > momentum_prices[i - 1]:

            rising += 1

        elif momentum_prices[i] < momentum_prices[i - 1]:

            falling += 1

    if rising > falling:

        call_score += 2

    elif falling > rising:

        put_score += 2

    # =====================================================
    # RUNNING CANDLE
    # =====================================================

    if running_direction == "BULLISH":

        call_score += 3

    elif running_direction == "BEARISH":

        put_score += 3

    # =====================================================
    # RUNNING CANDLE STRENGTH
    # =====================================================

    if running_strength >= 50:

        if running_direction == "BULLISH":
            call_score += 2

        elif running_direction == "BEARISH":
            put_score += 2

    elif running_strength >= 20:

        if running_direction == "BULLISH":
            call_score += 1

        elif running_direction == "BEARISH":
            put_score += 1

    # =====================================================
    # CLOSE POSITION
    # =====================================================

    if running_direction == "BULLISH":

        if running_position >= 0.55:
            call_score += 1

    elif running_direction == "BEARISH":

        if running_position <= 0.45:
            put_score += 1

    # =====================================================
    # DOJI HANDLING
    # =====================================================

    if running_direction == "DOJI":

        if call_score >= put_score:
            call_score += 1
        else:
            put_score += 1

    # =====================================================
    # FINAL SCORE
    # =====================================================

    total = call_score + put_score

    if total <= 0:

        confidence = 50

    else:

        highest = max(
            call_score,
            put_score
        )

        confidence = int(
            50 + (
                (highest / total) - 0.5
            ) * 100
        )

    confidence = max(
        50,
        min(90, confidence)
    )

    # =====================================================
    # SIGNAL
    # =====================================================

    if call_score >= put_score:

        signal = "CALL / UP"

        if confidence >= 75:
            signal_level = "STRONG"

        elif confidence >= 65:
            signal_level = "GOOD"

        else:
            signal_level = "MODERATE"

    else:

        signal = "PUT / DOWN"

        if confidence >= 75:
            signal_level = "STRONG"

        elif confidence >= 65:
            signal_level = "GOOD"

        else:
            signal_level = "MODERATE"

    # =====================================================
    # TREND
    # =====================================================

    if (
        price > ema20
        and ema20 > ema50
        and ema50 > ema200
    ):

        trend = "BULLISH STRONG"

    elif (
        price < ema20
        and ema20 < ema50
        and ema50 < ema200
    ):

        trend = "BEARISH STRONG"

    elif price > ema50:

        trend = "BULLISH"

    elif price < ema50:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"

    # =====================================================
    # RESULT
    # =====================================================

    return {

        "market_open": True,

        "signal_for":
            "CURRENT RUNNING CANDLE",

        "trade_window":
            "FIRST 30 SECONDS",

        "symbol":
            symbol,

        "timeframe":
            f"{TIMEFRAMES[timeframe]} Minute",

        "running_candle_time":
            running.get("datetime"),

        "price":
            round(price, 5),

        "ema20":
            round(ema20, 5),

        "ema50":
            round(ema50, 5),

        "ema200":
            round(ema200, 5),

        "rsi14":
            round(rsi14, 2),

        "candle":
            running_direction,

        "candle_strength":
            round(running_strength, 1),

        "trend":
            trend,

        "call_score":
            call_score,

        "put_score":
            put_score,

        "difference":
            abs(
                call_score - put_score
            ),

        "signal":
            signal,

        "signal_level":
            signal_level,

        "confidence":
            confidence,

        "data_source":
            "Twelve Data",

        "market_type":
            market_type,

        "proxy":
            market_type == "otc",

        "message":
            (
                "Signal is generated for the "
                "current running candle. "
                "Direction can change while "
                "the candle is forming."
            )
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=OTC_PAIRS
    )


# =========================================================
# API
# =========================================================

@app.route("/api/market")
def market():

    market_type = request.args.get(
        "market",
        "real"
    )

    symbol = request.args.get(
        "symbol",
        "EUR/USD"
    )

    timeframe = request.args.get(
        "timeframe",
        "1"
    )

    if not API_KEY:

        return jsonify({

            "market_open": False,

            "signal": "NO SIGNAL",

            "error":
                "TWELVEDATA_API_KEY is missing."

        }), 500

    if timeframe not in TIMEFRAMES:

        return jsonify({

            "market_open": False,

            "signal": "NO SIGNAL",

            "error":
                "Invalid timeframe."

        }), 400

    # =====================================================
    # REAL
    # =====================================================

    if market_type == "real":

        if symbol not in REAL_PAIRS:

            return jsonify({

                "market_open": False,

                "signal": "NO SIGNAL",

                "error":
                    "Invalid real-market pair."

            }), 400

        if forex_weekend_closed():

            return jsonify({

                "market_open": False,

                "signal": "MARKET CLOSED",

                "symbol": symbol,

                "timeframe":
                    f"{TIMEFRAMES[timeframe]} Minute",

                "message":
                    "Real Forex market is currently closed."

            })

        data_symbol = symbol

    # =====================================================
    # OTC
    # =====================================================

    elif market_type == "otc":

        if symbol not in OTC_PAIRS:

            return jsonify({

                "market_open": False,

                "signal": "NO SIGNAL",

                "error":
                    "Invalid OTC pair."

            }), 400

        data_symbol = symbol.replace(
            " OTC",
            ""
        )

    else:

        return jsonify({

            "market_open": False,

            "signal": "NO SIGNAL",

            "error":
                "Invalid market type."

        }), 400

    # =====================================================
    # GENERATE
    # =====================================================

    try:

        minutes = TIMEFRAMES[timeframe]

        candles = get_market_candles(
            data_symbol,
            minutes
        )

        result = generate_running_signal(
            candles,
            symbol,
            timeframe,
            market_type
        )

        return jsonify(result)

    except Exception as e:

        return jsonify({

            "market_open": True,

            "signal": "NO SIGNAL",

            "signal_for":
                "CURRENT RUNNING CANDLE",

            "symbol":
                symbol,

            "timeframe":
                f"{TIMEFRAMES[timeframe]} Minute",

            "error":
                str(e)

        }), 400


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
