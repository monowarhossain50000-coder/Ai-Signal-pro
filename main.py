import os
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


def calculate_ema(prices, period=50):
    if len(prices) < period:
        return None

    sma = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)

    ema = sma

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

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

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

        prices = []

        for candle in reversed(candles):
            prices.append(float(candle["close"]))

        current_price = prices[-1]

        ema50 = calculate_ema(
            prices,
            50
        )

        rsi14 = calculate_rsi(
            prices,
            14
        )

        if ema50 is None or rsi14 is None:
            signal = "WAIT"
        elif current_price > ema50 and rsi14 > 50:
            signal = "CALL / UP"
        elif current_price < ema50 and rsi14 < 50:
            signal = "PUT / DOWN"
        else:
            signal = "WAIT"

        return jsonify({
            "symbol": symbol,
            "interval": interval,
            "price": round(current_price, 5),
            "ema50": round(ema50, 5) if ema50 else None,
            "rsi14": round(rsi14, 2) if rsi14 else None,
            "signal": signal
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
