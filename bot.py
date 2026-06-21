import requests, time, json, os, asyncio
from datetime import datetime, timezone
from telegram import Bot

BOT_TOKEN = "8916572820:AAFmWoJhFOXnjwGU638SFMGHtdOLRBS0HkA"
API_KEY = "9f15ada892ae4fdc887e62de9b2ba265"
CHANNEL_ID = -1004359509046

SYMBOLS = [
    "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "USD/CAD", "AUD/USD", "NZD/USD", "EUR/JPY", "GBP/JPY"
]

bot = Bot(BOT_TOKEN)

DATA_FILE = "trades.json"
STATS_FILE = "stats.json"

def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

open_trades = load_json(DATA_FILE, {})
stats = load_json(STATS_FILE, {"win": 0, "loss": 0, "total": 0, "last_stats_day": ""})

def market_open():
    now = datetime.now(timezone.utc)
    day = now.weekday()
    hour = now.hour
    if day == 5:
        return False
    if day == 6 and hour < 21:
        return False
    if day == 4 and hour >= 21:
        return False
    return True

def get_candles(symbol, interval="15min", size=120):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": size,
        "apikey": API_KEY
    }
    try:
        data = requests.get(url, params=params, timeout=20).json()
        if "values" not in data:
            return None
        candles = list(reversed(data["values"]))
        return [
            {
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"])
            }
            for c in candles
        ]
    except:
        return None

def closes(candles):
    return [c["close"] for c in candles]

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for p in values[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period

def macd(values):
    if len(values) < 35:
        return None, None
    ema12 = ema(values[-40:], 12)
    ema26 = ema(values[-40:], 26)
    if ema12 is None or ema26 is None:
        return None, None
    line = ema12 - ema26
    signal = line * 0.8
    return line, signal

def analyze(symbol):
    c15 = get_candles(symbol, "15min", 120)
    c1h = get_candles(symbol, "1h", 120)
    c4h = get_candles(symbol, "4h", 120)

    if not c15 or not c1h or not c4h:
        return None

    p15 = closes(c15)
    p1h = closes(c1h)
    p4h = closes(c4h)

    price = p15[-1]

    ema20_15 = ema(p15[-40:], 20)
    ema50_15 = ema(p15[-80:], 50)

    ema50_1h = ema(p1h[-90:], 50)
    ema200_1h = ema(p1h, 100)

    ema50_4h = ema(p4h[-90:], 50)
    ema200_4h = ema(p4h, 100)

    r = rsi(p15)
    a = atr(c15)
    macd_line, macd_signal = macd(p15)

    if None in [ema20_15, ema50_15, ema50_1h, ema200_1h, ema50_4h, ema200_4h, r, a, macd_line, macd_signal]:
        return None

    score_buy = 0
    score_sell = 0

    if price > ema20_15 > ema50_15:
        score_buy += 25
    if price < ema20_15 < ema50_15:
        score_sell += 25

    if ema50_1h > ema200_1h:
        score_buy += 25
    if ema50_1h < ema200_1h:
        score_sell += 25

    if ema50_4h > ema200_4h:
        score_buy += 25
    if ema50_4h < ema200_4h:
        score_sell += 25

    if 50 < r < 65:
        score_buy += 15
    if 35 < r < 50:
        score_sell += 15

    if macd_line > macd_signal:
        score_buy += 10
    if macd_line < macd_signal:
        score_sell += 10

    if score_buy >= 85:
        side = "BUY"
        score = score_buy
    elif score_sell >= 85:
        side = "SELL"
        score = score_sell
    else:
        return None

    risk = a * 1.2

    if side == "BUY":
        sl = price - risk
        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 3.5
    else:
        sl = price + risk
        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 3.5

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(price, 5),
        "sl": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "score": score,
        "hit": []
    }

async def send_trade(t):
    msg = f"""🚀 توصية فوركس قوية

📊 الزوج: {t['symbol']}
📈 الاتجاه: {t['side']}
🔥 قوة التحليل: {t['score']}/100

🎯 الدخول: {t['entry']}

✅ TP1: {t['tp1']}
✅ TP2: {t['tp2']}
✅ TP3: {t['tp3']}
🛑 SL: {t['sl']}

⚠️ الصفقة تحليل آلي قوي وليست ضمان ربح."""
    await bot.send_message(CHANNEL_ID, msg)

async def send_result(text):
    await bot.send_message(CHANNEL_ID, text)

def hit_price(side, price, level):
    return price >= level if side == "BUY" else price <= level

def hit_sl(side, price, sl):
    return price <= sl if side == "BUY" else price >= sl

async def daily_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    if stats.get("last_stats_day") == today:
        return

    if stats["total"] == 0:
        return

    rate = round((stats["win"] / stats["total"]) * 100, 2)
    msg = f"""📊 إحصائيات اليوم

الصفقات: {stats['total']}
الرابحة: {stats['win']}
الخاسرة: {stats['loss']}
نسبة النجاح: {rate}%"""

    await send_result(msg)
    stats["last_stats_day"] = today
    save_json(STATS_FILE, stats)

async def main():
    while True:
        try:
            if not market_open():
                await asyncio.sleep(1800)
                continue

            for symbol in SYMBOLS:
                candles = get_candles(symbol, "15min", 20)
                if not candles:
                    continue

                price = candles[-1]["close"]

                if symbol in open_trades:
                    t = open_trades[symbol]

                    for tp in ["tp1", "tp2", "tp3"]:
                        if tp not in t["hit"] and hit_price(t["side"], price, t[tp]):
                            t["hit"].append(tp)
                            await send_result(f"✅ تحقق {tp.upper()}\n\n📊 {symbol}\n📈 {t['side']}\n🎯 السعر: {round(price, 5)}")
                            save_json(DATA_FILE, open_trades)

                    if hit_sl(t["side"], price, t["sl"]):
                        stats["loss"] += 1
                        stats["total"] += 1
                        await send_result(f"❌ ضرب وقف الخسارة\n\n📊 {symbol}\n🛑 السعر: {round(price, 5)}")
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                    elif "tp3" in t["hit"]:
                        stats["win"] += 1
                        stats["total"] += 1
                        await send_result(f"🏆 اكتملت الصفقة بنجاح\n\n📊 {symbol}\n✅ TP1 + TP2 + TP3")
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                else:
                    t = analyze(symbol)
                    if t:
                        open_trades[symbol] = t
                        save_json(DATA_FILE, open_trades)
                        await send_trade(t)

                await asyncio.sleep(10)

            await daily_stats()
            await asyncio.sleep(900)

        except Exception as e:
            await asyncio.sleep(60)

asyncio.run(main())
