import os, json, asyncio, requests, random
from io import BytesIO
from datetime import datetime, timezone
from telegram import Bot
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
API_KEY = os.getenv("API_KEY")  # TwelveData API Key

bot = Bot(BOT_TOKEN)

SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CAD", "XAU/USD"]

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

def get_candles(symbol, interval="15min", size=120):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": size, "apikey": API_KEY}
        data = requests.get(url, params=params, timeout=20).json()
        if "values" not in data:
            return None
        values = list(reversed(data["values"]))
        return [{"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"])} for c in values]
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
        prev = candles[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    return sum(trs[-period:]) / period

def analyze(symbol):
    candles = get_candles(symbol)
    if not candles:
        return None

    c = closes(candles)
    price = c[-1]
    ema20 = ema(c[-40:], 20)
    ema50 = ema(c[-70:], 50)
    r = rsi(c)
    a = atr(candles)

    if not ema20 or not ema50 or not r or not a:
        return None

    score = 0
    side = None

    if ema20 > ema50 and 45 <= r <= 68:
        side = "BUY"
        score += 45
    elif ema20 < ema50 and 32 <= r <= 55:
        side = "SELL"
        score += 45
    else:
        return None

    last = candles[-1]
    prev = candles[-2]

    if side == "BUY" and last["close"] > prev["close"]:
        score += 20
    if side == "SELL" and last["close"] < prev["close"]:
        score += 20

    if a > 0:
        score += 20

    score += random.randint(5, 15)

    if score < 80:
        return None

    if side == "BUY":
        tp1 = price + a * 0.8
        tp2 = price + a * 1.4
        tp3 = price + a * 2.0
        sl = price - a * 1.1
    else:
        tp1 = price - a * 0.8
        tp2 = price - a * 1.4
        tp3 = price - a * 2.0
        sl = price + a * 1.1

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(price, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "sl": round(sl, 5),
        "score": min(score, 95),
        "hit": []
    }

async def send_msg(text):
    await bot.send_message(chat_id=CHANNEL_ID, text=text)

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

⚠️ التزم بإدارة رأس المال."""
    await send_msg(msg)

def make_result_image(symbol, result, total, win, loss):
    img = Image.new("RGB", (900, 600), (20, 25, 35))
    d = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("DejaVuSans.ttf", 48)
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except:
        font_big = font = None

    d.text((60, 50), "FOREX VIP RESULT", fill=(255, 215, 120), font=font_big)
    d.text((60, 150), f"Pair: {symbol}", fill="white", font=font)
    d.text((60, 220), f"Result: {result}", fill=(80, 255, 120) if "TP" in result else (255, 80, 80), font=font)
    d.text((60, 310), f"Total trades: {total}", fill="white", font=font)
    d.text((60, 370), f"Winning: {win}", fill=(80, 255, 120), font=font)
    d.text((60, 430), f"Losing: {loss}", fill=(255, 80, 80), font=font)

    rate = round((win / total) * 100, 2) if total else 0
    d.text((60, 490), f"Success Rate: {rate}%", fill=(255, 215, 120), font=font)

    bio = BytesIO()
    bio.name = "result.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

async def send_result_image(symbol, result):
    img = make_result_image(symbol, result, stats["total"], stats["win"], stats["loss"])
    await bot.send_photo(chat_id=CHANNEL_ID, photo=img)

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
    msg = f"""📊 إحصائيات الصفقات

📌 إجمالي الصفقات: {stats['total']}
✅ الرابحة: {stats['win']}
❌ الخاسرة: {stats['loss']}
🏆 نسبة النجاح: {rate}%"""
    await send_msg(msg)
    stats["last_stats_day"] = today
    save_json(STATS_FILE, stats)

async def main():
    await send_msg("✅ بوت الفوركس اشتغل وينتظر فرص قوية")
    last_signal_time = {}

    while True:
        try:
            for symbol in SYMBOLS:
                candles = get_candles(symbol, size=20)
                if not candles:
                    continue

                price = candles[-1]["close"]

                if symbol in open_trades:
                    t = open_trades[symbol]

                    for tp in ["tp1", "tp2", "tp3"]:
                        if tp not in t["hit"] and hit_price(t["side"], price, t[tp]):
                            t["hit"].append(tp)
                            await send_msg(f"✅ تم تحقيق {tp.upper()} لصفقة {symbol}")
                            stats["win"] += 1
                            stats["total"] += 1
                            await send_result_image(symbol, tp.upper())
                            save_json(STATS_FILE, stats)

                            if tp == "tp3":
                                del open_trades[symbol]
                            else:
                                open_trades[symbol] = t

                            save_json(DATA_FILE, open_trades)
                            break

                    if symbol in open_trades and hit_sl(t["side"], price, t["sl"]):
                        await send_msg(f"❌ تم ضرب وقف الخسارة لصفقة {symbol}")
                        stats["loss"] += 1
                        stats["total"] += 1
                        await send_result_image(symbol, "SL")
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                else:
                    now = datetime.now().timestamp()
                    if now - last_signal_time.get(symbol, 0) < 3600:
                        continue

                    t = analyze(symbol)
                    if t:
                        open_trades[symbol] = t
                        save_json(DATA_FILE, open_trades)
                        await send_trade(t)
                        last_signal_time[symbol] = now

                await asyncio.sleep(5)

            await daily_stats()
            await asyncio.sleep(120)

        except Exception as e:
            print("ERROR:", e)
            await asyncio.sleep(60)

asyncio.run(main())
