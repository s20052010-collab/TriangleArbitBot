import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TG_TOKEN = os.environ.get("ARB_BOT_TOKEN", "")
CHAT_ID = None

config = {
    "min_profit_pct":  float(os.environ.get("MIN_PROFIT_PCT", "0.15")),
    "max_trade_usdt":  float(os.environ.get("MAX_TRADE_USDT", "100")),
    "scan_interval":   int(os.environ.get("SCAN_INTERVAL", "3")),
    "simulation_mode": os.environ.get("SIMULATION_MODE", "true").lower() == "true",
}

FEES = {
    "Binance":  0.10,
    "Bybit":    0.10,
    "OKX":      0.10,
    "Gate.io":  0.20,
    "MEXC":     0.00,
    "KuCoin":   0.10,
    "Bitfinex": 0.10,
    "HTX":      0.20,
    "Kraken":   0.16,
}

SYMBOLS = [
    # Топ монеты
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "TRX",
    "DOT", "AVAX", "LINK", "NEAR", "ATOM", "LTC",
    "MATIC", "FIL", "INJ", "WLD", "SEI", "TIA",
    # L2 / новые
    "ARB", "OP", "SUI", "APT", "ZK", "STRK", "MANTA",
    # DeFi
    "UNI", "AAVE", "CRV", "COMP", "MKR", "SNX", "BAL",
    # AI токены
    "FET", "AGIX", "OCEAN", "RENDER", "TAO", "ARKM",
    # Мем-коины
    "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME",
    # Другие
    "SAND", "MANA", "AXS", "GALA", "ENJ", "CHZ",
    "VET", "HBAR", "ALGO", "XLM", "EOS", "THETA",
    "FTM", "EGLD", "FLOW", "ROSE", "ONE", "ZIL",
]
QUOTE = "USDT"

stats = {
    "scans": 0, "signals": 0,
    "trades_sim": 0, "profit_sim": 0.0,
    "errors": 0, "start_time": datetime.now(),
}
trade_history: List[dict] = []
last_signal_time: Dict[str, float] = {}


async def send_tg(session, text):
    if not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.error(f"TG: {e}")


async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        async with session.get(url,
            params={"offset": offset, "timeout": 30},
            timeout=aiohttp.ClientTimeout(total=35)) as r:
            return (await r.json()).get("result", [])
    except:
        return []


# ═══════════════════════════════════════
# БИРЖИ
# ═══════════════════════════════════════

async def get_binance(session) -> Dict:
    try:
        async with session.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in await r.json():
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        bid = float(item.get("bidPrice", 0) or 0)
                        ask = float(item.get("askPrice", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"Binance: {e}")
        return {}


async def get_bybit(session) -> Dict:
    try:
        async with session.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot"},
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in (await r.json()).get("result", {}).get("list", []):
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        bid = float(item.get("bid1Price", 0) or 0)
                        ask = float(item.get("ask1Price", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"Bybit: {e}")
        return {}


async def get_okx(session) -> Dict:
    try:
        async with session.get(
            "https://www.okx.com/api/v5/market/tickers",
            params={"instType": "SPOT"},
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in (await r.json()).get("data", []):
                inst = item.get("instId", "")
                if inst.endswith(f"-{QUOTE}"):
                    base = inst[:-len(f"-{QUOTE}")]
                    if base in SYMBOLS:
                        bid = float(item.get("bidPx", 0) or 0)
                        ask = float(item.get("askPx", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"OKX: {e}")
        return {}


async def get_gate(session) -> Dict:
    try:
        async with session.get(
            "https://api.gateio.ws/api/v4/spot/tickers",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in await r.json():
                pair = item.get("currency_pair", "")
                if pair.endswith(f"_{QUOTE}"):
                    base = pair[:-len(f"_{QUOTE}")]
                    if base in SYMBOLS:
                        bid = float(item.get("highest_bid", 0) or 0)
                        ask = float(item.get("lowest_ask", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"Gate.io: {e}")
        return {}


async def get_mexc(session) -> Dict:
    try:
        async with session.get(
            "https://api.mexc.com/api/v3/ticker/bookTicker",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in await r.json():
                sym = item.get("symbol", "")
                if sym.endswith(QUOTE):
                    base = sym[:-len(QUOTE)]
                    if base in SYMBOLS:
                        bid = float(item.get("bidPrice", 0) or 0)
                        ask = float(item.get("askPrice", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"MEXC: {e}")
        return {}


async def get_kucoin(session) -> Dict:
    try:
        async with session.get(
            "https://api.kucoin.com/api/v1/market/allTickers",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in (await r.json()).get("data", {}).get("ticker", []):
                sym = item.get("symbol", "")
                if sym.endswith(f"-{QUOTE}"):
                    base = sym[:-len(f"-{QUOTE}")]
                    if base in SYMBOLS:
                        bid = float(item.get("buy", 0) or 0)
                        ask = float(item.get("sell", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"KuCoin: {e}")
        return {}


async def get_bitfinex(session) -> Dict:
    try:
        async with session.get(
            "https://api-pub.bitfinex.com/v2/tickers",
            params={"symbols": "ALL"},
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in await r.json():
                if not isinstance(item, list) or len(item) < 4:
                    continue
                sym = str(item[0])
                if sym.startswith("t") and sym.endswith("UST"):
                    base = sym[1:-3]
                    if base in SYMBOLS:
                        bid = float(item[1] or 0)
                        ask = float(item[3] or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"Bitfinex: {e}")
        return {}


async def get_htx(session) -> Dict:
    try:
        async with session.get(
            "https://api.huobi.pro/market/tickers",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            out = {}
            for item in (await r.json()).get("data", []):
                sym = item.get("symbol", "")
                if sym.endswith("usdt"):
                    base = sym[:-4].upper()
                    if base in SYMBOLS:
                        bid = float(item.get("bid", 0) or 0)
                        ask = float(item.get("ask", 0) or 0)
                        if bid > 0 and ask > 0:
                            out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"HTX: {e}")
        return {}


async def get_kraken(session) -> Dict:
    try:
        async with session.get(
            "https://api.kraken.com/0/public/Ticker",
            timeout=aiohttp.ClientTimeout(total=6)) as r:
            data = (await r.json()).get("result", {})
            out = {}
            for pair, item in data.items():
                # Kraken использует нестандартные имена
                base = pair.replace("XBT", "BTC").replace("ZUSD", "").replace("USD", "")
                base = base.rstrip("Z").rstrip("X")
                if base in SYMBOLS:
                    bid = float(item.get("b", [0])[0] or 0)
                    ask = float(item.get("a", [0])[0] or 0)
                    if bid > 0 and ask > 0:
                        out[base] = {"bid": bid, "ask": ask}
            return out
    except Exception as e:
        logger.error(f"Kraken: {e}")
        return {}


# ═══════════════════════════════════════
# АРБИТРАЖ
# ═══════════════════════════════════════

def find_arbitrage(all_data: Dict[str, Dict]) -> List[dict]:
    results = []
    vol = config["max_trade_usdt"]
    min_pct = config["min_profit_pct"]

    for symbol, exchanges in all_data.items():
        ex_list = list(exchanges.items())
        if len(ex_list) < 2:
            continue
        for i in range(len(ex_list)):
            for j in range(len(ex_list)):
                if i == j:
                    continue
                buy_ex,  buy_d  = ex_list[i]
                sell_ex, sell_d = ex_list[j]
                buy_price  = buy_d.get("ask", 0)
                sell_price = sell_d.get("bid", 0)
                if buy_price <= 0 or sell_price <= buy_price:
                    continue
                buy_fee  = FEES.get(buy_ex,  0.1) / 100
                sell_fee = FEES.get(sell_ex, 0.1) / 100
                gross_pct = (sell_price - buy_price) / buy_price * 100
                net_pct   = gross_pct - buy_fee * 100 - sell_fee * 100
                if net_pct < min_pct:
                    continue
                coins  = vol / buy_price
                profit = coins * sell_price * (1 - sell_fee) - vol * (1 + buy_fee)
                results.append({
                    "symbol":      symbol,
                    "buy_ex":      buy_ex,
                    "sell_ex":     sell_ex,
                    "buy_price":   buy_price,
                    "sell_price":  sell_price,
                    "gross_pct":   round(gross_pct, 4),
                    "net_pct":     round(net_pct, 4),
                    "profit_usdt": round(profit, 4),
                    "coins":       round(coins, 6),
                    "volume_usdt": vol,
                    "time":        datetime.now().strftime("%H:%M:%S"),
                })

    results.sort(key=lambda x: x["net_pct"], reverse=True)
    return results


def format_signal(opp: dict) -> str:
    mode = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ"
    p500  = round(opp["profit_usdt"] * 5,  2)
    p1000 = round(opp["profit_usdt"] * 10, 2)
    return (
        f"🚨 *АРБИТРАЖ: {opp['buy_ex']} → {opp['sell_ex']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{mode}\n\n"
        f"💱 *{opp['symbol']}/USDT*\n\n"
        f"📥 *КУПИТЬ на {opp['buy_ex']}*\n"
        f"   Цена: `{opp['buy_price']} USDT`\n"
        f"   Объём: `{opp['volume_usdt']} USDT`\n"
        f"   Получишь: `{opp['coins']} {opp['symbol']}`\n\n"
        f"📤 *ПРОДАТЬ на {opp['sell_ex']}*\n"
        f"   Цена: `{opp['sell_price']} USDT`\n\n"
        f"📊 *Расчёт:*\n"
        f"   Спред: `{opp['gross_pct']}%`\n"
        f"   После комиссий: `{opp['net_pct']}%`\n\n"
        f"💰 *Прибыль:*\n"
        f"   100 USDT → `~{opp['profit_usdt']} USDT`\n"
        f"   500 USDT → `~{p500} USDT`\n"
        f"   1000 USDT → `~{p1000} USDT`\n\n"
        f"⚠️ Цена актуальна только сейчас!\n"
        f"⚠️ Проверь баланс перед входом!\n\n"
        f"🕐 {opp['time']}"
    )


# ═══════════════════════════════════════
# СКАН
# ═══════════════════════════════════════

async def fetch_all(session):
    results = await asyncio.gather(
        get_binance(session),
        get_bybit(session),
        get_okx(session),
        get_gate(session),
        get_mexc(session),
        get_kucoin(session),
        get_bitfinex(session),
        get_htx(session),
        get_kraken(session),
        return_exceptions=True
    )

    ex_names = ["Binance","Bybit","OKX","Gate.io","MEXC","KuCoin","Bitfinex","HTX","Kraken"]
    all_data: Dict[str, Dict] = {}
    active = []

    for ex_name, result in zip(ex_names, results):
        if isinstance(result, Exception) or not result:
            continue
        active.append(ex_name)
        for symbol, price_data in result.items():
            if symbol not in all_data:
                all_data[symbol] = {}
            all_data[symbol][ex_name] = price_data

    return all_data, active


async def scan_cycle(session):
    stats["scans"] += 1
    all_data, active = await fetch_all(session)
    if len(active) < 2:
        return [], active
    opps = find_arbitrage(all_data)
    if opps:
        stats["signals"] += len(opps)
    return opps, active


async def execute_sim(opp: dict):
    trade = {
        "id": len(trade_history) + 1,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": opp["symbol"],
        "buy_ex": opp["buy_ex"],
        "sell_ex": opp["sell_ex"],
        "buy_price": opp["buy_price"],
        "sell_price": opp["sell_price"],
        "net_pct": opp["net_pct"],
        "profit_usdt": opp["profit_usdt"],
    }
    trade_history.append(trade)
    stats["trades_sim"] += 1
    stats["profit_sim"] += opp["profit_usdt"]
    logger.info(f"SIM #{trade['id']}: {opp['symbol']} {opp['buy_ex']}→{opp['sell_ex']} +{opp['net_pct']}%")


# ═══════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════

async def handle_command(session, text, chat_id):
    global CHAT_ID
    CHAT_ID = chat_id
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd == "/start":
        mode = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ"
        await send_tg(session,
            f"✅ *TriangleArbBot запущен!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Режим: {mode}\n"
            f"Площадки: Binance, Bybit, OKX, Gate.io,\n"
            f"MEXC, KuCoin, Bitfinex, HTX, Kraken\n"
            f"Монет: {len(SYMBOLS)}\n\n"
            f"⚙️ Мин. прибыль: `{config['min_profit_pct']}%`\n"
            f"⚙️ Объём: `{config['max_trade_usdt']} USDT`\n"
            f"⚙️ Интервал: `{config['scan_interval']} сек`\n\n"
            f"/scan — скан прямо сейчас\n"
            f"/top — топ пар по спреду\n"
            f"/prices — цены на биржах\n"
            f"/stats — статистика\n"
            f"/history — последние сделки\n"
            f"/mode — симуляция ↔ реал\n"
            f"/setprofit 0.15 — мин. прибыль %\n"
            f"/setvolume 200 — объём USDT\n"
        )

    elif cmd == "/scan":
        await send_tg(session, f"🔍 Сканирую 9 бирж, {len(SYMBOLS)} монет...")
        opps, active = await scan_cycle(session)
        if not opps:
            await send_tg(session,
                f"😔 Нет сигналов (порог {config['min_profit_pct']}%).\n\n"
                f"Активных бирж: {len(active)}\n"
                f"{', '.join(active)}\n\n"
                f"Сканов: {stats['scans']}\n"
                f"Напиши /top чтобы увидеть лучшие пары."
            )
        else:
            await send_tg(session, f"✅ Найдено {len(opps)} сигналов! Топ-3:")
            for opp in opps[:3]:
                await send_tg(session, format_signal(opp))
                if config["simulation_mode"]:
                    await execute_sim(opp)

    elif cmd == "/top":
        await send_tg(session, "📊 Ищу лучшие пары...")
        all_data, active = await fetch_all(session)
        if len(active) < 2:
            await send_tg(session, "❌ Недостаточно бирж.")
            return
        saved = config["min_profit_pct"]
        config["min_profit_pct"] = -999
        opps = find_arbitrage(all_data)
        config["min_profit_pct"] = saved
        if not opps:
            await send_tg(session, "❌ Нет данных.")
            return
        msg = f"📊 *ТОП-15 — {datetime.now().strftime('%H:%M:%S')}*\n"
        msg += f"Бирж: {', '.join(active)}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for i, opp in enumerate(opps[:15], 1):
            icon = "🟢" if opp["net_pct"] >= config["min_profit_pct"] else "🔴"
            msg += (
                f"{icon} *{i}. {opp['symbol']}* {opp['buy_ex']}→{opp['sell_ex']}\n"
                f"   Спред: `{opp['gross_pct']}%` | Чистая: `{opp['net_pct']}%`\n"
                f"   Купить: `{opp['buy_price']}` Продать: `{opp['sell_price']}`\n\n"
            )
        msg += f"_Порог: {config['min_profit_pct']}%_"
        await send_tg(session, msg)

    elif cmd == "/prices":
        await send_tg(session, "📊 Получаю цены...")
        all_data, active = await fetch_all(session)
        msg = f"📊 *ЦЕНЫ — {datetime.now().strftime('%H:%M:%S')}*\n"
        msg += f"Активных бирж: {len(active)}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for sym in ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX"]:
            ex_data = all_data.get(sym, {})
            if not ex_data:
                continue
            prices = [f"{ex}:`{d['ask']}`" for ex, d in ex_data.items()]
            msg += f"*{sym}:*\n  " + " | ".join(prices) + "\n\n"
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
            f"💰 Прибыль (симуляция): {round(stats['profit_sim'], 4)} USDT\n"
            f"❌ Ошибок: {stats['errors']}\n\n"
            f"⚙️ Мин. прибыль: {config['min_profit_pct']}%\n"
            f"⚙️ Объём: {config['max_trade_usdt']} USDT\n"
            f"⚙️ Интервал: {config['scan_interval']} сек\n"
            f"⚙️ Монет: {len(SYMBOLS)}\n"
            f"⚙️ Бирж: 9"
        )

    elif cmd == "/history":
        if not trade_history:
            await send_tg(session, "📋 Нет сделок в этой сессии.")
            return
        msg = "📋 *ПОСЛЕДНИЕ СДЕЛКИ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for t in trade_history[-10:][::-1]:
            sign = "+" if t["profit_usdt"] > 0 else ""
            msg += (
                f"#{t['id']} *{t['symbol']}* {t['buy_ex']}→{t['sell_ex']}\n"
                f"   {sign}{t['net_pct']}% | {sign}{t['profit_usdt']} USDT\n"
                f"   {t['time']}\n\n"
            )
        await send_tg(session, msg)

    elif cmd == "/mode":
        config["simulation_mode"] = not config["simulation_mode"]
        mode = "🔵 СИМУЛЯЦИЯ" if config["simulation_mode"] else "🔴 РЕАЛЬНАЯ ТОРГОВЛЯ"
        warn = "\n\n⚠️ Для реальной торговли нужны API ключи!" if not config["simulation_mode"] else ""
        await send_tg(session, f"Режим: {mode}{warn}")

    elif cmd == "/setprofit":
        if len(parts) < 2:
            await send_tg(session, "Пример: `/setprofit 0.15`")
            return
        try:
            config["min_profit_pct"] = float(parts[1])
            await send_tg(session, f"✅ Мин. прибыль: `{config['min_profit_pct']}%`")
        except:
            await send_tg(session, "❌ Пример: `/setprofit 0.15`")

    elif cmd == "/setvolume":
        if len(parts) < 2:
            await send_tg(session, "Пример: `/setvolume 200`")
            return
        try:
            config["max_trade_usdt"] = float(parts[1])
            await send_tg(session, f"✅ Объём: `{config['max_trade_usdt']} USDT`")
        except:
            await send_tg(session, "❌ Пример: `/setvolume 200`")

    else:
        await send_tg(session,
            "/start /scan /top /prices\n"
            "/stats /history /mode\n"
            "/setprofit 0.15 /setvolume 200"
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
    while True:
        try:
            opps, active = await scan_cycle(session)
            logger.info(f"Scan #{stats['scans']}: {len(active)} бирж, {len(opps)} сигналов")
            for opp in opps[:3]:
                key = f"{opp['symbol']}-{opp['buy_ex']}-{opp['sell_ex']}"
                now = datetime.now().timestamp()
                if now - last_signal_time.get(key, 0) > 120:
                    last_signal_time[key] = now
                    if CHAT_ID:
                        await send_tg(session, format_signal(opp))
                    if config["simulation_mode"]:
                        await execute_sim(opp)
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Scan error: {e}")
        await asyncio.sleep(config["scan_interval"])


async def main():
    if not TG_TOKEN:
        logger.error("ARB_BOT_TOKEN не установлен!")
        return
    logger.info(f"TriangleArbBot | {len(SYMBOLS)} монет | 9 бирж | порог {config['min_profit_pct']}%")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(polling_loop(session), scan_loop(session))


if __name__ == "__main__":
    asyncio.run(main())
