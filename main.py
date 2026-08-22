import os
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


def calculate_ema(prices, period=50):
    if len(prices) < period:
        return None

    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)

    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/market")
def market():

    if not API_KEY:
        return jsonify({
            "error": "API key is not configured"
        }), 500

    symbol = "EUR/USD"
    interval = "1min"

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": 100,
        "apikey": API_KEY
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        data = response.json()

        if "values" not in data:
            return jsonify({
                "error": data.get(
                    "message",
                    "Market data unavailable"
                )
            }), 400

        candles = data["values"]

        candles = list(reversed(candles))

        closes = [
            float(c["close"])
            for c in candles
        ]

        current = candles[-1]
        previous = candles[-2]

        current_price = float(current["close"])

        previous_close = float(previous["close"])

        open_price = float(current["open"])

        ema50 = calculate_ema(
            closes,
            50
        )

        rsi14 = calculate_rsi(
            closes,
            14
        )

        # Candle direction
        if current_price > open_price:
            candle = "BULLISH"
        elif current_price < open_price:
            candle = "BEARISH"
        else:
            candle = "DOJI"

        # EMA trend
        if current_price > ema50:
            ema_trend = "ABOVE EMA"
        elif current_price < ema50:
            ema_trend = "BELOW EMA"
        else:
            ema_trend = "AT EMA"

        # Signal scoring
        call_score = 0
        put_score = 0

        # Price vs EMA
        if current_price > ema50:
            call_score += 1
        elif current_price < ema50:
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

        # Final signal
        if call_score >= 3:
            signal = "CALL / UP"
            score = 3

        elif put_score >= 3:
            signal = "PUT / DOWN"
            score = 3

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

            "symbol": symbol,

            "interval": interval,

            "price": round(
                current_price,
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

            "ema_trend": ema_trend,

            "signal": signal,

            "confidence": confidence

        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/status")
def status():

    return jsonify({
        "status": "online"
    })


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
