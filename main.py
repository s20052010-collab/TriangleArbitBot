import asyncio
import aiohttp
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("ARB_BOT_TOKEN", "")
CHAT_ID = None

FEE = 0.999  # 0.1% комиссия Binance за сделку

TRIANGLES = {
    "USDT": [
        ("BTCUSDT", "ETHBTC", "ETHUSDT"),
        ("BTCUSDT", "BNBBTC", "BNBUSDT"),
        ("ETHUSDT", "BNBETH", "BNBUSDT"),
        ("BTCUSDT", "XRPBTC", "XRPUSDT"),
        ("ETHUSDT", "XRPETH", "XRPUSDT"),
        ("BTCUSDT", "ADABTC", "ADAUSDT"),
        ("ETHUSDT", "ADAETH", "ADAUSDT"),
        ("BTCUSDT", "SOLUSDT", "SOLBTC"),
        ("BTCUSDT", "DOTBTC", "DOTUSDT"),
        ("BTCUSDT", "LINKBTC", "LINKUSDT"),
        ("ETHUSDT", "LINKETH", "LINKUSDT"),
        ("BTCUSDT", "LTCBTC", "LTCUSDT"),
        ("BTCUSDT", "AVAXBTC", "AVAXUSDT"),
        ("ETHUSDT", "AVAXETH", "AVAXUSDT"),
        ("BTCUSDT", "ATOMBTC", "ATOMUSDT"),
        ("BTCUSDT", "NEARBTC", "NEARUSDT"),
        ("BTCUSDT", "MATICBTC", "MATICUSDT"),
        ("BTCUSDT", "DOGEBTC", "DOGEUSDT"),
        ("BTCUSDT", "TRXBTC", "TRXUSDT"),
        ("ETHUSDT", "BNBETH", "BNBUSDT"),
    ],
    "BTC": [
        ("ETHBTC", "BNBETH", "BNBBTC"),
        ("ETHBTC", "ADAETH", "ADABTC"),
        ("ETHBTC", "LINKETH", "LINKBTC"),
        ("ETHBTC", "XRPETH", "XRPBTC"),
        ("ETHBTC", "SOLUSDT", "SOLBTC"),
    ],
    "ETH": [
        ("BNBETH", "BNBBTC", "ETHBTC"),
        ("ADAETH", "ADABTC", "ETHBTC"),
        ("LINKETH", "LINKBTC", "ETHBTC"),
        ("XRPETH", "XRPBTC", "ETHBTC"),
    ],
}

# Настройки пользователя (дефолт)
user_settings = {
    "base": "USDT",
    "capital": 1000,
    "min_margin": 0.3,
}


async def send_message(session, text, chat_id=None):
    cid = chat_id or CHAT_ID
    if not cid:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": cid,
            "text": text,
            "parse_mode": "Markdown"
        })
    except Exception as e:
        logger.error(f"Send error: {e}")


async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        async with session.get(url, params={"offset": offset, "timeout": 30}) as r:
            data = await r.json()
            return data.get("result", [])
    except:
        return []


async def fetch_prices(session):
    url = "https://api.binance.com/api/v3/ticker/bookTicker"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            prices = {}
            for d in data:
                bid = float(d.get("bidPrice", 0))
                ask = float(d.get("askPrice", 0))
                if bid > 0 and ask > 0:
                    prices[d["symbol"]] = {"bid": bid, "ask": ask}
            return prices
    except Exception as e:
        logger.error(f"Fetch prices error: {e}")
        return {}


def calc_triangle(t, base, capital, prices):
    s1, s2, s3 = t
    p1 = prices.get(s1)
    p2 = prices.get(s2)
    p3 = prices.get(s3)
    if not p1 or not p2 or not p3:
        return None

    try:
        amount = float(capital)

        # Шаг 1: base → coin1
        if s1.endswith(base):
            coin1 = s1[:-len(base)]
            amount = (amount / p1["ask"]) * FEE
        elif s1.startswith(base):
            coin1 = s1[len(base):]
            amount = amount * p1["bid"] * FEE
        else:
            return None

        # Шаг 2: coin1 → coin2
        if s2.startswith(coin1):
            coin2 = s2[len(coin1):]
            amount = (amount / p2["ask"]) * FEE
        elif s2.endswith(coin1):
            coin2 = s2[:-len(coin1)]
            amount = amount * p2["bid"] * FEE
        else:
            return None

        # Шаг 3: coin2 → base
        if s3.startswith(coin2):
            amount = amount * p3["bid"] * FEE
        elif s3.endswith(coin2):
            amount = (amount / p3["ask"]) * FEE
        else:
            return None

        profit = amount - capital
        pct = (profit / capital) * 100

        return {
            "chain": f"{s1} → {s2} → {s3}",
            "pct": round(pct, 3),
            "profit": round(profit, 4),
            "end": round(amount, 4),
        }
    except:
        return None


async def scan_triangles(session, base=None, capital=None, min_margin=None):
    base = base or user_settings["base"]
    capital = capital or user_settings["capital"]
    min_margin = min_margin if min_margin is not None else user_settings["min_margin"]

    prices = await fetch_prices(session)
    if not prices:
        return None, []

    tris = TRIANGLES.get(base, [])
    results = []
    for t in tris:
        r = calc_triangle(t, base, capital, prices)
        if r:
            results.append(r)

    results.sort(key=lambda x: x["pct"], reverse=True)
    profitable = [r for r in results if r["pct"] >= min_margin]
    return results, profitable


def format_scan_result(results, profitable, base, capital, min_margin):
    if not results:
        return "❌ Не удалось получить данные с Binance. Попробуй позже."

    best = results[0]
    icon = "🟢" if best["pct"] > 0 else "🔴"

    text = (
        f"🔺 *ТРЕУГОЛЬНЫЙ АРБИТРАЖ — Binance*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💱 База: *{base}* | Капитал: *{capital} {base}*\n"
        f"📊 Проверено треугольников: *{len(results)}*\n"
        f"✅ Прибыльных (≥{min_margin}%): *{len(profitable)}*\n\n"
    )

    if profitable:
        text += f"🏆 *ЛУЧШИЕ ЦЕПОЧКИ:*\n\n"
        for i, r in enumerate(profitable[:5], 1):
            sign = "+" if r["pct"] > 0 else ""
            text += (
                f"*{i}. {r['chain']}*\n"
                f"   Маржа: `{sign}{r['pct']}%`\n"
                f"   Старт: {capital} {base} → Итог: {r['end']} {base}\n"
                f"   Прибыль: `{sign}{r['profit']} {base}`\n\n"
            )
    else:
        text += f"{icon} *Лучшая цепочка:*\n"
        text += f"`{best['chain']}`\n"
        sign = "+" if best["pct"] > 0 else ""
        text += f"Маржа: `{sign}{best['pct']}%`\n\n"
        text += f"⚠️ Прибыльных цепочек с маржой ≥{min_margin}% не найдено.\nСнизь порог командой /setmargin\n"

    text += f"🕐 {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
    return text


def settings_text():
    return (
        f"⚙️ *ТЕКУЩИЕ НАСТРОЙКИ*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💱 Базовая валюта: *{user_settings['base']}*\n"
        f"💵 Капитал: *{user_settings['capital']} {user_settings['base']}*\n"
        f"📈 Мин. маржа: *{user_settings['min_margin']}%*\n\n"
        f"Команды для изменения:\n"
        f"`/setbase USDT` — сменить базу (USDT/BTC/ETH)\n"
        f"`/setcapital 5000` — сменить капитал\n"
        f"`/setmargin 0.5` — сменить мин. маржу %\n"
    )


HELP_TEXT = """
🤖 *TRIANGLE ARB BOT — Binance*
━━━━━━━━━━━━━━━━━━━━━━

Команды:
/start — запустить бота
/scan — сканировать треугольники сейчас
/top — топ-10 лучших цепочек
/settings — текущие настройки
/setbase USDT — сменить базу (USDT/BTC/ETH)
/setcapital 1000 — сменить капитал
/setmargin 0.3 — мин. маржа в %
/help — помощь

Бот проверяет 20 треугольных цепочек.
Комиссия Binance 0.1% за сделку уже учтена.
"""


async def handle_command(session, text, chat_id):
    global CHAT_ID
    CHAT_ID = chat_id
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd == "/start":
        await send_message(session,
            "✅ *Triangle Arb Bot запущен!*\n\n"
            "Ищу треугольные арбитражные возможности на Binance.\n\n"
            + settings_text()
        )

    elif cmd == "/scan":
        await send_message(session, "🔍 Сканирую треугольники на Binance...")
        results, profitable = await scan_triangles(session)
        if results is None:
            await send_message(session, "❌ Ошибка получения данных. Попробуй позже.")
            return
        msg = format_scan_result(
            results, profitable,
            user_settings["base"],
            user_settings["capital"],
            user_settings["min_margin"]
        )
        await send_message(session, msg)

    elif cmd == "/top":
        await send_message(session, "📊 Загружаю топ цепочек...")
        results, _ = await scan_triangles(session, min_margin=-999)
        if not results:
            await send_message(session, "❌ Ошибка получения данных.")
            return
        base = user_settings["base"]
        capital = user_settings["capital"]
        text_out = f"📊 *ТОП-10 ЦЕПОЧЕК — {base}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for i, r in enumerate(results[:10], 1):
            sign = "+" if r["pct"] > 0 else ""
            icon = "🟢" if r["pct"] > 0 else "🔴"
            text_out += f"{icon} *{i}. {r['chain']}*\n   `{sign}{r['pct']}%` | Прибыль: {sign}{r['profit']} {base}\n\n"
        text_out += f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        await send_message(session, text_out)

    elif cmd == "/settings":
        await send_message(session, settings_text())

    elif cmd == "/setbase":
        if len(parts) < 2:
            await send_message(session, "⚠️ Укажи базу: `/setbase USDT` или `/setbase BTC` или `/setbase ETH`")
            return
        base = parts[1].upper()
        if base not in TRIANGLES:
            await send_message(session, f"❌ Доступные базы: {', '.join(TRIANGLES.keys())}")
            return
        user_settings["base"] = base
        await send_message(session, f"✅ Базовая валюта изменена на *{base}*")

    elif cmd == "/setcapital":
        if len(parts) < 2:
            await send_message(session, "⚠️ Укажи капитал: `/setcapital 5000`")
            return
        try:
            cap = float(parts[1])
            if cap <= 0:
                raise ValueError
            user_settings["capital"] = cap
            await send_message(session, f"✅ Капитал изменён на *{cap} {user_settings['base']}*")
        except:
            await send_message(session, "❌ Неверное значение. Пример: `/setcapital 5000`")

    elif cmd == "/setmargin":
        if len(parts) < 2:
            await send_message(session, "⚠️ Укажи маржу: `/setmargin 0.5`")
            return
        try:
            margin = float(parts[1])
            user_settings["min_margin"] = margin
            await send_message(session, f"✅ Минимальная маржа изменена на *{margin}%*")
        except:
            await send_message(session, "❌ Неверное значение. Пример: `/setmargin 0.5`")

    elif cmd == "/help":
        await send_message(session, HELP_TEXT)

    else:
        await send_message(session,
            "❓ Неизвестная команда. Напиши /help для списка команд."
        )


async def polling_loop(session):
    offset = 0
    while True:
        updates = await get_updates(session, offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if msg:
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")
                if text.startswith("/"):
                    await handle_command(session, text, chat_id)
        await asyncio.sleep(1)


async def main():
    if not TOKEN:
        logger.error("ARB_BOT_TOKEN не установлен!")
        return

    logger.info("Triangle Arb Bot запущен | Binance | USDT/BTC/ETH")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await polling_loop(session)


if __name__ == "__main__":
    asyncio.run(main())
