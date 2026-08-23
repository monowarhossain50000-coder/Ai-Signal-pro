import os
import time
import requests

from datetime import datetime, timezone
from threading import Lock

from flask import Flask, render_template, jsonify, request


app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


# =========================================================
# SETTINGS
# =========================================================

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
# FOREX MARKET STATUS
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

        change = prices[i] - prices[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# MARKET DATA
# =========================================================

def get_market_candles(symbol, minutes):

    global last_api_request

    cache_key = (
        symbol,
        minutes
    )

    now = time.time()

    # =====================================================
    # CACHE
    # =====================================================

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

    # =====================================================
    # API RATE LIMIT
    # =====================================================

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

            wait_time = (
                API_MIN_GAP
                - elapsed
            )

            time.sleep(
                wait_time
            )

        last_api_request = time.time()

    # =====================================================
    # INTERVAL
    # =====================================================

    if minutes == 60:

        interval = "1h"

    elif minutes == 240:

        interval = "4h"

    else:

        interval = "1min"

    # =====================================================
    # REQUEST
    # =====================================================

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

    # =====================================================
    # RATE LIMIT ERROR
    # =====================================================

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

    # =====================================================
    # BUILD CANDLES
    # =====================================================

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
            len(raw) - minutes + 1,
            minutes
        ):

            group = raw[
                i:i + minutes
            ]

            candles.append({

                "datetime":
                    group[0].get(
                        "datetime"
                    ),

                "open":
                    float(
                        group[0]["open"]
                    ),

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
                    float(
                        group[-1]["close"]
                    )
            })

    # =====================================================
    # CACHE
    # =====================================================

    with cache_lock:

        market_cache[
            cache_key
        ] = {

            "time":
                time.time(),

            "data":
                candles
        }

    return candles


# =========================================================
# CANDLE INFORMATION
# =========================================================

def candle_info(candle):

    open_price = float(
        candle["open"]
    )

    high = float(
        candle["high"]
    )

    low = float(
        candle["low"]
    )

    close = float(
        candle["close"]
    )

    candle_range = (
        high - low
    )

    body = abs(
        close - open_price
    )

    if candle_range > 0:

        body_ratio = (
            body
            / candle_range
        )

    else:

        body_ratio = 0

    if close > open_price:

        direction = "BULLISH"

    elif close < open_price:

        direction = "BEARISH"

    else:

        direction = "DOJI"

    if candle_range > 0:

        close_position = (
            (close - low)
            / candle_range
        )

    else:

        close_position = 0.5

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

    # =====================================================
    # IMPORTANT
    # CURRENT LAST CANDLE = RUNNING CANDLE
    # PREVIOUS CANDLES = COMPLETED
    # =====================================================

    running = candles[-1]

    completed = candles[:-1]

    if len(completed) < 210:

        raise Exception(
            "Not enough completed candles."
        )

    # =====================================================
    # COMPLETED CANDLES
    # =====================================================

    c1 = completed[-1]
    c2 = completed[-2]
    c3 = completed[-3]
    c4 = completed[-4]
    c5 = completed[-5]
    c6 = completed[-6]

    # =====================================================
    # COMPLETED CLOSES
    # =====================================================

    completed_closes = [

        float(c["close"])

        for c in completed[-250:]

    ]

    # =====================================================
    # EMA
    # =====================================================

    ema20 = calculate_ema(
        completed_closes,
        20
    )

    ema50 = calculate_ema(
        completed_closes,
        50
    )

    ema200 = calculate_ema(
        completed_closes,
        200
    )

    rsi14 = calculate_rsi(
        completed_closes,
        14
    )

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

    running_info = candle_info(
        running
    )

    running_direction = (
        running_info["direction"]
    )

    running_strength = (
        running_info["body_ratio"]
        * 100
    )

    running_price = float(
        running["close"]
    )

    # =====================================================
    # COMPLETED CANDLE DIRECTIONS
    # =====================================================

    info1 = candle_info(c1)
    info2 = candle_info(c2)
    info3 = candle_info(c3)
    info4 = candle_info(c4)
    info5 = candle_info(c5)
    info6 = candle_info(c6)

    directions = [

        info1["direction"],
        info2["direction"],
        info3["direction"],
        info4["direction"],
        info5["direction"],
        info6["direction"]

    ]

    # =====================================================
    # SCORE
    # =====================================================

    call_score = 0
    put_score = 0

    # =====================================================
    # EMA STRUCTURE
    # =====================================================

    if ema20 > ema50:

        call_score += 2

    elif ema20 < ema50:

        put_score += 2

    if ema50 > ema200:

        call_score += 2

    elif ema50 < ema200:

        put_score += 2

    # Strong alignment

    if (
        ema20 > ema50
        and ema50 > ema200
    ):

        call_score += 2

    elif (
        ema20 < ema50
        and ema50 < ema200
    ):

        put_score += 2

    # =====================================================
    # RUNNING PRICE VS EMA
    # =====================================================

    if running_price > ema20:

        call_score += 1

    elif running_price < ema20:

        put_score += 1

    if running_price > ema50:

        call_score += 2

    elif running_price < ema50:

        put_score += 2

    if running_price > ema200:

        call_score += 1

    elif running_price < ema200:

        put_score += 1

    # =====================================================
    # RSI
    # =====================================================

    # Neutral zone deliberately gives NO advantage.

    if rsi14 >= 60:

        call_score += 3

    elif rsi14 >= 55:

        call_score += 2

    elif rsi14 > 52:

        call_score += 1

    elif rsi14 <= 40:

        put_score += 3

    elif rsi14 <= 45:

        put_score += 2

    elif rsi14 < 48:

        put_score += 1

    # =====================================================
    # COMPLETED CANDLE MOMENTUM
    # =====================================================

    bullish = directions.count(
        "BULLISH"
    )

    bearish = directions.count(
        "BEARISH"
    )

    if bullish >= 5:

        call_score += 3

    elif bullish >= 4:

        call_score += 2

    elif bullish >= 3:

        call_score += 1

    if bearish >= 5:

        put_score += 3

    elif bearish >= 4:

        put_score += 2

    elif bearish >= 3:

        put_score += 1

    # =====================================================
    # LAST COMPLETED CANDLE
    # =====================================================

    if info1["direction"] == "BULLISH":

        call_score += 2

    elif info1["direction"] == "BEARISH":

        put_score += 2

    # =====================================================
    # RUNNING CANDLE DIRECTION
    # =====================================================

    if running_direction == "BULLISH":

        call_score += 2

    elif running_direction == "BEARISH":

        put_score += 2

    # =====================================================
    # RUNNING CANDLE STRENGTH
    # =====================================================

    if running_strength >= 70:

        if running_direction == "BULLISH":

            call_score += 3

        elif running_direction == "BEARISH":

            put_score += 3

    elif running_strength >= 45:

        if running_direction == "BULLISH":

            call_score += 2

        elif running_direction == "BEARISH":

            put_score += 2

    elif running_strength >= 25:

        if running_direction == "BULLISH":

            call_score += 1

        elif running_direction == "BEARISH":

            put_score += 1

    # =====================================================
    # PRICE MOMENTUM
    # =====================================================

    p1 = float(
        completed[-1]["close"]
    )

    p2 = float(
        completed[-2]["close"]
    )

    p3 = float(
        completed[-3]["close"]
    )

    p4 = float(
        completed[-4]["close"]
    )

    p5 = float(
        completed[-5]["close"]
    )

    rising = 0
    falling = 0

    comparisons = [

        (p1, p2),
        (p2, p3),
        (p3, p4),
        (p4, p5)

    ]

    for a, b in comparisons:

        if a > b:
            rising += 1

        elif a < b:
            falling += 1

    if rising >= 3:

        call_score += 2

    elif rising >= 2:

        call_score += 1

    if falling >= 3:

        put_score += 2

    elif falling >= 2:

        put_score += 1

    # =====================================================
    # RUNNING CANDLE POSITION
    # =====================================================

    close_position = (
        running_info["close_position"]
    )

    if (
        running_direction == "BULLISH"
        and close_position >= 0.70
    ):

        call_score += 2

    elif (
        running_direction == "BEARISH"
        and close_position <= 0.30
    ):

        put_score += 2

    # =====================================================
    # DOJI PROTECTION
    # =====================================================

    if running_direction == "DOJI":

        call_score = max(
            0,
            call_score - 2
        )

        put_score = max(
            0,
            put_score - 2
        )

    # =====================================================
    # FINAL SCORE
    # =====================================================

    highest = max(
        call_score,
        put_score
    )

    lowest = min(
        call_score,
        put_score
    )

    difference = abs(
        call_score
        - put_score
    )

    # =====================================================
    # REALISTIC CONFIDENCE
    # =====================================================

    if highest == 0:

        confidence = 0

    else:

        total = (
            call_score
            + put_score
        )

        if total > 0:

            ratio = (
                highest
                / total
            )

        else:

            ratio = 0.5

        confidence = int(
            50
            + (
                ratio - 0.5
            ) * 70
        )

        # Running candle must have
        # meaningful confirmation.

        if running_strength < 20:

            confidence -= 12

        elif running_strength < 35:

            confidence -= 6

        # RSI neutral protection.

        if 48 <= rsi14 <= 52:

            confidence -= 10

        elif 47 <= rsi14 <= 53:

            confidence -= 5

        # EMA distance protection.

        ema_distance = abs(
            ema50 - ema200
        )

        if ema200 != 0:

            ema_gap_percent = (
                ema_distance
                / abs(ema200)
            ) * 100

            if ema_gap_percent < 0.005:

                confidence -= 5

        # Difference bonus, capped.

        confidence += min(
            10,
            difference
        )

        confidence = max(
            0,
            min(
                90,
                confidence
            )
        )

    # =====================================================
    # SIGNAL
    # =====================================================

    signal = "NO TRADE"

    signal_level = "NO TRADE"

    # Need meaningful direction.
    # 65% is the minimum signal threshold.

    if (
        call_score > put_score
        and difference >= 3
        and confidence >= 65
    ):

        signal = "CALL / UP"

        if confidence >= 80:

            signal_level = "STRONG"

        elif confidence >= 72:

            signal_level = "GOOD"

        else:

            signal_level = "MODERATE"

    elif (
        put_score > call_score
        and difference >= 3
        and confidence >= 65
    ):

        signal = "PUT / DOWN"

        if confidence >= 80:

            signal_level = "STRONG"

        elif confidence >= 72:

            signal_level = "GOOD"

        else:

            signal_level = "MODERATE"

    # =====================================================
    # TREND
    # =====================================================

    if (
        running_price > ema20
        and ema20 > ema50
        and ema50 > ema200
    ):

        trend = "BULLISH STRONG"

    elif (
        running_price < ema20
        and ema20 < ema50
        and ema50 < ema200
    ):

        trend = "BEARISH STRONG"

    elif running_price > ema50:

        trend = "BULLISH"

    elif running_price < ema50:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"

    # =====================================================
    # RESULT
    # =====================================================

    result = {

        "market_open":
            True,

        "signal_for":
            "CURRENT RUNNING CANDLE",

        "trade_window":
            "FIRST 30 SECONDS",

        "symbol":
            symbol,

        "timeframe":
            f"{TIMEFRAMES[timeframe]} Minute",

        "running_candle_time":
            running.get(
                "datetime"
            ),

        "price":
            round(
                running_price,
                5
            ),

        "ema20":
            round(
                ema20,
                5
            ),

        "ema50":
            round(
                ema50,
                5
            ),

        "ema200":
            round(
                ema200,
                5
            ),

        "rsi14":
            round(
                rsi14,
                2
            ),

        "candle":
            running_direction,

        "previous_candle":
            info1["direction"],

        "candle_strength":
            round(
                running_strength,
                1
            ),

        "trend":
            trend,

        "call_score":
            call_score,

        "put_score":
            put_score,

        "difference":
            difference,

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
                "Running-candle signal. "
                "Use during the first 30 seconds "
                "of the current candle. "
                "Signal can change while the candle forms."
            )
    }

    # =====================================================
    # OTC WARNING
    # =====================================================

    if market_type == "otc":

        result["warning"] = (
            "OTC uses proxy market data. "
            "It is not the direct Quotex OTC feed."
        )

    return result


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

    # =====================================================
    # API KEY
    # =====================================================

    if not API_KEY:

        return jsonify({

            "market_open":
                False,

            "signal":
                "NO SIGNAL",

            "error":
                "TWELVEDATA_API_KEY is missing."

        }), 500

    # =====================================================
    # TIMEFRAME
    # =====================================================

    if timeframe not in TIMEFRAMES:

        return jsonify({

            "market_open":
                False,

            "signal":
                "NO SIGNAL",

            "error":
                "Invalid timeframe."

        }), 400

    # =====================================================
    # REAL MARKET
    # =====================================================

    if market_type == "real":

        if symbol not in REAL_PAIRS:

            return jsonify({

                "market_open":
                    False,

                "signal":
                    "NO SIGNAL",

                "error":
                    "Invalid real-market pair."

            }), 400

        if forex_weekend_closed():

            return jsonify({

                "market_open":
                    False,

                "signal":
                    "MARKET CLOSED",

                "symbol":
                    symbol,

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

                "market_open":
                    False,

                "signal":
                    "NO SIGNAL",

                "error":
                    "Invalid OTC pair."

            }), 400

        data_symbol = symbol.replace(
            " OTC",
            ""
        )

    else:

        return jsonify({

            "market_open":
                False,

            "signal":
                "NO SIGNAL",

            "error":
                "Invalid market type."

        }), 400

    # =====================================================
    # SIGNAL
    # =====================================================

    try:

        minutes = TIMEFRAMES[
            timeframe
        ]

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

        return jsonify(
            result
        )

    except Exception as e:

        return jsonify({

            "market_open":
                True,

            "signal":
                "NO SIGNAL",

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
