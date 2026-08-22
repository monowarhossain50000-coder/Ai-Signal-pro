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
    "EUR/CAD", "EUR/NZD",

    "GBP/JPY", "GBP/CHF", "GBP/AUD",
    "GBP/CAD", "GBP/NZD",

    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY",

    "AUD/CAD", "AUD/CHF", "AUD/NZD",
    "CAD/CHF", "NZD/CAD", "NZD/CHF",

    "USD/SGD", "USD/HKD", "USD/SEK",
    "USD/NOK", "USD/DKK", "USD/ZAR", "USD/TRY"
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


def forex_weekend_closed():
    """
    Forex is normally closed from Friday evening
    until Sunday evening, depending on the provider's
    timezone/session.
    """

    now = datetime.now(timezone.utc)

    # Saturday
    if now.weekday() == 5:
        return True

    # Sunday before 21:00 UTC
    if now.weekday() == 6 and now.hour < 21:
        return True

    # Friday after 21:00 UTC
    if now.weekday() == 4 and now.hour >= 21:
        return True

    return False


def calculate_ema(prices, period=50):

    if len(prices) < period:
        return None

    value = sum(prices[:period]) / period

    multiplier = 2 / (period + 1)

    for price in prices[period:]:

        value = (
            (price - value)
            * multiplier
            + value
        )

    return value


def calculate_rsi(prices, period=14):

    if len(prices) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(prices)):

        change = prices[i] - prices[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


@app.route("/")
def home():

    return render_template(
        "index.html",
        pairs=REAL_PAIRS
    )


@app.route("/api/market")
def market():

    if not API_KEY:

        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "API key is missing"
        }), 500

    symbol = request.args.get(
        "symbol",
        "EUR/USD"
    )

    timeframe = request.args.get(
        "timeframe",
        "1"
    )

    if symbol not in REAL_PAIRS:

        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "Invalid pair"
        }), 400

    if timeframe not in TIMEFRAMES:

        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "Invalid timeframe"
        }), 400

    # ------------------------------------------------
    # IMPORTANT:
    # Do not generate a Real Market signal on weekends.
    # ------------------------------------------------

    if forex_weekend_closed():

        return jsonify({

            "market_open": False,

            "symbol": symbol,

            "timeframe": f"{TIMEFRAMES[timeframe]} Minute",

            "signal": "MARKET CLOSED",

            "message": (
                "Real Forex market is currently closed. "
                "No signal generated."
            )

        })


    minutes = TIMEFRAMES[timeframe]


    # ------------------------------------------------
    # Native Twelve Data intervals
    # ------------------------------------------------

    if minutes in [1, 5, 15, 30, 60, 240]:

        if minutes == 60:
            interval = "1h"

        elif minutes == 240:
            interval = "4h"

        else:
            interval = f"{minutes}min"

        params = {

            "symbol": symbol,

            "interval": interval,

            "outputsize": 100,

            "apikey": API_KEY
        }

        try:

            response = requests.get(

                "https://api.twelvedata.com/time_series",

                params=params,

                timeout=15
            )

            data = response.json()

            if "values" not in data:

                return jsonify({

                    "market_open": True,

                    "signal": "NO SIGNAL",

                    "error": data.get(

                        "message",

                        "Market data unavailable"
                    )

                }), 400

            candles = list(

                reversed(
                    data["values"]
                )
            )

        except Exception as e:

            return jsonify({

                "market_open": True,

                "signal": "NO SIGNAL",

                "error": str(e)

            }), 500


    # ------------------------------------------------
    # Build 2-minute / 3-minute candles from 1-minute
    # ------------------------------------------------

    else:

        params = {

            "symbol": symbol,

            "interval": "1min",

            "outputsize": 300,

            "apikey": API_KEY
        }

        try:

            response = requests.get(

                "https://api.twelvedata.com/time_series",

                params=params,

                timeout=15
            )

            data = response.json()

            if "values" not in data:

                return jsonify({

                    "market_open": True,

                    "signal": "NO SIGNAL",

                    "error": data.get(

                        "message",

                        "Market data unavailable"
                    )

                }), 400

            raw = list(

                reversed(
                    data["values"]
                )
            )

            candles = []

            step = minutes

            for i in range(

                0,

                len(raw) - step + 1,

                step

            ):

                group = raw[
                    i:i + step
                ]

                candles.append({

                    "open":
                        group[0]["open"],

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
                        group[-1]["close"]

                })

        except Exception as e:

            return jsonify({

                "market_open": True,

                "signal": "NO SIGNAL",

                "error": str(e)

            }), 500


    if len(candles) < 60:

        return jsonify({

            "market_open": True,

            "signal": "NO SIGNAL",

            "error":
                "Not enough candle data"

        }), 400


    closes = [

        float(x["close"])

        for x in candles

    ]


    current = candles[-1]

    price = float(
        current["close"]
    )

    open_price = float(
        current["open"]
    )


    ema50 = calculate_ema(
        closes,
        50
    )

    rsi14 = calculate_rsi(
        closes,
        14
    )


    if ema50 is None or rsi14 is None:

        return jsonify({

            "market_open": True,

            "signal": "NO SIGNAL",

            "error":
                "Not enough data for indicators"

        }), 400


    if price > open_price:

        candle = "BULLISH"

    elif price < open_price:

        candle = "BEARISH"

    else:

        candle = "DOJI"


    if price > ema50:

        trend = "ABOVE EMA"

    elif price < ema50:

        trend = "BELOW EMA"

    else:

        trend = "AT EMA"


    call_score = 0

    put_score = 0


    if price > ema50:

        call_score += 1

    elif price < ema50:

        put_score += 1


    if rsi14 > 50:

        call_score += 1

    elif rsi14 < 50:

        put_score += 1


    if candle == "BULLISH":

        call_score += 1

    elif candle == "BEARISH":

        put_score += 1


    if call_score == 3:

        signal = "CALL / UP"

    elif put_score == 3:

        signal = "PUT / DOWN"

    else:

        signal = "WAIT"


    score = max(
        call_score,
        put_score
    )

    confidence = int(
        (score / 3) * 100
    )


    return jsonify({

        "market_open": True,

        "symbol": symbol,

        "timeframe":
            f"{minutes} Minute",

        "price":
            round(price, 5),

        "ema50":
            round(ema50, 5),

        "rsi14":
            round(rsi14, 2),

        "candle":
            candle,

        "trend":
            trend,

        "signal":
            signal,

        "confidence":
            confidence

    })


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
