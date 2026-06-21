import requests, time, json, os, asyncio
from telegram import Bot

BOT_TOKEN = "8916572820:AAFmWoJhFOXnjwGU638SFMGHtdOLRBS0HkA"
API_KEY = "9f15ada892ae4fdc887e62de9b2ba265"
CHANNEL_ID = -1004359509046

SYMBOLS = [
    "XAU/USD","EUR/USD","GBP/USD","USD/JPY","USD/CHF",
    "USD/CAD","AUD/USD","NZD/USD","EUR/JPY","GBP/JPY"
]

open_trades = {}
stats = {"win": 0, "loss": 0, "total": 0}

bot = Bot(BOT_TOKEN)

def get_candles(symbol):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "15min",
        "outputsize": 80,
        "apikey": API_KEY
    }
    data = requests.get(url, params=params, timeout=20).json()
    if "values" not in data:
        return None
    candles = list(reversed(data["values"]))
    return [float(c["close"]) for c in candles]

def ema(prices, period):
    k = 2 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e

def rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    prices = get_candles(symbol)
    if not prices or len(prices) < 60:
        return None

    price = prices[-1]
    ema20 = ema(prices[-40:], 20)
    ema50 = ema(prices[-70:], 50)
    r = rsi(prices)

    if price > ema20 > ema50 and r < 70:
        side = "BUY"
    elif price < ema20 < ema50 and r > 30:
        side = "SELL"
    else:
        return None

    risk = price * 0.0025

    if side == "BUY":
        sl = price - risk
        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 4
    else:
        sl = price + risk
        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 4

    return {
        "symbol": symbol,
        "side": side,
        "entry": round(price, 5),
        "sl": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "hit": []
    }

async def send_trade(t):
    msg = f"""🚀 توصية فوركس جديدة

📊 الزوج: {t['symbol']}
📈 الاتجاه: {t['side']}

🎯 الدخول: {t['entry']}
✅ TP1: {t['tp1']}
✅ TP2: {t['tp2']}
✅ TP3: {t['tp3']}
🛑 SL: {t['sl']}

⚠️ إدارة رأس المال مهمة، الصفقة تحليل آلي وليست ضمان ربح."""
    await bot.send_message(CHANNEL_ID, msg)

async def send_result(text):
    await bot.send_message(CHANNEL_ID, text)

def hit_price(side, price, level):
    return price >= level if side == "BUY" else price <= level

def hit_sl(side, price, sl):
    return price <= sl if side == "BUY" else price >= sl

async def main():
    await bot.send_message(CHANNEL_ID, "✅ تم تشغيل بوت توصيات الفوركس الآلي")

    while True:
        try:
            for symbol in SYMBOLS:
                prices = get_candles(symbol)
                if not prices:
                    continue
                price = prices[-1]

                if symbol in open_trades:
                    t = open_trades[symbol]

                    for tp in ["tp1", "tp2", "tp3"]:
                        if tp not in t["hit"] and hit_price(t["side"], price, t[tp]):
                            t["hit"].append(tp)
                            await send_result(f"✅ تحقق {tp.upper()}\n\n📊 {symbol}\n📈 {t['side']}\n🎯 السعر: {round(price,5)}")

                    if hit_sl(t["side"], price, t["sl"]):
                        stats["loss"] += 1
                        stats["total"] += 1
                        await send_result(f"❌ ضرب وقف الخسارة\n\n📊 {symbol}\n🛑 السعر: {round(price,5)}")
                        del open_trades[symbol]

                    elif "tp3" in t["hit"]:
                        stats["win"] += 1
                        stats["total"] += 1
                        await send_result(f"🏆 اكتملت الصفقة بنجاح\n\n📊 {symbol}\n✅ TP1 + TP2 + TP3")
                        del open_trades[symbol]

                else:
                    t = analyze(symbol)
                    if t:
                        open_trades[symbol] = t
                        await send_trade(t)

                time.sleep(8)

            if stats["total"] > 0:
                rate = round((stats["win"] / stats["total"]) * 100, 2)
                await send_result(f"📊 إحصائيات البوت\n\nالصفقات: {stats['total']}\nالرابحة: {stats['win']}\nالخاسرة: {stats['loss']}\nنسبة النجاح: {rate}%")

            await asyncio.sleep(1200)

        except Exception as e:
            await send_result(f"⚠️ خطأ في البوت:\n{e}")
            await asyncio.sleep(60)

asyncio.run(main())
