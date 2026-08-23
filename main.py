import os
import requests
from datetime import datetime, timezone

from flask import Flask, render_template, jsonify, request


app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


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

        if change > 0:
            gains.append(change)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(change))

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


    # -----------------------------------------------------
    # Convert 1-minute candles into 2/3/5/10/15/30 minute
    # candles.
    # -----------------------------------------------------

    if minutes not in [1, 60, 240]:

        candles = []

        for i in range(
            0,
            len(raw) - minutes + 1,
            minutes
        ):

            group = raw[
                i:i + minutes
            ]

            candles.append({

                "open": float(
                    group[0]["open"]
                ),

                "high": max(
                    float(x["high"])
                    for x in group
                ),

                "low": min(
                    float(x["low"])
                    for x in group
                ),

                "close": float(
                    group[-1]["close"]
                )
            })

    else:

        candles = []

        for item in raw:

            candles.append({

                "open": float(
                    item["open"]
                ),

                "high": float(
                    item["high"]
                ),

                "low": float(
                    item["low"]
                ),

                "close": float(
                    item["close"]
                )
            })


    return candles


# =========================================================
# CANDLE ANALYSIS
# =========================================================

def candle_information(candle):

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


    total_range = high - low

    body = abs(
        close - open_price
    )


    if total_range == 0:

        body_ratio = 0

    else:

        body_ratio = body / total_range


    if close > open_price:

        direction = "BULLISH"

    elif close < open_price:

        direction = "BEARISH"

    else:

        direction = "DOJI"


    return {
        "direction": direction,
        "body": body,
        "range": total_range,
        "body_ratio": body_ratio
    }


# =========================================================
# SIGNAL ENGINE
# =========================================================

def generate_signal(
    candles,
    symbol,
    timeframe,
    market_type
):

    if len(candles) < 220:

        raise Exception(
            "Not enough candle data."
        )


    closes = [
        float(c["close"])
        for c in candles
    ]


    current = candles[-1]

    previous = candles[-2]


    price = float(
        current["close"]
    )


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


    current_info = candle_information(
        current
    )

    previous_info = candle_information(
        previous
    )


    current_direction = (
        current_info["direction"]
    )

    previous_direction = (
        previous_info["direction"]
    )


    # =====================================================
    # TREND
    # =====================================================

    if (
        price > ema50
        and ema50 > ema200
    ):

        trend = "STRONG BULLISH"

    elif (
        price < ema50
        and ema50 < ema200
    ):

        trend = "STRONG BEARISH"

    elif price > ema50:

        trend = "BULLISH / WEAK"

    elif price < ema50:

        trend = "BEARISH / WEAK"

    else:

        trend = "SIDEWAYS"


    # =====================================================
    # EMA DISTANCE FILTER
    # =====================================================

    if price != 0:

        ema_distance = (
            abs(price - ema50)
            / price
        ) * 100

    else:

        ema_distance = 0


    # Avoid entries when price is too close to EMA50.
    ema_filter = ema_distance >= 0.01


    # =====================================================
    # CANDLE STRENGTH
    # =====================================================

    strong_current = (
        current_info["body_ratio"]
        >= 0.45
    )


    strong_previous = (
        previous_info["body_ratio"]
        >= 0.35
    )


    # =====================================================
    # SCORE
    # =====================================================

    call_score = 0
    put_score = 0


    # Trend confirmation

    if (
        price > ema50
        and ema50 > ema200
    ):

        call_score += 2


    if (
        price < ema50
        and ema50 < ema200
    ):

        put_score += 2


    # RSI confirmation

    if rsi14 >= 52:

        call_score += 1

    elif rsi14 <= 48:

        put_score += 1


    # Current candle

    if current_direction == "BULLISH":

        call_score += 1

    elif current_direction == "BEARISH":

        put_score += 1


    # Previous candle confirmation

    if (
        previous_direction == "BULLISH"
        and strong_previous
    ):

        call_score += 1


    elif (
        previous_direction == "BEARISH"
        and strong_previous
    ):

        put_score += 1


    # Current candle strength

    if (
        current_direction == "BULLISH"
        and strong_current
    ):

        call_score += 1


    elif (
        current_direction == "BEARISH"
        and strong_current
    ):

        put_score += 1


    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    signal = "WAIT"


    # Need strong trend + enough confirmations

    if (
        call_score >= 5
        and call_score > put_score
        and ema_filter
        and rsi14 >= 52
        and current_direction == "BULLISH"
    ):

        signal = "CALL / UP"


    elif (
        put_score >= 5
        and put_score > call_score
        and ema_filter
        and rsi14 <= 48
        and current_direction == "BEARISH"
    ):

        signal = "PUT / DOWN"


    # =====================================================
    # CONFIDENCE
    # =====================================================

    maximum_score = 7

    raw_score = max(
        call_score,
        put_score
    )


    confidence = int(
        min(
            raw_score
            / maximum_score
            * 100,
            95
        )
    )


    # WAIT should never show high confidence.

    if signal == "WAIT":

        confidence = min(
            confidence,
            55
        )


    # =====================================================
    # MARKET RESULT
    # =====================================================

    result = {

        "market_open": True,

        "symbol": symbol,

        "timeframe":
            f"{TIMEFRAMES[timeframe]} Minute",

        "price":
            round(price, 5),

        "ema50":
            round(ema50, 5),

        "ema200":
            round(ema200, 5),

        "rsi14":
            round(rsi14, 2),

        "candle":
            current_direction,

        "previous_candle":
            previous_direction,

        "candle_strength":
            round(
                current_info["body_ratio"]
                * 100,
                1
            ),

        "ema_distance":
            round(
                ema_distance,
                4
            ),

        "trend":
            trend,

        "call_score":
            call_score,

        "put_score":
            put_score,

        "signal":
            signal,

        "confidence":
            confidence,

        "data_source":
            "Twelve Data",

        "market_type":
            market_type
    }


    # =====================================================
    # OTC WARNING
    # =====================================================

    if market_type == "otc":

        result["proxy"] = True

        result["message"] = (
            "OTC signal is based on proxy "
            "real-market data. It is not "
            "direct Quotex OTC candle data."
        )

    else:

        result["proxy"] = False

        result["message"] = (
            "Signal generated from "
            "Twelve Data real-market candles."
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


    if not API_KEY:

        return jsonify({

            "market_open": False,

            "signal":
                "NO SIGNAL",

            "error":
                "TWELVEDATA_API_KEY is missing."
        }), 500


    if timeframe not in TIMEFRAMES:

        return jsonify({

            "market_open": False,

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

                "market_open": False,

                "signal":
                    "NO SIGNAL",

                "error":
                    "Invalid real-market pair."
            }), 400


        if forex_weekend_closed():

            return jsonify({

                "market_open": False,

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

                "market_open": False,

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

            "market_open": False,

            "signal":
                "NO SIGNAL",

            "error":
                "Invalid market type."
        }), 400


    # =====================================================
    # GET DATA + GENERATE SIGNAL
    # =====================================================

    try:

        minutes = TIMEFRAMES[
            timeframe
        ]


        candles = get_market_candles(
            data_symbol,
            minutes
        )


        result = generate_signal(
            candles,
            symbol,
            timeframe,
            market_type
        )


        return jsonify(result)


    except Exception as e:

        return jsonify({

            "market_open": True,

            "signal":
                "NO SIGNAL",

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
