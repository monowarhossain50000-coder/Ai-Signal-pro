import os
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)

API_KEY = os.getenv("TWELVEDATA_API_KEY")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/market")
def market():

    if not API_KEY:
        return jsonify({
            "error": "API key is not configured"
        }), 500

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": "EUR/USD",
        "interval": "1min",
        "outputsize": 60,
        "apikey": API_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if "values" not in data:
            return jsonify({
                "error": data.get("message", "Market data unavailable")
            }), 400

        return jsonify(data)

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
    app.run(host="0.0.0.0", port=5000)
