import asyncio
import aiohttp
import logging
import os
import json
from datetime import datetime
from typing import Optional, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════
TG_TOKEN = os.environ.get("ARB_BOT_TOKEN", "")
CHAT_ID = None

# API ключи бирж (из переменных окружения)
BINANCE_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BYBIT_KEY      = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET   = os.environ.get("BYBIT_API_SECRET", "")
OKX_KEY        = os.environ.get("OKX_API_KEY", "")
OKX_SECRET     = os.environ.get("OKX_API_SECRET", "")
OKX_PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")
BITGET_KEY     = os.environ.get("BITGET_API_KEY", "")
BITGET_SECRET  = os.environ.get("BITGET_API_SECRET", "")

# Параметры торговли
MIN_PROFIT_PCT  = float(os.environ.get("MIN_PROFIT_PCT", "0.3"))   # минимальная прибыль %
MIN_VOLUME_USDT = float(os.environ.get("MIN_VOLUME_USDT", "100"))  # минимальный объём $
MAX_TRADE_USDT  = float(os.environ.get("MAX_TRADE_USDT", "500"))   # максимальный объём $
SCAN_INTERVAL   = int(os.environ.get("SCAN_INTERVAL", "2"))        # секунд между сканами

# Комиссии бирж (maker/taker %)
FEES = {
    "Binance": 0.10,
    "Bybit":   0.10,
    "OKX":     0.10,
    "Bitget":  0.10,
}

# Торговые пары
SYMBOLS = ["BTC", "ETH", "SOL", "USDT"]
QUOTE   = "USDT"

# Режим работы
SIMULATION_MODE = os.environ.get("SIMULATION_MODE", "true").lower() == "true"

# Статистика
stats = {
    "scans": 0,
    "signals": 0,
    "trades_sim": 0,
    "profit_sim": 0.0,
    "errors": 0,
    "start_time": datetime.now(),
}

# История сделок (в памяти)
trade_history: List[dict] = []


# ═══════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════

async def send_tg(session, text):
    if not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.error(f"TG send error: {e}")


async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        async with session.get(url, params={"offset": offset, "timeout": 30},
                               timeout=aiohttp.ClientTimeout(total=35)) as r:
            data = await r.json()
            return data.get("result", [])
    except:
        return []


# ═══════════════════════════════════════
# ПОЛУЧЕНИЕ ЦЕН (PUBLIC API)
# ═══════════════════════════════════════

async def get_binance_prices(session) -> Dict[str, float]:
    """Цены с Binance Spot"""
    try:
        async with session.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            prices = {}
            for item in data:
                symbol = item.get("symbol", "")
                if symbol.endswith(QUOTE):
                    base = symbol[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bidPrice", 0)),
                            "ask": float(item.get("askPrice", 0)),
                            "exchange": "Binance"
                        }
            return prices
    except Exception as e:
        logger.error(f"Binance prices error: {e}")
        return {}


async def get_bybit_prices(session) -> Dict[str, float]:
    """Цены с Bybit Spot"""
    try:
        async with session.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot"},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            prices = {}
            for item in data.get("result", {}).get("list", []):
                symbol = item.get("symbol", "")
                if symbol.endswith(QUOTE):
                    base = symbol[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bid1Price", 0)),
                            "ask": float(item.get("ask1Price", 0)),
                            "exchange": "Bybit"
                        }
            return prices
    except Exception as e:
        logger.error(f"Bybit prices error: {e}")
        return {}


async def get_okx_prices(session) -> Dict[str, float]:
    """Цены с OKX Spot"""
    try:
        async with session.get(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SPOT"},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            prices = {}
            for item in data.get("data", []):
                inst_id = item.get("instId", "")
                if inst_id.endswith(f"-{QUOTE}"):
                    base = inst_id[:-len(f"-{QUOTE}")]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bidPx", 0)),
                            "ask": float(item.get("askPx", 0)),
                            "exchange": "OKX"
                        }
            return prices
    except Exception as e:
        logger.error(f"OKX prices error: {e}")
        return {}


async def get_bitget_prices(session) -> Dict[str, float]:
    """Цены с Bitget Spot"""
    try:
        async with session.get(
            "https://api.bitget.com/api/v2/spot/market/tickers",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            prices = {}
            for item in data.get("data", []):
                symbol = item.get("symbol", "")
                if symbol.endswith(QUOTE):
                    base = symbol[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("buyOne", 0)),
                            "ask": float(item.get("sellOne", 0)),
                            "exchange": "Bitget"
                        }
            return prices
    except Exception as e:
        logger.error(f"Bitget prices error: {e}")
        return {}


# ═══════════════════════════════════════
# ПРОВЕРКА БАЛАНСОВ (ТРЕБУЕТ API КЛЮЧИ)
# ═══════════════════════════════════════

async def check_balances(session) -> Dict[str, float]:
    """Проверяет балансы на биржах (симуляция если нет ключей)"""
    if SIMULATION_MODE or not BINANCE_KEY:
        return {
            "Binance_USDT": 1000.0,
            "Bybit_USDT": 1000.0,
            "OKX_USDT": 1000.0,
            "Bitget_USDT": 1000.0,
        }
    # TODO: реальные запросы с подписью
    return {}


# ═══════════════════════════════════════
# ПОИСК АРБИТРАЖА
# ═══════════════════════════════════════

def calc_profit(buy_price, sell_price, buy_ex, sell_ex, volume_usdt):
    """Рассчитывает чистую прибыль с учётом комиссий"""
    buy_fee_pct  = FEES.get(buy_ex, 0.1) / 100
    sell_fee_pct = FEES.get(sell_ex, 0.1) / 100

    coins = volume_usdt / buy_price
    buy_cost  = volume_usdt * (1 + buy_fee_pct)
    sell_recv = coins * sell_price * (1 - sell_fee_pct)

    gross_profit = sell_recv - buy_cost
    gross_pct    = (sell_price - buy_price) / buy_price * 100
    net_pct      = gross_pct - buy_fee_pct * 100 - sell_fee_pct * 100

    return {
        "gross_pct": round(gross_pct, 4),
        "net_pct":   round(net_pct, 4),
        "profit_usdt": round(gross_profit, 4),
        "coins": round(coins, 6),
    }


def find_arbitrage(all_prices: Dict[str, Dict]) -> List[dict]:
    """Ищет арбитражные возможности между биржами"""
    opportunities = []

    for symbol, exchanges in all_prices.items():
        ex_list = list(exchanges.items())

        for i in range(len(ex_list)):
            for j in range(len(ex_list)):
                if i == j:
                    continue

                buy_ex,  buy_data  = ex_list[i]
                sell_ex, sell_data = ex_list[j]

                buy_price  = buy_data.get("ask", 0)
                sell_price = sell_data.get("bid", 0)

                if buy_price <= 0 or sell_price <= 0:
                    continue

                result = calc_profit(buy_price, sell_price, buy_ex, sell_ex, MAX_TRADE_USDT)

                if result["net_pct"] >= MIN_PROFIT_PCT:
                    opportunities.append({
                        "symbol":     symbol,
                        "buy_ex":     buy_ex,
                        "sell_ex":    sell_ex,
                        "buy_price":  buy_price,
                        "sell_price": sell_price,
                        "net_pct":    result["net_pct"],
                        "gross_pct":  result["gross_pct"],
                        "profit_usdt": result["profit_usdt"],
                        "coins":      result["coins"],
                        "volume_usdt": MAX_TRADE_USDT,
                        "time":       datetime.now().strftime("%H:%M:%S"),
                    })

    opportunities.sort(key=lambda x: x["net_pct"], reverse=True)
    return opportunities


def format_opportunity(opp: dict) -> str:
    mode_str = "🔵 СИМУЛЯЦИЯ" if SIMULATION_MODE else "🔴 РЕАЛЬНАЯ СДЕЛКА"
    return (
        f"🚨 *АРБИТРАЖ: {opp['buy_ex']} → {opp['sell_ex']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{mode_str}\n\n"
        f"💱 *Пара:* {opp['symbol']}/{QUOTE}\n\n"
        f"📥 *КУПИТЬ на {opp['buy_ex']}*\n"
        f"   Цена: `{opp['buy_price']} {QUOTE}`\n"
        f"   Объём: `{opp['volume_usdt']} {QUOTE}`\n"
        f"   Получишь: `{opp['coins']} {opp['symbol']}`\n\n"
        f"📤 *ПРОДАТЬ на {opp['sell_ex']}*\n"
        f"   Цена: `{opp['sell_price']} {QUOTE}`\n\n"
        f"📊 *Расчёт:*\n"
        f"   Спред (gross): `{opp['gross_pct']}%`\n"
        f"   После комиссий: `{opp['net_pct']}%`\n"
        f"   Прибыль: `~{opp['profit_usdt']} {QUOTE}`\n\n"
        f"⚠️ Цена актуальна только в момент получения!\n"
        f"⚠️ Проверь баланс перед входом!\n\n"
        f"🕐 {opp['time']}"
    )


# ═══════════════════════════════════════
# ВЫПОЛНЕНИЕ СДЕЛКИ (СИМУЛЯЦИЯ)
# ═══════════════════════════════════════

async def execute_trade(session, opp: dict):
    """Выполняет сделку (симуляция или реальная)"""
    trade = {
        "id": len(trade_history) + 1,
        "time": datetime.now().isoformat(),
        "symbol": opp["symbol"],
        "buy_ex": opp["buy_ex"],
        "sell_ex": opp["sell_ex"],
        "buy_price": opp["buy_price"],
        "sell_price": opp["sell_price"],
        "volume_usdt": opp["volume_usdt"],
        "net_pct": opp["net_pct"],
        "profit_usdt": opp["profit_usdt"],
        "mode": "simulation" if SIMULATION_MODE else "real",
        "status": "executed",
    }

    if SIMULATION_MODE:
        trade_history.append(trade)
        stats["trades_sim"] += 1
        stats["profit_sim"] += opp["profit_usdt"]
        logger.info(f"SIM TRADE #{trade['id']}: {opp['symbol']} {opp['buy_ex']}→{opp['sell_ex']} profit={opp['profit_usdt']:.4f}")
        return trade, None

    # Реальная торговля — TODO: добавить реальные API вызовы с подписью
    error = "Реальная торговля требует настройки API ключей и подписей"
    logger.warning(error)
    return trade, error


# ═══════════════════════════════════════
# ОСНОВНОЙ ЦИКЛ СКАНИРОВАНИЯ
# ═══════════════════════════════════════

async def scan_cycle(session):
    """Один цикл сканирования всех бирж"""
    stats["scans"] += 1

    # Получаем цены параллельно
    results = await asyncio.gather(
        get_binance_prices(session),
        get_bybit_prices(session),
        get_okx_prices(session),
        get_bitget_prices(session),
        return_exceptions=True
    )

    # Объединяем цены по символу
    all_prices: Dict[str, Dict] = {}
    exchange_names = ["Binance", "Bybit", "OKX", "Bitget"]

    active_exchanges = []
    for i, (ex_name, result) in enumerate(zip(exchange_names, results)):
        if isinstance(result, Exception) or not result:
            continue
        active_exchanges.append(ex_name)
        for symbol, price_data in result.items():
            if symbol not in all_prices:
                all_prices[symbol] = {}
            all_prices[symbol][ex_name] = price_data

    if len(active_exchanges) < 2:
        logger.warning(f"Только {len(active_exchanges)} бирж доступно: {active_exchanges}")
        return [], active_exchanges

    # Ищем арбитраж
    opportunities = find_arbitrage(all_prices)

    if opportunities:
        stats["signals"] += len(opportunities)

    return opportunities, active_exchanges


# ═══════════════════════════════════════
# КОМАНДЫ TELEGRAM
# ═══════════════════════════════════════

async def handle_command(session, text, chat_id):
    global CHAT_ID
    CHAT_ID = chat_id
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd == "/start":
        mode = "🔵 СИМУЛЯЦИЯ" if SIMULATION_MODE else "🔴 РЕАЛЬНАЯ ТОРГОВЛЯ"
        await send_tg(session,
            f"✅ *TriangleArbBot запущен!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Режим: {mode}\n"
            f"Площадки: Binance, Bybit, OKX, Bitget\n"
            f"Пары: BTC, ETH, SOL / USDT\n\n"
            f"⚙️ *Параметры:*\n"
            f"   Мин. прибыль: `{MIN_PROFIT_PCT}%`\n"
            f"   Объём сделки: `{MAX_TRADE_USDT} USDT`\n"
            f"   Интервал скана: `{SCAN_INTERVAL} сек`\n\n"
            f"Команды:\n"
            f"/scan — скан прямо сейчас\n"
            f"/prices — текущие цены\n"
            f"/stats — статистика\n"
            f"/history — последние сделки\n"
            f"/mode — переключить симуляция/реал\n"
            f"/setprofit 0.5 — мин. прибыль %\n"
            f"/setvolume 200 — объём сделки\n"
            f"/help — помощь"
        )

    elif cmd == "/scan":
        await send_tg(session, "🔍 Сканирую биржи...")
        opps, active = await scan_cycle(session)

        if not opps:
            await send_tg(session,
                f"😔 Нет сигналов (порог {MIN_PROFIT_PCT}%).\n\n"
                f"Активных бирж: {len(active)} ({', '.join(active)})\n"
                f"Всего сканов: {stats['scans']}"
            )
        else:
            await send_tg(session, f"✅ Найдено {len(opps)} возможностей:")
            for opp in opps[:3]:
                await send_tg(session, format_opportunity(opp))

    elif cmd == "/prices":
        await send_tg(session, "📊 Получаю цены...")
        results = await asyncio.gather(
            get_binance_prices(session),
            get_bybit_prices(session),
            get_okx_prices(session),
            get_bitget_prices(session),
            return_exceptions=True
        )
        exchange_names = ["Binance", "Bybit", "OKX", "Bitget"]

        msg = f"📊 *ЦЕНЫ — {datetime.now().strftime('%H:%M:%S')}*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for symbol in ["BTC", "ETH", "SOL"]:
            msg += f"*{symbol}/USDT:*\n"
            for ex_name, result in zip(exchange_names, results):
                if isinstance(result, Exception) or not result:
                    msg += f"   {ex_name}: —\n"
                    continue
                data = result.get(symbol)
                if data:
                    msg += f"   {ex_name}: bid=`{data['bid']}` ask=`{data['ask']}`\n"
                else:
                    msg += f"   {ex_name}: —\n"
            msg += "\n"

        await send_tg(session, msg)

    elif cmd == "/stats":
        uptime = datetime.now() - stats["start_time"]
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        mode = "Симуляция 🔵" if SIMULATION_MODE else "Реальная 🔴"

        msg = (
            f"📈 *СТАТИСТИКА*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Режим: {mode}\n"
            f"Аптайм: {hours}ч {minutes}м\n\n"
            f"🔍 Сканов: {stats['scans']}\n"
            f"🎯 Сигналов найдено: {stats['signals']}\n"
            f"✅ Сделок (симуляция): {stats['trades_sim']}\n"
            f"💰 Прибыль (симуляция): {round(stats['profit_sim'], 2)} USDT\n"
            f"❌ Ошибок: {stats['errors']}\n\n"
            f"⚙️ Мин. прибыль: {MIN_PROFIT_PCT}%\n"
            f"⚙️ Объём: {MAX_TRADE_USDT} USDT\n"
            f"⚙️ Интервал: {SCAN_INTERVAL} сек"
        )
        await send_tg(session, msg)

    elif cmd == "/history":
        if not trade_history:
            await send_tg(session, "📋 Нет сделок.")
            return
        msg = "📋 *ПОСЛЕДНИЕ СДЕЛКИ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for t in trade_history[-10:][::-1]:
            sign = "+" if t["profit_usdt"] > 0 else ""
            msg += (
                f"#{t['id']} {t['symbol']} | {t['buy_ex']}→{t['sell_ex']}\n"
                f"   {sign}{t['net_pct']}% | {sign}{t['profit_usdt']} USDT\n"
                f"   {t['time'][:19]}\n\n"
            )
        await send_tg(session, msg)

    elif cmd == "/mode":
        global SIMULATION_MODE
        SIMULATION_MODE = not SIMULATION_MODE
        mode = "🔵 СИМУЛЯЦИЯ" if SIMULATION_MODE else "🔴 РЕАЛЬНАЯ ТОРГОВЛЯ"
        await send_tg(session,
            f"Режим переключён: {mode}\n\n"
            + ("⚠️ В реальном режиме нужны API ключи!" if not SIMULATION_MODE else "")
        )

    elif cmd == "/setprofit":
        if len(parts) < 2:
            await send_tg(session, "Пример: /setprofit 0.5")
            return
        try:
            MIN_PROFIT_PCT = float(parts[1])
            await send_tg(session, f"✅ Мин. прибыль: {MIN_PROFIT_PCT}%")
        except:
            await send_tg(session, "❌ Неверное значение")

    elif cmd == "/setvolume":
        if len(parts) < 2:
            await send_tg(session, "Пример: /setvolume 200")
            return
        try:
            MAX_TRADE_USDT = float(parts[1])
            await send_tg(session, f"✅ Объём сделки: {MAX_TRADE_USDT} USDT")
        except:
            await send_tg(session, "❌ Неверное значение")

    elif cmd == "/help":
        await send_tg(session,
            "🤖 *TriangleArbBot — Справка*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/start — запуск и статус\n"
            "/scan — сканировать биржи сейчас\n"
            "/prices — текущие цены на всех биржах\n"
            "/stats — статистика работы\n"
            "/history — последние 10 сделок\n"
            "/mode — симуляция ↔ реальная торговля\n"
            "/setprofit 0.3 — минимальная прибыль %\n"
            "/setvolume 500 — объём одной сделки USDT\n\n"
            "⚠️ По умолчанию работает в режиме симуляции.\n"
            "Для реальной торговли нужны API ключи."
        )


# ═══════════════════════════════════════
# ОСНОВНЫЕ ЦИКЛЫ
# ═══════════════════════════════════════

async def polling_loop(session):
    offset = 0
    while True:
        updates = await get_updates(session, offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if msg:
                global CHAT_ID
                CHAT_ID = msg["chat"]["id"]
                text = msg.get("text", "")
                if text.startswith("/"):
                    await handle_command(session, text, CHAT_ID)
        await asyncio.sleep(1)


async def scan_loop(session):
    """Основной цикл сканирования каждые N секунд"""
    await asyncio.sleep(15)
    last_signal_time = {}

    while True:
        try:
            opps, active = await scan_cycle(session)

            for opp in opps:
                key = f"{opp['symbol']}-{opp['buy_ex']}-{opp['sell_ex']}"
                last_sent = last_signal_time.get(key, 0)
                now = datetime.now().timestamp()

                # Не спамить одним и тем же сигналом чаще раз в 60 сек
                if now - last_sent > 60:
                    last_signal_time[key] = now
                    if CHAT_ID:
                        await send_tg(session, format_opportunity(opp))

                    # Исполняем сделку (симуляция)
                    trade, err = await execute_trade(session, opp)
                    if err:
                        logger.error(f"Trade error: {err}")

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Scan loop error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)


async def main():
    if not TG_TOKEN:
        logger.error("ARB_BOT_TOKEN не установлен!")
        return

    mode = "СИМУЛЯЦИЯ" if SIMULATION_MODE else "РЕАЛЬНАЯ ТОРГОВЛЯ"
    logger.info(f"TriangleArbBot запущен | {mode} | порог {MIN_PROFIT_PCT}%")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(
            polling_loop(session),
            scan_loop(session)
        )


if __name__ == "__main__":
    asyncio.run(main())
