def generate_running_signal(
    candles,
    symbol,
    timeframe,
    market_type
):

    if len(candles) < 220:
        raise Exception("Not enough candle data.")

    # =====================================================
    # CURRENT RUNNING CANDLE
    # =====================================================

    running = candles[-1]
    completed = candles[:-1]

    if len(completed) < 210:
        raise Exception("Not enough completed candles.")

    # =====================================================
    # LAST COMPLETED CANDLES
    # =====================================================

    c1 = completed[-1]
    c2 = completed[-2]
    c3 = completed[-3]
    c4 = completed[-4]
    c5 = completed[-5]
    c6 = completed[-6]

    # =====================================================
    # INDICATORS FROM COMPLETED CANDLES
    # =====================================================

    closes = [
        float(c["close"])
        for c in completed[-250:]
    ]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    rsi14 = calculate_rsi(closes, 14)

    if (
        ema20 is None
        or ema50 is None
        or ema200 is None
        or rsi14 is None
    ):
        raise Exception("Indicator calculation failed.")

    # =====================================================
    # RUNNING CANDLE INFO
    # =====================================================

    rc = candle_info(running)

    running_direction = rc["direction"]

    running_strength = rc["body_ratio"] * 100

    running_position = rc["close_position"]

    price = float(running["close"])

    # =====================================================
    # COMPLETED CANDLE INFO
    # =====================================================

    infos = [
        candle_info(c1),
        candle_info(c2),
        candle_info(c3),
        candle_info(c4),
        candle_info(c5),
        candle_info(c6)
    ]

    directions = [
        x["direction"]
        for x in infos
    ]

    bullish_count = directions.count("BULLISH")
    bearish_count = directions.count("BEARISH")

    previous_direction = infos[0]["direction"]

    # =====================================================
    # SCORE
    # =====================================================

    call_score = 0
    put_score = 0

    # =====================================================
    # EMA 20 / 50
    # =====================================================

    if ema20 > ema50:
        call_score += 2

    elif ema20 < ema50:
        put_score += 2

    # =====================================================
    # EMA 50 / 200
    # =====================================================

    if ema50 > ema200:
        call_score += 2

    elif ema50 < ema200:
        put_score += 2

    # =====================================================
    # PRICE VS EMA50
    # =====================================================

    if price > ema50:
        call_score += 2

    elif price < ema50:
        put_score += 2

    # =====================================================
    # PRICE VS EMA200
    # =====================================================

    if price > ema200:
        call_score += 1

    elif price < ema200:
        put_score += 1

    # =====================================================
    # RSI
    # =====================================================

    if rsi14 >= 58:
        call_score += 3

    elif rsi14 >= 54:
        call_score += 2

    elif rsi14 >= 51:
        call_score += 1

    elif rsi14 <= 42:
        put_score += 3

    elif rsi14 <= 46:
        put_score += 2

    elif rsi14 < 49:
        put_score += 1

    # =====================================================
    # PREVIOUS COMPLETED CANDLE
    # =====================================================

    if previous_direction == "BULLISH":
        call_score += 2

    elif previous_direction == "BEARISH":
        put_score += 2

    # =====================================================
    # RECENT MOMENTUM
    # =====================================================

    if bullish_count >= 5:
        call_score += 2

    elif bullish_count >= 4:
        call_score += 1

    if bearish_count >= 5:
        put_score += 2

    elif bearish_count >= 4:
        put_score += 1

    # =====================================================
    # PRICE MOMENTUM
    # =====================================================

    prices = [
        float(completed[-i]["close"])
        for i in range(1, 6)
    ]

    rising = 0
    falling = 0

    for i in range(len(prices) - 1):

        if prices[i] > prices[i + 1]:
            rising += 1

        elif prices[i] < prices[i + 1]:
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
    # RUNNING CANDLE
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
            call_score += 2

        elif running_direction == "BEARISH":
            put_score += 2

    elif running_strength >= 40:

        if running_direction == "BULLISH":
            call_score += 1

        elif running_direction == "BEARISH":
            put_score += 1

    # =====================================================
    # CLOSE POSITION
    # =====================================================

    if (
        running_direction == "BULLISH"
        and running_position >= 0.65
    ):
        call_score += 1

    elif (
        running_direction == "BEARISH"
        and running_position <= 0.35
    ):
        put_score += 1

    # =====================================================
    # DIFFERENCE
    # =====================================================

    difference = abs(
        call_score - put_score
    )

    highest = max(
        call_score,
        put_score
    )

    total = (
        call_score
        + put_score
    )

    # =====================================================
    # CONFIDENCE
    # =====================================================

    if total <= 0:

        confidence = 50

    else:

        dominance = highest / total

        confidence = int(
            50
            + (dominance - 0.5) * 80
        )

    # =====================================================
    # WEAK RSI PROTECTION
    # =====================================================

    if 48 <= rsi14 <= 52:

        confidence -= 10

    elif 47 <= rsi14 <= 53:

        confidence -= 6

    elif 46 <= rsi14 <= 54:

        confidence -= 3

    # =====================================================
    # WEAK RUNNING CANDLE PROTECTION
    # =====================================================

    if running_strength < 20:

        confidence -= 12

    elif running_strength < 30:

        confidence -= 6

    # =====================================================
    # DOJI PROTECTION
    # =====================================================

    is_doji = (
        running_direction == "DOJI"
        or running_strength < 5
    )

    if is_doji:

        confidence = min(
            confidence,
            55
        )

    # =====================================================
    # CONFIDENCE LIMIT
    # =====================================================

    confidence = max(
        50,
        min(
            88,
            confidence
        )
    )

    # =====================================================
    # SIGNAL DECISION
    # =====================================================

    signal = "NO TRADE"
    signal_level = "NO TRADE"

    # =====================================================
    # HARD SAFETY FILTER
    # =====================================================

    # Doji বা খুব দুর্বল running candle হলে
    # কোনো directional trade নয়।

    if is_doji:

        signal = "NO TRADE"
        signal_level = "WAIT FOR CONFIRMATION"

    elif running_strength < 20:

        signal = "NO TRADE"
        signal_level = "WEAK CANDLE"

    else:

        # =================================================
        # CALL FILTER
        # =================================================

        call_allowed = (
            call_score > put_score
            and difference >= 3
            and confidence >= 64
            and running_direction == "BULLISH"
        )

        # RSI খুব দুর্বল হলে CALL নয়
        if rsi14 < 51:
            call_allowed = False

        # Strong CALL-এর জন্য অতিরিক্ত confirmation
        strong_call = (
            call_allowed
            and confidence >= 78
            and running_strength >= 40
            and rsi14 >= 54
            and previous_direction == "BULLISH"
            and price >= ema50
        )

        # =================================================
        # PUT FILTER
        # =================================================

        put_allowed = (
            put_score > call_score
            and difference >= 3
            and confidence >= 64
            and running_direction == "BEARISH"
        )

        # RSI খুব দুর্বল হলে PUT নয়
        if rsi14 > 49:
            put_allowed = False

        # Strong PUT-এর জন্য অতিরিক্ত confirmation
        strong_put = (
            put_allowed
            and confidence >= 78
            and running_strength >= 40
            and rsi14 <= 46
            and previous_direction == "BEARISH"
            and price <= ema50
        )

        # =================================================
        # FINAL CALL
        # =================================================

        if strong_call:

            signal = "CALL / UP"
            signal_level = "STRONG"

        elif strong_put:

            signal = "PUT / DOWN"
            signal_level = "STRONG"

        elif call_allowed:

            signal = "CALL / UP"

            if confidence >= 70:
                signal_level = "GOOD"
            else:
                signal_level = "MODERATE"

        elif put_allowed:

            signal = "PUT / DOWN"

            if confidence >= 70:
                signal_level = "GOOD"
            else:
                signal_level = "MODERATE"

    # =====================================================
    # TREND
    # =====================================================

    if (
        price > ema20
        and ema20 > ema50
        and ema50 > ema200
    ):

        trend = "BULLISH STRONG"

    elif (
        price < ema20
        and ema20 < ema50
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
    # RESULT
    # =====================================================

    result = {

        "market_open": True,

        "signal_for":
            "CURRENT RUNNING CANDLE",

        "trade_window":
            "FIRST 30 SECONDS",

        "symbol":
            symbol,

        "timeframe":
            f"{TIMEFRAMES[timeframe]} Minute",

        "running_candle_time":
            running.get("datetime"),

        "price":
            round(price, 5),

        "ema20":
            round(ema20, 5),

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
            round(running_strength, 1),

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
                "Running-candle signal for the current "
                "candle. Intended for early entry during "
                "the first 30 seconds. Direction can change "
                "while the candle is forming."
            )
    }

    # =====================================================
    # EXTRA FILTER MESSAGE
    # =====================================================

    if is_doji:

        result["filter_reason"] = (
            "Running candle is DOJI/too weak. "
            "Directional signal blocked."
        )

    elif running_strength < 20:

        result["filter_reason"] = (
            "Running candle strength is too weak."
        )

    elif 47 <= rsi14 <= 53:

        result["filter_reason"] = (
            "RSI is near neutral. "
            "Signal confidence reduced."
        )

    # =====================================================
    # OTC WARNING
    # =====================================================

    if market_type == "otc":

        result["warning"] = (
            "OTC uses proxy market data. "
            "It is not the direct Quotex OTC feed."
        )

    return result
