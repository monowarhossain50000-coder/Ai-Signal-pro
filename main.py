import os
import requests
from datetime import datetime, timezone

from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")

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
    "EUR/CHF",
    "EUR/AUD",
    "EUR/CAD",
    "EUR/NZD",
    "GBP/JPY",
    "GBP/CHF",
    "GBP/AUD",
    "GBP/CAD",
    "GBP/NZD",
    "AUD/JPY",
    "AUD/CHF",
    "AUD/CAD",
    "AUD/NZD",
    "CAD/JPY",
    "CAD/CHF",
    "CHF/JPY",
    "NZD/JPY",
    "NZD/CAD",
    "NZD/CHF",
    "USD/SGD",
    "USD/HKD",
    "USD/SEK",
    "USD/NOK",
    "USD/DKK",
    "USD/ZAR",
    "USD/TRY"
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
    "EUR/CHF OTC",
    "EUR/AUD OTC",
    "EUR/CAD OTC",
    "EUR/NZD OTC",
    "GBP/JPY OTC",
    "GBP/CHF OTC",
    "GBP/AUD OTC",
    "GBP/CAD OTC",
    "GBP/NZD OTC",
    "AUD/JPY OTC",
    "AUD/CHF OTC",
    "AUD/CAD OTC",
    "AUD/NZD OTC",
    "CAD/JPY OTC",
    "CAD/CHF OTC",
    "CHF/JPY OTC",
    "NZD/JPY OTC",
    "NZD/CAD OTC",
    "NZD/CHF OTC",
    "USD/INR OTC",
    "USD/PKR OTC",
    "USD/MXN OTC",
    "USD/COP OTC",
    "USD/EGP OTC",
    "USD/IDR OTC",
    "USD/NGN OTC",
    "USD/PHP OTC",
    "USD/ZAR OTC",
    "USD/TRY OTC",
    "USD/ARS OTC",
    "USD/BRL OTC",
    "XAU/USD OTC",
    "XAG/USD OTC",
    "BTC/USD OTC",
    "ETH/USD OTC",
    "BCH/USD OTC",
    "BNB/USD OTC",
    "XRP/USD OTC",
    "LTC/USD OTC",
    "ADA/USD OTC",
    "DOGE/USD OTC",
    "SOL/USD OTC"
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


def forex_market_closed():
    """
    Forex market is generally closed from Friday evening
    until Sunday evening UTC.
    """

    now = datetime.now(timezone.utc)

    # Saturday
    if now.weekday() == 5:
        return True

    # Sunday before approximately 21:00 UTC
    if now.weekday() == 6 and now.hour < 21:
        return True

    # Friday after approximately 21:00 UTC
    if now.weekday() == 4 and now.hour >= 21:
        return True

    return False


def calculate_ema(prices, period=50):
    if len(prices) < period:
        return None

    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)

    for price in prices[period:]:
        ema = ((price - ema) * multiplier) + ema

    return ema


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
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


@app.route("/")
def home():
    return render_template(
        "index.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=OTC_PAIRS,
        timeframes=TIMEFRAMES
    )


@app.route("/api/market")
def market():

    market_type = request.args.get("market", "real")
    symbol = request.args.get("symbol", "EUR/USD")
    timeframe = request.args.get("timeframe", "1")

    # ==================================================
    # OTC MARKET
    # ==================================================

    if market_type == "otc":

        if symbol not in OTC_PAIRS:
            return jsonify({
                "market_open": False,
                "signal": "NO SIGNAL",
                "error": "Invalid OTC pair."
            }), 400

        return jsonify({
            "market_open": True,
            "otc_available": False,
            "signal": "OTC DATA UNAVAILABLE",
            "symbol": symbol,
            "timeframe": f"{TIMEFRAMES.get(timeframe, 1)} Minute",
            "message": (
                "This pair is listed as OTC, but live Quotex OTC "
                "candle data is not connected."
            )
        })

    # ==================================================
    # REAL MARKET VALIDATION
    # ==================================================

    if symbol not in REAL_PAIRS:
        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "Invalid real-market pair."
        }), 400

    if timeframe not in TIMEFRAMES:
        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "Invalid timeframe."
        }), 400

    if not API_KEY:
        return jsonify({
            "market_open": False,
            "signal": "NO SIGNAL",
            "error": "TWELVEDATA_API_KEY is not configured in Render."
        }), 500

    # ==================================================
    # REAL FOREX MARKET CLOSED
    # ==================================================

    if forex_market_closed():

        return jsonify({
            "market_open": False,
            "signal": "MARKET CLOSED",
            "symbol": symbol,
            "timeframe": f"{TIMEFRAMES[timeframe]} Minute",
            "message": "Real Forex market is currently closed."
        })

    minutes = TIMEFRAMES[timeframe]

    # ==================================================
    # REQUEST MARKET DATA
    # ==================================================

    if minutes == 60:
        interval = "1h"

    elif minutes == 240:
        interval = "4h"

    elif minutes in [1, 5, 15, 30]:
        interval = f"{minutes}min"

    else:
        # For 2, 3 and 10 minute charts,
        # get 1-minute candles and combine them below.
        interval = "1min"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": 300,
        "apikey": API_KEY
    }

    try:

        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params=params,
            timeout=20
        )

        data = response.json()

    except Exception as e:

        return jsonify({
            "market_open": True,
            "signal": "NO SIGNAL",
            "error": f"Market data request failed: {str(e)}"
        }), 500

    if "values" not in data:

        return jsonify({
            "market_open": True,
            "signal": "NO SIGNAL",
            "error": data.get(
                "message",
                "Market data is unavailable."
            )
        }), 400

    raw = list(reversed(data["values"]))

    # ==================================================
    # BUILD CANDLES
    # ==================================================

    candles = []

    if minutes in [1, 5, 15, 30, 60, 240]:

        for item in raw:

            candles.append({
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"])
            })

    else:

        for i in range(
            0,
            len(raw) - minutes + 1,
            minutes
        ):

            group = raw[i:i + minutes]

            candles.append({
                "open": float(group[0]["open"]),
                "high": max(
                    float(x["high"]) for x in group
                ),
                "low": min(
                    float(x["low"]) for x in group
                ),
                "close": float(group[-1]["close"])
            })

    # ==================================================
    # CHECK DATA
    # ==================================================

    if len(candles) < 60:

        return jsonify({
            "market_open": True,
            "signal": "NO SIGNAL",
            "error": "Not enough candle data."
        }), 400

    closes = [
        float(c["close"])
        for c in candles
    ]

    current = candles[-1]

    price = float(current["close"])
    open_price = float(current["open"])

    # ==================================================
    # INDICATORS
    # ==================================================

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
            "error": "Not enough data for indicators."
        }), 400

    # ==================================================
    # CANDLE
    # ==================================================

    if price > open_price:

        candle = "BULLISH"

    elif price < open_price:

        candle = "BEARISH"

    else:

        candle = "DOJI"

    # ==================================================
    # TREND
    # ==================================================

    if price > ema50:

        trend = "ABOVE EMA"

    elif price < ema50:

        trend = "BELOW EMA"

    else:

        trend = "AT EMA"

    # ==================================================
    # SIGNAL SCORE
    # ==================================================

    call_score = 0
    put_score = 0

    # EMA
    if price > ema50:

        call_score += 1

    elif price < ema50:

        put_score += 1

    # RSI
    if rsi14 > 50:

        call_score += 1

    elif rsi14 < 50:

        put_score += 1

    # Candle
    if candle == "BULLISH":

        call_score += 1

    elif candle == "BEARISH":

        put_score += 1

    # ==================================================
    # FINAL SIGNAL
    # ==================================================

    if call_score == 3:

        signal = "CALL / UP"

    elif put_score == 3:

        signal = "PUT / DOWN"

    else:

        signal = "WAIT"

    confidence = int(
        max(call_score, put_score) / 3 * 100
    )

    # ==================================================
    # RESPONSE
    # ==================================================

    return jsonify({

        "market_open": True,

        "symbol": symbol,

        "timeframe": f"{minutes} Minute",

        "price": round(
            price,
            5
        ),

        "ema50": round(
            ema50,
            5
        ),

        "rsi14": round(
            rsi14,
            2
        ),

        "candle": candle,

        "trend": trend,

        "signal": signal,

        "confidence": confidence,

        "data_source": "Twelve Data",

        "warning": (
            "This is technical analysis only. "
            "It is not a guaranteed trading signal."
        )
    })


# ==================================================
# START SERVER
# ==================================================

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
