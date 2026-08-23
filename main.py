import os
import requests
from datetime import datetime, timezone

from flask import Flask, render_template, jsonify, request


app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


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
            ((avg_gain * (period - 1)) + gains[i])
            / period
        )

        avg_loss = (
            ((avg_loss * (period - 1)) + losses[i])
            / period
        )

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================================================
# MARKET DATA
# =========================================================

def get_market_candles(symbol, minutes):

    if minutes == 60:
        interval = "1h"

    elif minutes == 240:
        interval = "4h"

    else:
        interval = "1min"


    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": 500,
        "apikey": API_KEY
    }


    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params=params,
        timeout=15
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
        reversed(data["values"])
    )


    candles = []


    for item in raw:

        candles.append({

            "datetime": item.get("datetime"),

            "open": float(item["open"]),

            "high": float(item["high"]),

            "low": float(item["low"]),

            "close": float(item["close"])
        })


    return candles


# =========================================================
# CANDLE INFORMATION
# =========================================================

def candle_info(candle):

    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])


    candle_range = high - low

    body = abs(close - open_price)


    if candle_range > 0:
        body_ratio = body / candle_range
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
            (close - low) / candle_range
        )

    else:

        close_position = 0.5


    return {

        "direction": direction,

        "body_ratio": body_ratio,

        "range": candle_range,

        "close_position": close_position
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
    # RUNNING CANDLE
    # =====================================================

    running = candles[-1]


    # Previous completed candles

    previous = candles[-2]

    previous2 = candles[-3]

    previous3 = candles[-4]


    # =====================================================
    # PRICE
    # =====================================================

    price = float(
        running["close"]
    )


    # =====================================================
    # HISTORICAL CLOSES
    #
    # Running price is included.
    # =====================================================

    closes = [
        float(c["close"])
        for c in candles[-250:]
    ]


    # =====================================================
    # INDICATORS
    # =====================================================

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    rsi14 = calculate_rsi(
        closes,
        14
    )


    if (
        ema50 is None
        or ema200 is None
        or rsi14 is None
    ):

        raise Exception(
            "Indicator calculation failed."
        )


    # =====================================================
    # CANDLE DATA
    # =====================================================

    running_info = candle_info(
        running
    )

    previous_info = candle_info(
        previous
    )

    previous2_info = candle_info(
        previous2
    )

    previous3_info = candle_info(
        previous3
    )


    running_direction = (
        running_info["direction"]
    )

    previous_direction = (
        previous_info["direction"]
    )

    previous2_direction = (
        previous2_info["direction"]
    )

    previous3_direction = (
        previous3_info["direction"]
    )


    # =====================================================
    # SCORES
    # =====================================================

    call_score = 0
    put_score = 0


    # =====================================================
    # 1. PRICE VS EMA50
    # =====================================================

    if price > ema50:
        call_score += 2

    elif price < ema50:
        put_score += 2


    # =====================================================
    # 2. EMA TREND
    # =====================================================

    if ema50 > ema200:
        call_score += 2

    elif ema50 < ema200:
        put_score += 2


    # =====================================================
    # 3. RSI
    # =====================================================

    if rsi14 >= 55:
        call_score += 2

    elif rsi14 <= 45:
        put_score += 2

    elif rsi14 > 50:
        call_score += 1

    elif rsi14 < 50:
        put_score += 1


    # =====================================================
    # 4. RUNNING CANDLE DIRECTION
    # =====================================================

    if running_direction == "BULLISH":
        call_score += 2

    elif running_direction == "BEARISH":
        put_score += 2


    # =====================================================
    # 5. RUNNING CANDLE BODY
    # =====================================================

    body_strength = (
        running_info["body_ratio"] * 100
    )


    if body_strength >= 40:

        if running_direction == "BULLISH":
            call_score += 2

        elif running_direction == "BEARISH":
            put_score += 2


    elif body_strength >= 20:

        if running_direction == "BULLISH":
            call_score += 1

        elif running_direction == "BEARISH":
            put_score += 1


    # =====================================================
    # 6. RUNNING CANDLE CLOSE POSITION
    # =====================================================

    close_position = (
        running_info["close_position"]
    )


    if close_position >= 0.75:

        call_score += 1

    elif close_position <= 0.25:

        put_score += 1


    # =====================================================
    # 7. MOMENTUM
    # =====================================================

    bullish_count = 0
    bearish_count = 0


    for direction in [
        running_direction,
        previous_direction,
        previous2_direction,
        previous3_direction
    ]:

        if direction == "BULLISH":
            bullish_count += 1

        elif direction == "BEARISH":
            bearish_count += 1


    if bullish_count >= 3:
        call_score += 2

    elif bearish_count >= 3:
        put_score += 2


    # =====================================================
    # 8. PRICE MOMENTUM
    # =====================================================

    price_now = float(
        candles[-1]["close"]
    )

    price_1 = float(
        candles[-2]["close"]
    )

    price_2 = float(
        candles[-3]["close"]
    )

    price_3 = float(
        candles[-4]["close"]
    )


    if (
        price_now > price_1
        and price_1 > price_2
        and price_2 > price_3
    ):

        call_score += 2


    elif (
        price_now < price_1
        and price_1 < price_2
        and price_2 < price_3
    ):

        put_score += 2


    # =====================================================
    # 9. EMA MOMENTUM
    # =====================================================

    ema50_previous = calculate_ema(
        closes[:-1],
        50
    )


    if ema50_previous is not None:

        if ema50 > ema50_previous:

            call_score += 1

        elif ema50 < ema50_previous:

            put_score += 1


    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    signal = "NO TRADE"


    difference = abs(
        call_score - put_score
    )


    # Stronger threshold for running candle

    if (
        call_score >= 9
        and call_score > put_score
        and difference >= 3
    ):

        signal = "CALL / UP"


    elif (
        put_score >= 9
        and put_score > call_score
        and difference >= 3
    ):

        signal = "PUT / DOWN"


    # =====================================================
    # CONFIDENCE
    # =====================================================

    maximum_possible = 17

    highest_score = max(
        call_score,
        put_score
    )


    confidence = int(
        (
            highest_score
            / maximum_possible
        ) * 100
    )


    confidence = max(
        50,
        min(confidence, 95)
    )


    # Don't show high confidence
    # when direction is actually weak

    if signal == "NO TRADE":

        confidence = 50


    # =====================================================
    # TREND
    # =====================================================

    if (
        price > ema50
        and ema50 > ema200
    ):

        trend = "BULLISH STRONG"


    elif (
        price < ema50
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
    # SIGNAL STRENGTH
    # =====================================================

    if signal == "CALL / UP":

        strength = "STRONG CALL"

    elif signal == "PUT / DOWN":

        strength = "STRONG PUT"

    else:

        strength = "WEAK / WAIT"


    # =====================================================
    # RESULT
    # =====================================================

    result = {

        "market_open": True,

        "signal_for": "RUNNING CANDLE",

        "symbol": symbol,

        "timeframe":
            f"{TIMEFRAMES[timeframe]} Minute",

        "running_candle":
            running.get("datetime"),

        "price":
            round(price, 5),

        "ema50":
            round(ema50, 5),

        "ema200":
            round(ema200, 5),

        "rsi14":
            round(rsi14, 2),

        "candle":
            running_direction,

        "previous_candle":
            previous_direction,

        "candle_strength":
            round(body_strength, 1),

        "close_position":
            round(close_position * 100, 1),

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

        "strength":
            strength,

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
                "The current candle is still forming, "
                "so the signal can change before the candle closes."
            )
    }


    if market_type == "otc":

        result["warning"] = (
            "OTC warning: Twelve Data does not provide "
            "the actual Quotex OTC feed. This signal uses "
            "the corresponding market symbol as proxy data."
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

            "market_open": False,

            "signal": "NO SIGNAL",

            "error":
                "TWELVEDATA_API_KEY is missing."
        }), 500


    # =====================================================
    # TIMEFRAME
    # =====================================================

    if timeframe not in TIMEFRAMES:

        return jsonify({

            "market_open": False,

            "signal": "NO SIGNAL",

            "error":
                "Invalid timeframe."
        }), 400


    # =====================================================
    # REAL MARKET
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
    # GENERATE RUNNING SIGNAL
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


        return jsonify(result)


    except Exception as e:

        return jsonify({

            "market_open": True,

            "signal": "NO SIGNAL",

            "signal_for":
                "RUNNING CANDLE",

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
