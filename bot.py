import os, json, asyncio, requests, random, html
from io import BytesIO
from datetime import datetime, timedelta
from telegram import Bot
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
API_KEY = os.getenv("API_KEY")

bot = Bot(BOT_TOKEN)

SYMBOLS = ["EUR/USD","GBP/USD","USD/JPY","USD/CHF","EUR/JPY","GBP/JPY","AUD/USD","USD/CAD","XAU/USD"]

DATA_FILE = "trades.json"
STATS_FILE = "daily_stats.json"

def now_ymd():
    return (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")

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
stats = load_json(STATS_FILE, {
    "date": now_ymd(),
    "win": 0,
    "loss": 0,
    "total": 0,
    "sent": False
})

def reset_stats_if_new_day():
    global stats
    today = now_ymd()
    if stats.get("date") != today:
        stats = {"date": today, "win": 0, "loss": 0, "total": 0, "sent": False}
        save_json(STATS_FILE, stats)

def get_candles(symbol, interval="15min", size=120):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": size, "apikey": API_KEY}
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

def pip_size(symbol):
    if "JPY" in symbol:
        return 0.01
    if "XAU" in symbol:
        return 0.1
    return 0.0001

def pips_profit(symbol, entry, target, side):
    pip = pip_size(symbol)
    diff = target - entry if side == "BUY" else entry - target
    return round(diff / pip, 1)

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
        tp4 = price + a * 2.8
        tp5 = price + a * 3.5
        sl = price - a * 1.2
    else:
        tp1 = price - a * 0.8
        tp2 = price - a * 1.4
        tp3 = price - a * 2.0
        tp4 = price - a * 2.8
        tp5 = price - a * 3.5
        sl = price + a * 1.2

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(price, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "tp4": round(tp4, 5),
        "tp5": round(tp5, 5),
        "sl": round(sl, 5),
        "score": min(score, 95),
        "hit": [],
        "time": datetime.utcnow().timestamp()
    }

def build_trade_text(t):
    lines = []
    lines.append("🚀 توصية فوركس قوية\n")
    lines.append(f"📊 الزوج: {html.escape(t['symbol'])}")
    lines.append(f"📈 الاتجاه: {t['side']}")
    lines.append(f"🔥 قوة التحليل: {t['score']}/100\n")
    lines.append(f"🎯 الدخول: {t['entry']}\n")

    for tp in ["tp1", "tp2", "tp3", "tp4", "tp5"]:
        label = tp.upper()
        value = t[tp]
        if tp in t.get("hit", []):
            lines.append(f"<s>✅ {label}: {value}</s> ✔️")
        else:
            lines.append(f"✅ {label}: {value}")

    lines.append(f"\n🛑 SL: {t['sl']}")

    if len(t.get("hit", [])) >= 5:
        lines.append("\n🏆 تم تحقيق جميع الأهداف بنجاح")

    lines.append("\n⚠️ التزم بإدارة رأس المال")
    return "\n".join(lines)

def make_target_image(symbol, target, pips):
    img = Image.new("RGB", (900, 600), (20, 25, 35))
    d = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("DejaVuSans.ttf", 48)
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except:
        font_big = font = None

    d.text((60, 50), "FOREX VIP RESULT", fill=(255, 215, 120), font=font_big)
    d.text((60, 150), f"Pair: {symbol}", fill="white", font=font)
    d.text((60, 230), f"Target: {target}", fill=(80, 255, 120), font=font)
    d.text((60, 310), f"Profit: +{pips} Pips", fill=(255, 215, 120), font=font)
    d.text((60, 410), "Result: TARGET HIT", fill=(80, 255, 120), font=font)

    bio = BytesIO()
    bio.name = "target_result.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def make_daily_image():
    total = stats["total"]
    win = stats["win"]
    loss = stats["loss"]
    rate = round((win / total) * 100, 2) if total else 0

    img = Image.new("RGB", (900, 600), (20, 25, 35))
    d = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("DejaVuSans.ttf", 48)
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except:
        font_big = font = None

    d.text((60, 50), "DAILY FOREX STATS", fill=(255, 215, 120), font=font_big)
    d.text((60, 150), f"Date: {stats['date']}", fill="white", font=font)
    d.text((60, 240), f"Total trades: {total}", fill="white", font=font)
    d.text((60, 310), f"Winning: {win}", fill=(80, 255, 120), font=font)
    d.text((60, 380), f"Losing: {loss}", fill=(255, 80, 80), font=font)
    d.text((60, 460), f"Success Rate: {rate}%", fill=(255, 215, 120), font=font)

    bio = BytesIO()
    bio.name = "daily_stats.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

async def send_trade(t):
    msg = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=build_trade_text(t),
        parse_mode="HTML"
    )
    t["message_id"] = msg.message_id

def hit_price(side, price, level):
    return price >= level if side == "BUY" else price <= level

def hit_sl(side, price, sl):
    return price <= sl if side == "BUY" else price >= sl

async def send_target_result(symbol, tp_name, pips):
    text = f"🎯 تم تحقيق {tp_name} لصفقة {symbol}\n💰 الربح: +{pips} نقطة"
    await bot.send_message(chat_id=CHANNEL_ID, text=text)
    img = make_target_image(symbol, tp_name, pips)
    await bot.send_photo(chat_id=CHANNEL_ID, photo=img)

async def send_full_targets(symbol):
    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🏆 تم تحقيق جميع أهداف صفقة {symbol}\n✅ 5/5 أهداف محققة"
    )

async def send_daily_stats():
    img = make_daily_image()
    await bot.send_photo(chat_id=CHANNEL_ID, photo=img)

async def main():
    await bot.send_message(chat_id=CHANNEL_ID, text="✅ بوت الفوركس اشتغل 24 ساعة وينتظر فرص قوية")
    last_signal_time = {}

    while True:
        try:
            reset_stats_if_new_day()

            now_local = datetime.utcnow() + timedelta(hours=3)

            if now_local.hour == 23 and now_local.minute >= 59 and not stats.get("sent"):
                await send_daily_stats()
                stats["sent"] = True
                save_json(STATS_FILE, stats)

            for symbol in SYMBOLS:
                candles = get_candles(symbol, size=20)
                if not candles:
                    continue

                price = candles[-1]["close"]

                if symbol in open_trades:
                    t = open_trades[symbol]

                    for tp in ["tp1", "tp2", "tp3", "tp4", "tp5"]:
                        if tp not in t["hit"] and hit_price(t["side"], price, t[tp]):
                            t["hit"].append(tp)

                            await bot.edit_message_text(
                                chat_id=CHANNEL_ID,
                                message_id=t["message_id"],
                                text=build_trade_text(t),
                                parse_mode="HTML"
                            )

                            pips = pips_profit(symbol, t["entry"], t[tp], t["side"])
                            await send_target_result(symbol, tp.upper(), pips)

                            if tp == "tp5":
                                await send_full_targets(symbol)
                                stats["win"] += 1
                                stats["total"] += 1
                                del open_trades[symbol]
                            else:
                                open_trades[symbol] = t

                            save_json(DATA_FILE, open_trades)
                            save_json(STATS_FILE, stats)
                            break

                    if symbol in open_trades and hit_sl(open_trades[symbol]["side"], price, open_trades[symbol]["sl"]):
                        await bot.send_message(chat_id=CHANNEL_ID, text=f"❌ تم ضرب وقف الخسارة لصفقة {symbol}")
                        stats["loss"] += 1
                        stats["total"] += 1
                        del open_trades[symbol]
                        save_json(DATA_FILE, open_trades)
                        save_json(STATS_FILE, stats)

                else:
                    now_ts = datetime.utcnow().timestamp()
                    if now_ts - last_signal_time.get(symbol, 0) < 3600:
                        continue

                    t = analyze(symbol)
                    if t:
                        open_trades[symbol] = t
                        await send_trade(t)
                        save_json(DATA_FILE, open_trades)
                        last_signal_time[symbol] = now_ts

                await asyncio.sleep(5)

            await asyncio.sleep(60)

        except Exception as e:
            print("ERROR:", e)
            await asyncio.sleep(60)

asyncio.run(main())
