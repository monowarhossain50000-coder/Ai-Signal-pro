import os
import time
import requests

from datetime import datetime, timezone


API_KEY = os.getenv("TWELVEDATA_API_KEY")

API_URL = "https://api.twelvedata.com/time_series"

PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
    "EUR/GBP",
    "EUR/JPY",
    "GBP/JPY"
]


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    result = sum(
        values[:period]
    ) / period

    multiplier = 2 / (
        period + 1
    )

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
        ) + result

    return result


# =========================================================
# RSI
# =========================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:

        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# GET MARKET DATA
# =========================================================

def get_data(symbol):

    params = {

        "symbol":
            symbol,

        "interval":
            "1min",

        "outputsize":
            220,

        "apikey":
            API_KEY
    }

    response = requests.get(

        API_URL,

        params=params,

        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:

        raise Exception(
            data.get(
                "message",
                "Market data unavailable"
            )
        )

    values = list(
        reversed(
            data["values"]
        )
    )

    candles = []

    for item in values:

        candles.append({

            "datetime":
                item["datetime"],

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

    return candles


# =========================================================
# SCAN ONE PAIR
# =========================================================

def scan_pair(symbol):

    candles = get_data(
        symbol
    )

    if len(candles) < 210:

        return {

            "symbol":
                symbol,

            "signal":
                "NO TRADE",

            "score":
                0,

            "error":
                "Not enough data"
        }

    closes = [

        c["close"]

        for c in candles
    ]

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema200 = ema(
        closes,
        200
    )

    rsi14 = rsi(
        closes,
        14
    )

    previous = candles[-2]

    if (
        previous["close"]
        > previous["open"]
    ):

        candle = "BULLISH"

    elif (
        previous["close"]
        < previous["open"]
    ):

        candle = "BEARISH"

    else:

        candle = "DOJI"

    call = 0
    put = 0

    # -----------------------------------------------------
    # EMA TREND
    # -----------------------------------------------------

    if (
        ema20
        > ema50
        > ema200
    ):

        call += 3

    elif (
        ema20
        < ema50
        < ema200
    ):

        put += 3

    # -----------------------------------------------------
    # PRICE / EMA50
    # -----------------------------------------------------

    if price > ema50:

        call += 2

    elif price < ema50:

        put += 2

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if rsi14 >= 55:

        call += 2

    elif rsi14 <= 45:

        put += 2

    # -----------------------------------------------------
    # CANDLE
    # -----------------------------------------------------

    if candle == "BULLISH":

        call += 1

    elif candle == "BEARISH":

        put += 1

    # -----------------------------------------------------
    # FINAL
    # -----------------------------------------------------

    difference = abs(
        call - put
    )

    if (
        call >= 6
        and call > put
        and difference >= 2
    ):

        signal = "CALL / UP"

    elif (
        put >= 6
        and put > call
        and difference >= 2
    ):

        signal = "PUT / DOWN"

    else:

        signal = "NO TRADE"

    score = max(
        call,
        put
    )

    return {

        "symbol":
            symbol,

        "price":
            round(
                price,
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

        "rsi":
            round(
                rsi14,
                2
            ),

        "candle":
            candle,

        "call_score":
            call,

        "put_score":
            put,

        "score":
            score,

        "signal":
            signal
    }


# =========================================================
# SCAN ALL PAIRS
# =========================================================

def scan_market():

    results = []

    for symbol in PAIRS:

        try:

            result = scan_pair(
                symbol
            )

            results.append(
                result
            )

        except Exception as e:

            results.append({

                "symbol":
                    symbol,

                "signal":
                    "ERROR",

                "error":
                    str(e)
            })

        time.sleep(1)

    return results


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    if not API_KEY:

        print(
            "ERROR: "
            "TWELVEDATA_API_KEY is missing."
        )

        raise SystemExit

    print(
        "\n"
        "================================"
    )

    print(
        "      MARKET SCANNER"
    )

    print(
        "================================"
    )

    print(
        "Time:",
        datetime.now(
            timezone.utc
        )
    )

    print()

    results = scan_market()

    for item in results:

        print(
            "--------------------------------"
        )

        print(
            "Symbol:",
            item.get(
                "symbol"
            )
        )

        print(
            "Signal:",
            item.get(
                "signal"
            )
        )

        print(
            "CALL:",
            item.get(
                "call_score",
                "-"
            )
        )

        print(
            "PUT:",
            item.get(
                "put_score",
                "-"
            )
        )

        print(
            "RSI:",
            item.get(
                "rsi",
                "-"
            )
        )

        print(
            "Candle:",
            item.get(
                "candle",
                "-"
            )
        )

    print(
        "================================"
    )
