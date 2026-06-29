import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════
TG_TOKEN = os.environ.get("ARB_BOT_TOKEN", "")
CHAT_ID = None

BINANCE_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BYBIT_KEY      = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET   = os.environ.get("BYBIT_API_SECRET", "")
OKX_KEY        = os.environ.get("OKX_API_KEY", "")
OKX_SECRET     = os.environ.get("OKX_API_SECRET", "")
BITGET_KEY     = os.environ.get("BITGET_API_KEY", "")
BITGET_SECRET  = os.environ.get("BITGET_API_SECRET", "")

# Параметры (можно менять через команды бота)
config = {
    "min_profit_pct":  float(os.environ.get("MIN_PROFIT_PCT", "0.3")),
    "max_trade_usdt":  float(os.environ.get("MAX_TRADE_USDT", "100")),
    "scan_interval":   int(os.environ.get("SCAN_INTERVAL", "2")),
    "simulation_mode": os.environ.get("SIMULATION_MODE", "true").lower() == "true",
}

FEES = {"Binance": 0.10, "Bybit": 0.10, "OKX": 0.10, "Bitget": 0.10}
SYMBOLS = ["BTC", "ETH", "SOL"]
QUOTE   = "USDT"

stats = {
    "scans": 0,
    "signals": 0,
    "trades_sim": 0,
    "profit_sim": 0.0,
    "errors": 0,
    "start_time": datetime.now(),
}
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
        logger.error(f"TG error: {e}")


async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        async with session.get(url,
            params={"offset": offset, "timeout": 30},
            timeout=aiohttp.ClientTimeout(total=35)) as r:
            data = await r.json()
            return data.get("result", [])
    except:
        return []


# ═══════════════════════════════════════
# ЦЕНЫ С БИРЖ
# ═══════════════════════════════════════

async def get_binance_prices(session) -> Dict:
    try:
        async with session.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            prices = {}
            for item in data:
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bidPrice", 0)),
                            "ask": float(item.get("askPrice", 0)),
                            "exchange": "Binance"
                        }
            return prices
    except Exception as e:
        logger.error(f"Binance: {e}")
        return {}


async def get_bybit_prices(session) -> Dict:
    try:
        async with session.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot"},
            timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            prices = {}
            for item in data.get("result", {}).get("list", []):
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bid1Price", 0) or 0),
                            "ask": float(item.get("ask1Price", 0) or 0),
                            "exchange": "Bybit"
                        }
            return prices
    except Exception as e:
        logger.error(f"Bybit: {e}")
        return {}


async def get_okx_prices(session) -> Dict:
    try:
        async with session.get(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SPOT"},
            timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            prices = {}
            for item in data.get("data", []):
                inst = item.get("instId", "")
                if inst.endswith(f"-{QUOTE}"):
                    base = inst[:-len(f"-{QUOTE}")]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("bidPx", 0) or 0),
                            "ask": float(item.get("askPx", 0) or 0),
                            "exchange": "OKX"
                        }
            return prices
    except Exception as e:
        logger.error(f"OKX: {e}")
        return {}


async def get_bitget_prices(session) -> Dict:
    try:
        async with session.get(
            "https://api.bitget.com/api/v2/spot/market/tickers",
            timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            prices = {}
            for item in data.get("data", []):
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        prices[base] = {
                            "bid": float(item.get("buyOne", 0) or 0),
                            "ask": float(item.get("sellOne", 0) or 0),
                            "exchange": "Bitget"
                        }
            return prices
    except Exception as e:
        logger.error(f"Bitget: {e}")
        return {}


# ═══════════════════════════════════════
# ПОИСК АРБИТРАЖА
# ═══════════════════════════════════════

def calc_profit(buy_price, sell_price, buy_ex, sell_ex, volume_usdt):
    buy_fee  = FEES.get(buy_ex,  0.1) / 100
    sell_fee = FEES.get(sell_ex, 0.1) / 100
    coins    = volume_usdt / buy_price
    buy_cost = volume_usdt * (1 + buy_fee)
    sell_recv = coins * sell_price * (1 - sell_fee)
    gross_pct = (sell_price - buy_price) / buy_price * 100
    net_pct   = gross_pct - buy_fee * 100 - sell_fee * 100
    profit    = sell_recv - buy_cost
    return round(gross_pct, 4), round(net_pct, 4), round(profit, 4), round(coins, 6)


def find_arbitrage(all_prices: Dict) -> List[dict]:
    opportunities = []
    vol = config["max_trade_usdt"]
    min_pct = config["min_profit_pct"]

    for symbol, exchanges in all_prices.items():
        ex_list = list(exchanges.items())
        for i in range(len(ex_list)):
            for j in range(len(ex_list)):
                if i == j:
                    continue
                buy_ex,  buy_d  = ex_list[i]
                sell_ex, sell_d = ex_list[j]
                buy_price  = buy_d.get("ask", 0)
                sell_price = sell_d.get("bid", 0)
                if buy_price <= 0 or sell_price <= 0:
                    continue
                gross_pct, net_pct, profit, coins = calc_profit(buy_price, sell_price, buy_ex, sell_ex, vol)
                if net_pct >= min_pct:
                    opportunities.append({
                        "symbol":      symbol,
                        "buy_ex":      buy_ex,
                        "sell_ex":     sell_ex,
                        "buy_price":   buy_price,
                        "sell_price":  sell_price,
                        "gross_pct":   gross_pct,
                        "net_pct":     net_pct,
                        "profit_usdt": profit,
                        "coins":       coins,
                        "volume_usdt": vol,
                        "time":        datetime.now().strftime("%H:%M:%S"),
                    })

    opportunities.sort(key=lambda x: x["net_pct"], reverse=True)
    return opportunities


def format_opportunity(opp: dict) -> str:
    mode_str = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ СДЕЛКА"
    return (
        f"🚨 *АРБИТРАЖ: {opp['buy_ex']} → {opp['sell_ex']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{mode_str}\n\n"
        f"💱 *Пара:* {opp['symbol']}/{QUOTE}\n\n"
        f"📥 *КУПИТЬ на {opp['buy_ex']}*\n"
        f"   Цена ask: `{opp['buy_price']} {QUOTE}`\n"
        f"   Объём: `{opp['volume_usdt']} {QUOTE}`\n"
        f"   Получишь: `{opp['coins']} {opp['symbol']}`\n\n"
        f"📤 *ПРОДАТЬ на {opp['sell_ex']}*\n"
        f"   Цена bid: `{opp['sell_price']} {QUOTE}`\n\n"
        f"📊 *Расчёт:*\n"
        f"   Спред: `{opp['gross_pct']}%`\n"
        f"   После комиссий: `{opp['net_pct']}%`\n"
        f"   💰 Прибыль: `~{opp['profit_usdt']} {QUOTE}`\n\n"
        f"⚠️ Цена актуальна только в момент получения!\n\n"
        f"🕐 {opp['time']}"
    )


# ═══════════════════════════════════════
# ОСНОВНОЙ СКАН
# ═══════════════════════════════════════

async def scan_cycle(session):
    stats["scans"] += 1

    results = await asyncio.gather(
        get_binance_prices(session),
        get_bybit_prices(session),
        get_okx_prices(session),
        get_bitget_prices(session),
        return_exceptions=True
    )

    exchange_names = ["Binance", "Bybit", "OKX", "Bitget"]
    all_prices: Dict = {}
    active = []

    for ex_name, result in zip(exchange_names, results):
        if isinstance(result, Exception) or not result:
            continue
        active.append(ex_name)
        for symbol, price_data in result.items():
            if symbol not in all_prices:
                all_prices[symbol] = {}
            all_prices[symbol][ex_name] = price_data

    if len(active) < 2:
        return [], active, {}

    opps = find_arbitrage(all_prices)
    if opps:
        stats["signals"] += len(opps)

    return opps, active, all_prices


async def execute_sim_trade(opp: dict):
    trade = {
        "id":          len(trade_history) + 1,
        "time":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol":      opp["symbol"],
        "buy_ex":      opp["buy_ex"],
        "sell_ex":     opp["sell_ex"],
        "buy_price":   opp["buy_price"],
        "sell_price":  opp["sell_price"],
        "volume_usdt": opp["volume_usdt"],
        "net_pct":     opp["net_pct"],
        "profit_usdt": opp["profit_usdt"],
    }
    trade_history.append(trade)
    stats["trades_sim"]  += 1
    stats["profit_sim"]  += opp["profit_usdt"]
    logger.info(f"SIM #{trade['id']}: {opp['symbol']} {opp['buy_ex']}→{opp['sell_ex']} +{opp['profit_usdt']} USDT")
    return trade


# ═══════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════

async def handle_command(session, text, chat_id):
    global CHAT_ID
    CHAT_ID = chat_id
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd == "/start":
        mode = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ ТОРГОВЛЯ"
        await send_tg(session,
            f"✅ *TriangleArbBot запущен!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Режим: {mode}\n"
            f"Площадки: Binance, Bybit, OKX, Bitget\n"
            f"Пары: BTC, ETH, SOL / USDT\n\n"
            f"⚙️ *Параметры:*\n"
            f"   Мин. прибыль: `{config['min_profit_pct']}%`\n"
            f"   Объём сделки: `{config['max_trade_usdt']} USDT`\n"
            f"   Интервал: `{config['scan_interval']} сек`\n\n"
            f"Команды:\n"
            f"/scan — скан прямо сейчас\n"
            f"/prices — цены на всех биржах\n"
            f"/stats — статистика\n"
            f"/history — последние сделки\n"
            f"/mode — переключить режим\n"
            f"/setprofit 0.5 — мин. прибыль %\n"
            f"/setvolume 200 — объём сделки USDT\n"
        )

    elif cmd == "/scan":
        await send_tg(session, "🔍 Сканирую биржи...")
        opps, active, _ = await scan_cycle(session)
        if not opps:
            await send_tg(session,
                f"😔 Нет сигналов (порог {config['min_profit_pct']}%).\n\n"
                f"Активных бирж: {len(active)} ({', '.join(active) or 'нет'})\n"
                f"Сканов всего: {stats['scans']}"
            )
        else:
            await send_tg(session, f"✅ Найдено {len(opps)} возможностей:")
            for opp in opps[:3]:
                await send_tg(session, format_opportunity(opp))
                if config["simulation_mode"]:
                    await execute_sim_trade(opp)

    elif cmd == "/prices":
        await send_tg(session, "📊 Получаю цены...")
        results = await asyncio.gather(
            get_binance_prices(session),
            get_bybit_prices(session),
            get_okx_prices(session),
            get_bitget_prices(session),
            return_exceptions=True
        )
        ex_names = ["Binance", "Bybit", "OKX", "Bitget"]
        msg = f"📊 *ЦЕНЫ — {datetime.now().strftime('%H:%M:%S')}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for symbol in SYMBOLS:
            msg += f"*{symbol}/USDT:*\n"
            for ex_name, result in zip(ex_names, results):
                if isinstance(result, Exception) or not result:
                    msg += f"   {ex_name}: —\n"
                    continue
                data = result.get(symbol)
                if data and data.get("ask", 0) > 0:
                    msg += f"   {ex_name}: `{data['ask']}`\n"
                else:
                    msg += f"   {ex_name}: —\n"
            msg += "\n"
        await send_tg(session, msg)

    elif cmd == "/stats":
        uptime = datetime.now() - stats["start_time"]
        h = int(uptime.total_seconds() // 3600)
        m = int((uptime.total_seconds() % 3600) // 60)
        mode = "Симуляция 🔵" if config["simulation_mode"] else "Реальная 🔴"
        await send_tg(session,
            f"📈 *СТАТИСТИКА*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Режим: {mode}\n"
            f"Аптайм: {h}ч {m}м\n\n"
            f"🔍 Сканов: {stats['scans']}\n"
            f"🎯 Сигналов: {stats['signals']}\n"
            f"✅ Сделок (симуляция): {stats['trades_sim']}\n"
            f"💰 Прибыль (симуляция): {round(stats['profit_sim'], 2)} USDT\n"
            f"❌ Ошибок: {stats['errors']}\n\n"
            f"⚙️ Мин. прибыль: {config['min_profit_pct']}%\n"
            f"⚙️ Объём: {config['max_trade_usdt']} USDT\n"
            f"⚙️ Интервал: {config['scan_interval']} сек"
        )

    elif cmd == "/history":
        if not trade_history:
            await send_tg(session, "📋 Нет сделок в этой сессии.")
            return
        msg = "📋 *ПОСЛЕДНИЕ СДЕЛКИ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for t in trade_history[-10:][::-1]:
            sign = "+" if t["profit_usdt"] > 0 else ""
            msg += (
                f"#{t['id']} *{t['symbol']}* | {t['buy_ex']}→{t['sell_ex']}\n"
                f"   {sign}{t['net_pct']}% | {sign}{t['profit_usdt']} USDT\n"
                f"   {t['time']}\n\n"
            )
        await send_tg(session, msg)

    elif cmd == "/mode":
        config["simulation_mode"] = not config["simulation_mode"]
        mode = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ ТОРГОВЛЯ"
        warning = "\n\n⚠️ Для реальной торговли нужны API ключи бирж!" if not config["simulation_mode"] else ""
        await send_tg(session, f"Режим переключён: {mode}{warning}")

    elif cmd == "/setprofit":
        if len(parts) < 2:
            await send_tg(session, "⚠️ Пример: `/setprofit 0.5`")
            return
        try:
            config["min_profit_pct"] = float(parts[1])
            await send_tg(session, f"✅ Мин. прибыль: `{config['min_profit_pct']}%`")
        except:
            await send_tg(session, "❌ Неверное значение. Пример: `/setprofit 0.5`")

    elif cmd == "/setvolume":
        if len(parts) < 2:
            await send_tg(session, "⚠️ Пример: `/setvolume 200`")
            return
        try:
            config["max_trade_usdt"] = float(parts[1])
            await send_tg(session, f"✅ Объём сделки: `{config['max_trade_usdt']} USDT`")
        except:
            await send_tg(session, "❌ Неверное значение. Пример: `/setvolume 200`")

    else:
        await send_tg(session,
            "❓ Неизвестная команда.\n\n"
            "/start — статус и параметры\n"
            "/scan — сканировать биржи\n"
            "/prices — текущие цены\n"
            "/stats — статистика\n"
            "/history — последние сделки\n"
            "/mode — режим симуляция/реал\n"
            "/setprofit 0.3 — мин. прибыль %\n"
            "/setvolume 100 — объём USDT"
        )


# ═══════════════════════════════════════
# ЦИКЛЫ
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
    await asyncio.sleep(15)
    last_signal_time = {}

    while True:
        try:
            opps, active, _ = await scan_cycle(session)
            logger.info(f"Scan #{stats['scans']}: active={active} opps={len(opps)}")

            for opp in opps[:3]:
                key = f"{opp['symbol']}-{opp['buy_ex']}-{opp['sell_ex']}"
                now = datetime.now().timestamp()
                if now - last_signal_time.get(key, 0) > 60:
                    last_signal_time[key] = now
                    if CHAT_ID:
                        await send_tg(session, format_opportunity(opp))
                    if config["simulation_mode"]:
                        await execute_sim_trade(opp)

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Scan loop error: {e}")

        await asyncio.sleep(config["scan_interval"])


async def main():
    if not TG_TOKEN:
        logger.error("ARB_BOT_TOKEN не установлен!")
        return

    mode = "СИМУЛЯЦИЯ" if config["simulation_mode"] else "РЕАЛЬНАЯ"
    logger.info(f"TriangleArbBot запущен | {mode} | порог {config['min_profit_pct']}%")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(
            polling_loop(session),
            scan_loop(session)
        )


if __name__ == "__main__":
    asyncio.run(main())
