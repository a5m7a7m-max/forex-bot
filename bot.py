import os, json, asyncio, requests
from datetime import datetime, timezone
from telegram import Bot
from openai import OpenAI
from PIL import Image, ImageDraw

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
API_KEY = os.getenv("API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(BOT_TOKEN)
ai = OpenAI(api_key=OPENAI_API_KEY)

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CAD", "XAU/USD"
]

DATA_FILE = "trades.json"
STATS_FILE = "stats.json"

def load_json(file, default):
    try:
        if os.path.exists(file):
            with open(file, "r") as f:
                return json.load(f)
    except:
        pass
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
        values = list(reversed(data["values"]))
        return [{
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"])
        } for c in values]
    except:
        return None

def closes(candles):
    return [c["close"] for c in candles]

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
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
        prev = candles[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    return sum(trs[-period:]) / period

def macd(values):
    e12 = ema(values[-60:], 12)
    e26 = ema(values[-60:], 26)
    if e12 is None or e26 is None:
        return None
    return e12 - e26

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

    ema20 = ema(p15[-60:], 20)
    ema50 = ema(p15[-90:], 50)
    ema100_1h = ema(p1h[-120:], 100)
    ema100_4h = ema(p4h[-120:], 100)
    r = rsi(p15)
    a = atr(c15)
    m = macd(p15)

    if None in [ema20, ema50, ema100_1h, ema100_4h, r, a, m]:
        return None

    buy = 0
    sell = 0

    if price > ema20 > ema50:
        buy += 25
    if price < ema20 < ema50:
        sell += 25

    if price > ema100_1h:
        buy += 20
    if price < ema100_1h:
        sell += 20

    if price > ema100_4h:
        buy += 20
    if price < ema100_4h:
        sell += 20

    if 45 <= r <= 68:
        buy += 20
    if 32 <= r <= 55:
        sell += 20

    if m > 0:
        buy += 15
    if m < 0:
        sell += 15

    last = c15[-1]
    body = abs(last["close"] - last["open"])
    rng = last["high"] - last["low"]

    if rng > 0 and body / rng > 0.45:
        if last["close"] > last["open"]:
            buy += 10
        else:
            sell += 10

    if buy >= 85 and buy > sell:
        side = "BUY"
        score = buy
    elif sell >= 85 and sell > buy:
        side = "SELL"
        score = sell
    else:
        return None

    risk = max(a * 1.2, price * 0.0015)

    if side == "BUY":
        sl = price - risk
        tp1 = price + risk * 1.2
        tp2 = price + risk * 2
        tp3 = price + risk * 3
    else:
        sl = price + risk
        tp1 = price - risk * 1.2
        tp2 = price - risk * 2
        tp3 = price - risk * 3

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(price, 5),
        "sl": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "score": score,
        "rsi": round(r, 2),
        "hit": []
    }

def ai_filter(t):
    prompt = f"""
أنت محلل فوركس محترف. وافق فقط على الصفقات القوية جداً.
أجب بكلمة واحدة فقط: APPROVE أو REJECT.

PAIR: {t['symbol']}
SIDE: {t['side']}
ENTRY: {t['entry']}
SL: {t['sl']}
TP1: {t['tp1']}
TP2: {t['tp2']}
TP3: {t['tp3']}
SCORE: {t['score']}/100
RSI: {t['rsi']}
"""
    try:
        res = ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        answer = res.choices[0].message.content.strip().upper()
        return "APPROVE" in answer
    except:
        return False

async def send_trade(t):
    msg = f"""🚀 توصية فوركس AI قوية

📊 الزوج: {t['symbol']}
📈 الاتجاه: {t['side']}

🎯 الدخول: {t['entry']}
✅ TP1: {t['tp1']}
✅ TP2: {t['tp2']}
✅ TP3: {t['tp3']}
🛑 SL: {t['sl']}

🧠 قوة التحليل: {t['score']}/100
🤖 الذكاء الاصطناعي: موافق ✅

⚠️ إدارة رأس المال مهمة، ليست ضمان ربح."""
    await bot.send_message(CHANNEL_ID, msg)

async def send_result_image(title, t, result_text):
    img = Image.new("RGB", (900, 600), (16, 20, 30))
    draw = ImageDraw.Draw(img)

    lines = [
        "CRYPTO STAR VIP",
        title,
        "",
        f"PAIR: {t['symbol']}",
        f"SIDE: {t['side']}",
        f"ENTRY: {t['entry']}",
        f"TP1: {t['tp1']}",
        f"TP2: {t['tp2']}",
        f"TP3: {t['tp3']}",
        f"SL: {t['sl']}",
        "",
        result_text
    ]

    y = 35
    for line in lines:
        draw.text((60, y), line, fill=(255, 255, 255))
        y += 42

    path = "result.png"
    img.save(path)

    caption = f"{title}\n📊 {t['symbol']}\n📈 {t['side']}"
    with open(path, "rb") as photo:
        await bot.send_photo(CHANNEL_ID, photo=photo, caption=caption)

async def send_text(text):
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

    await send_text(msg)
    stats["last_stats_day"] = today
    save_json(STATS_FILE, stats)

async def main():
    await bot.send_message(CHANNEL_ID, "✅ بوت الفوركس AI اشتغل وينتظر فرص قوية")

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
                            await send_result_image(
                                f"✅ تحقق {tp.upper()}",
                                t,
                                f"PROFIT TARGET HIT: {tp.upper()}"
                            )
                            save_json(DATA_FILE, open_trades)

                    if hit_sl(t["side"], price, t["sl"]):
                        stats["loss"] += 1
                        stats["total"] += 1
                        await send_result_image(
                            "❌ وقف الخسارة",
                            t,
                            "LOSS: STOP LOSS HIT"
                        )
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                    elif "tp3" in t["hit"]:
                        stats["win"] += 1
                        stats["total"] += 1
                        await send_result_image(
                            "🏆 اكتملت الصفقة بنجاح",
                            t,
                            "FULL PROFIT: TP1 + TP2 + TP3"
                        )
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                else:
                    t = analyze(symbol)
                    if t and ai_filter(t):
                        open_trades[symbol] = t
                        save_json(DATA_FILE, open_trades)
                        await send_trade(t)

                await asyncio.sleep(10)

            await daily_stats()
            await asyncio.sleep(900)

        except Exception as e:
            await send_text(f"⚠️ خطأ في البوت:\n{e}")
            await asyncio.sleep(60)

asyncio.run(main())
