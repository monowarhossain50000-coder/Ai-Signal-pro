import os
import time
import math
import requests
from datetime import datetime, timezone
from threading import Lock
from flask import Flask, jsonify, render_template, request


app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("TWELVEDATA_API_KEY")

# Twelve Data rate-limit protection
CACHE_SECONDS = 8
API_MIN_GAP = 12

market_cache = {}
quote_cache = {}

last_api_request = 0.0
last_quote_request = 0.0

cache_lock = Lock()
quote_lock = Lock()


# ============================================================
# SYMBOLS
# ============================================================

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
    "GBP/JPY",
    "AUD/JPY",
    "EUR/AUD",
    "EUR/CAD",
    "GBP/CAD",
    "CHF/JPY",
    "CAD/JPY",
    "AUD/CAD",
    "NZD/JPY",
    "GBP/CHF",
    "EUR/CHF",
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
    "GBP/JPY OTC",
    "AUD/JPY OTC",
    "EUR/AUD OTC",
    "EUR/CAD OTC",
    "GBP/CAD OTC",
    "USD/BDT OTC",
    "USD/INR OTC",
    "USD/PKR OTC",
    "USD/TRY OTC",
    "USD/ZAR OTC",
    "XAU/USD OTC",
    "XAG/USD OTC",
    "BTC/USD OTC",
    "ETH/USD OTC",
    "AAPL OTC",
    "TSLA OTC",
    "AMZN OTC",
    "MSFT OTC",
    "GOOGL OTC",
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
    "240": 240,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(symbol):
    symbol = (symbol or "EUR/USD").strip().upper()
    symbol = symbol.replace(" OTC", "").strip()
    return symbol


def is_otc_symbol(symbol):
    return " OTC" in (symbol or "").upper()


def utc_now():
    return datetime.now(timezone.utc)


def parse_market_datetime(value):
    if not value:
        return None

    text = str(value).strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def round_price(value):
    if value is None:
        return None

    if abs(value) >= 100:
        return round(value, 3)

    if abs(value) >= 1:
        return round(value, 5)

    return round(value, 8)


def clamp(value, low, high):
    return max(low, min(high, value))


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):
    if not values:
        return None

    if len(values) < period:
        period = len(values)

    if period <= 0:
        return None

    sma = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    ema = sma

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
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
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# BOLLINGER BANDS
# ============================================================

def calculate_bollinger(values, period=20, multiplier=2):
    if len(values) < period:
        return None

    window = values[-period:]

    middle = sum(window) / period

    variance = sum(
        (price - middle) ** 2
        for price in window
    ) / period

    std = math.sqrt(variance)

    upper = middle + multiplier * std
    lower = middle - multiplier * std

    return {
        "lower": lower,
        "middle": middle,
        "upper": upper,
        "width": upper - lower,
    }


# ============================================================
# CANDLE ANALYSIS
# ============================================================

def analyze_candle(candle):
    if not candle:
        return None

    o = safe_float(candle.get("open"))
    h = safe_float(candle.get("high"))
    l = safe_float(candle.get("low"))
    c = safe_float(candle.get("close"))

    if None in (o, h, l, c):
        return None

    candle_range = max(h - l, 0)

    body = abs(c - o)

    if candle_range > 0:
        body_ratio = body / candle_range
        close_position = (c - l) / candle_range
    else:
        body_ratio = 0
        close_position = 0.5

    upper_wick = max(h - max(o, c), 0)
    lower
