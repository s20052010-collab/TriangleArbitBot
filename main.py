import asyncio
import aiohttp
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("ARB_BOT_TOKEN", "")
CHAT_ID = None
MIN_MARGIN = 0.5

SELLER_MIN_TRADES = 50
SELLER_MIN_COMPLETION = 98.0
SELLER_MIN_LIMIT_KZT = 10000

BUYER_MIN_TRADES = 30
BUYER_MIN_COMPLETION = 98.0
BUYER_MAX_MIN_LIMIT_KZT = 450000

SEEN_DEALS = set()
SEEN_RESET_TIME = datetime.now()


async def send_message(session, text):
    if not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.error(f"Send error: {e}")


async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        async with session.get(url, params={"offset": offset, "timeout": 30},
                               timeout=aiohttp.ClientTimeout(total=35)) as r:
            data = await r.json()
            return data.get("result", [])
    except:
        return []


# ═══════════════════════════════════════
# BINANCE P2P
# ═══════════════════════════════════════

async def binance_fetch(session, trade_type):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    try:
        async with session.post(url, json={
            "asset": "USDT", "fiat": "KZT",
            "tradeType": trade_type, "page": 1, "rows": 20,
            "merchantCheck": False
        }, headers={"Content-Type": "application/json"},
           timeout=aiohttp.ClientTimeout(total=8)) as r:
            data = await r.json()
            best = None
            min_trades = SELLER_MIN_TRADES if trade_type == "BUY" else BUYER_MIN_TRADES
            max_min_limit = None if trade_type == "BUY" else BUYER_MAX_MIN_LIMIT_KZT
            for a in data.get("data", []):
                adv = a.get("adv", {})
                advertiser = a.get("advertiser", {})
                price = float(adv.get("price", 0))
                min_l = float(adv.get("minSingleTransAmount", 0))
                max_l = float(adv.get("maxSingleTransAmount", 0))
                trades = int(advertiser.get("monthOrderCount", 0))
                comp = float(advertiser.get("monthFinishRate", 0)) * 100
                nick = advertiser.get("nickName", "?")
                banks = []
                for pm in adv.get("tradeMethods", []):
                    name = pm.get("tradeMethodName") or pm.get("identifier") or ""
                    if name:
                        banks.append(name.strip())
                if price <= 0: continue
                if trades < min_trades: continue
                if comp < SELLER_MIN_COMPLETION: continue
                if trade_type == "BUY":
                    if min_l > SELLER_MIN_LIMIT_KZT: continue
                    if max_l < SELLER_MIN_LIMIT_KZT: continue
                    if not best or price < best[0]:
                        best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Binance")
                else:
                    if max_min_limit and min_l > max_min_limit: continue
                    if not best or price > best[0]:
                        best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Binance")
            return best
    except Exception as e:
        logger.error(f"Binance {trade_type} error: {e}")
        return None


# ═══════════════════════════════════════
# BYBIT P2P
# ═══════════════════════════════════════

async def bybit_fetch(session, side):
    url = "https://api2.bybit.com/fiat/otc/item/online"
    try:
        async with session.post(url, json={
            "tokenId": "USDT", "currencyId": "KZT",
            "side": side, "page": "1", "size": "20"
        }, headers={"Content-Type": "application/json"},
           timeout=aiohttp.ClientTimeout(total=8)) as r:
            data = await r.json()
            best = None
            is_buy = side == "1"
            for item in data.get("result", {}).get("items", []):
                price = float(item.get("price", 0))
                min_l = float(item.get("minAmount", 0))
                max_l = float(item.get("maxAmount", 0))
                trades = int(item.get("recentOrderNum", 0))
                comp_raw = float(item.get("recentExecuteRate", 0))
                comp = comp_raw * 100 if comp_raw <= 1 else comp_raw
                nick = item.get("nickName", "?")
                banks = []
                for pm in item.get("payments", []):
                    name = pm.get("name") or ""
                    if name:
                        banks.append(name.strip())
                if not banks:
                    for pm in item.get("paymentMethods", []):
                        if isinstance(pm, str):
                            banks.append(pm.strip())
                        elif isinstance(pm, dict):
                            name = pm.get("name") or pm.get("paymentType") or ""
                            if name:
                                banks.append(name.strip())
                if price <= 0: continue
                min_t = SELLER_MIN_TRADES if is_buy else BUYER_MIN_TRADES
                if trades < min_t: continue
                if comp < SELLER_MIN_COMPLETION: continue
                if is_buy:
                    if min_l > SELLER_MIN_LIMIT_KZT: continue
                    if max_l < SELLER_MIN_LIMIT_KZT: continue
                    if not best or price < best[0]:
                        best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Bybit")
                else:
                    if min_l > BUYER_MAX_MIN_LIMIT_KZT: continue
                    if not best or price > best[0]:
                        best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Bybit")
            return best
    except Exception as e:
        logger.error(f"Bybit side={side} error: {e}")
        return None


# ═══════════════════════════════════════
# OKX P2P
# ═══════════════════════════════════════

async def okx_fetch(session, side):
    url = "https://www.okx.com/v3/c2c/tradingOrders/books"
    try:
        async with session.get(url, params={
            "quoteCurrency": "KZT",
            "baseCurrency": "USDT",
            "side": side,
            "paymentMethod": "all",
            "userType": "all",
            "showTrade": "true",
            "showFollow": "false",
            "showAlreadyTraded": "false",
            "isAbleFilter": "false"
        }, headers={"Content-Type": "application/json"},
           timeout=aiohttp.ClientTimeout(total=8)) as r:
            data = await r.json()
            best = None
            is_buy = side == "sell"  # buy USDT = sell KZT
            items = data.get("data", {}).get("buy", []) if side == "sell" else data.get("data", {}).get("sell", [])
            for item in items:
                try:
                    price = float(item.get("price", 0))
                    min_l = float(item.get("quoteMinAmountPerOrder", 0))
                    max_l = float(item.get("quoteMaxAmountPerOrder", 0))
                    trades = int(item.get("completedOrderQuantity", 0))
                    comp_str = item.get("completedRate", "0")
                    comp = float(comp_str) * 100 if float(comp_str) <= 1 else float(comp_str)
                    nick = item.get("nickName", "?")
                    banks = [pm.get("paymentMethod", "") for pm in item.get("paymentMethods", []) if pm.get("paymentMethod")]
                    if price <= 0: continue
                    min_t = SELLER_MIN_TRADES if is_buy else BUYER_MIN_TRADES
                    if trades < min_t: continue
                    if comp < SELLER_MIN_COMPLETION: continue
                    if is_buy:
                        if not best or price < best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "OKX")
                    else:
                        if not best or price > best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "OKX")
                except:
                    continue
            return best
    except Exception as e:
        logger.error(f"OKX side={side} error: {e}")
        return None


# ═══════════════════════════════════════
# BITGET P2P
# ═══════════════════════════════════════

async def bitget_fetch(session, side):
    url = "https://api.bitget.com/api/v2/p2p/adv/list"
    try:
        async with session.get(url, params={
            "coin": "USDT",
            "fiatCurrency": "KZT",
            "tradeType": side,
            "page": "1",
            "pageSize": "20"
        }, headers={"Content-Type": "application/json"},
           timeout=aiohttp.ClientTimeout(total=8)) as r:
            data = await r.json()
            best = None
            is_buy = side == "BUY"
            for item in data.get("data", {}).get("dataList", []):
                try:
                    price = float(item.get("price", 0))
                    min_l = float(item.get("minLimit", 0))
                    max_l = float(item.get("maxLimit", 0))
                    trades = int(item.get("completedOrderNum", 0))
                    comp_str = item.get("completionRate", "0")
                    comp = float(comp_str) * 100 if float(comp_str) <= 1 else float(comp_str)
                    nick = item.get("nickName", "?")
                    banks = [pm.get("paymentName", "") for pm in item.get("paymentList", []) if pm.get("paymentName")]
                    if price <= 0: continue
                    min_t = SELLER_MIN_TRADES if is_buy else BUYER_MIN_TRADES
                    if trades < min_t: continue
                    if comp < SELLER_MIN_COMPLETION: continue
                    if is_buy:
                        if not best or price < best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Bitget")
                    else:
                        if not best or price > best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Bitget")
                except:
                    continue
            return best
    except Exception as e:
        logger.error(f"Bitget side={side} error: {e}")
        return None


# ═══════════════════════════════════════
# GATE.IO P2P
# ═══════════════════════════════════════

async def gate_fetch(session, side):
    url = "https://www.gate.io/api/web/v1/p2p/buy-sell-list"
    try:
        async with session.post(url, json={
            "currency": "USDT",
            "fiat": "KZT",
            "side": side,
            "page": 1,
            "page_size": 20
        }, headers={"Content-Type": "application/json"},
           timeout=aiohttp.ClientTimeout(total=8)) as r:
            data = await r.json()
            best = None
            is_buy = side == "buy"
            for item in data.get("data", {}).get("list", []):
                try:
                    price = float(item.get("price", 0))
                    min_l = float(item.get("min_amount", 0))
                    max_l = float(item.get("max_amount", 0))
                    trades = int(item.get("completed_orders", 0))
                    comp_str = item.get("completion_rate", "0")
                    comp = float(comp_str) * 100 if float(comp_str) <= 1 else float(comp_str)
                    nick = item.get("nickname", "?")
                    banks = item.get("payment_methods", [])
                    if isinstance(banks, list):
                        banks = [b if isinstance(b, str) else b.get("name", "") for b in banks]
                    if price <= 0: continue
                    min_t = SELLER_MIN_TRADES if is_buy else BUYER_MIN_TRADES
                    if trades < min_t: continue
                    if comp < SELLER_MIN_COMPLETION: continue
                    if is_buy:
                        if not best or price < best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Gate.io")
                    else:
                        if not best or price > best[0]:
                            best = (price, min_l, max_l, banks, nick, trades, round(comp, 1), "Gate.io")
                except:
                    continue
            return best
    except Exception as e:
        logger.error(f"Gate.io side={side} error: {e}")
        return None


# ═══════════════════════════════════════
# СКАНИРОВАНИЕ
# ═══════════════════════════════════════

def check_pair(buy_data, sell_data):
    global SEEN_DEALS, SEEN_RESET_TIME

    if (datetime.now() - SEEN_RESET_TIME).seconds > 1800:
        SEEN_DEALS = set()
        SEEN_RESET_TIME = datetime.now()
        logger.info("SEEN_DEALS reset")

    if not buy_data or not sell_data:
        return None

    buy_price, buy_min, buy_max, buy_banks, buy_nick, buy_trades, buy_comp, buy_ex = buy_data
    sell_price, sell_min, sell_max, sell_banks, sell_nick, sell_trades, sell_comp, sell_ex = sell_data

    if buy_ex == sell_ex and buy_nick == sell_nick:
        return None

    if sell_min > buy_max:
        return None

    net = round(((sell_price - buy_price) / buy_price) * 100 - 0.3, 2)

    if net < MIN_MARGIN:
        return None

    key = f"{buy_ex}-{sell_ex}-{round(buy_price, 1)}-{round(sell_price, 1)}"
    if key in SEEN_DEALS:
        return None
    SEEN_DEALS.add(key)

    return {
        "buy_exchange": buy_ex,
        "sell_exchange": sell_ex,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "buy_nick": buy_nick,
        "sell_nick": sell_nick,
        "buy_trades": buy_trades,
        "buy_comp": buy_comp,
        "buy_min": buy_min,
        "buy_max": buy_max,
        "buy_banks": buy_banks,
        "sell_trades": sell_trades,
        "sell_comp": sell_comp,
        "sell_min": sell_min,
        "sell_max": sell_max,
        "sell_banks": sell_banks,
        "net": net,
    }


async def scan(session):
    tasks = await asyncio.gather(
        binance_fetch(session, "BUY"),
        binance_fetch(session, "SELL"),
        bybit_fetch(session, "1"),
        bybit_fetch(session, "0"),
        okx_fetch(session, "sell"),
        okx_fetch(session, "buy"),
        bitget_fetch(session, "BUY"),
        bitget_fetch(session, "SELL"),
        gate_fetch(session, "buy"),
        gate_fetch(session, "sell"),
        return_exceptions=True
    )

    def safe(v):
        return v if not isinstance(v, Exception) and v is not None else None

    b_buy   = safe(tasks[0])
    b_sell  = safe(tasks[1])
    bb_buy  = safe(tasks[2])
    bb_sell = safe(tasks[3])
    ok_buy  = safe(tasks[4])
    ok_sell = safe(tasks[5])
    bg_buy  = safe(tasks[6])
    bg_sell = safe(tasks[7])
    gt_buy  = safe(tasks[8])
    gt_sell = safe(tasks[9])

    buy_sources  = [d for d in [b_buy, bb_buy, ok_buy, bg_buy, gt_buy] if d]
    sell_sources = [d for d in [b_sell, bb_sell, ok_sell, bg_sell, gt_sell] if d]

    logger.info(f"Buy sources: {[d[7]+':'+str(d[0]) for d in buy_sources]}")
    logger.info(f"Sell sources: {[d[7]+':'+str(d[0]) for d in sell_sources]}")

    signals = []
    seen_pairs = set()

    for buy_d in buy_sources:
        for sell_d in sell_sources:
            pair_key = f"{buy_d[7]}-{sell_d[7]}"
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            r = check_pair(buy_d, sell_d)
            if r:
                signals.append(r)

    signals.sort(key=lambda x: x["net"], reverse=True)
    return signals, buy_sources, sell_sources


def fmt(val):
    return f"{int(val):,}".replace(",", " ")


def format_signal(s):
    buy_banks_str = ", ".join(s["buy_banks"]) if s["buy_banks"] else "—"
    sell_banks_str = ", ".join(s["sell_banks"]) if s["sell_banks"] else "—"
    profit_100  = round((s["sell_price"] - s["buy_price"]) * 100  * 0.997, 0)
    profit_500  = round((s["sell_price"] - s["buy_price"]) * 500  * 0.997, 0)
    profit_1000 = round((s["sell_price"] - s["buy_price"]) * 1000 * 0.997, 0)
    work_min = max(s["buy_min"], s["sell_min"])
    work_max = min(s["buy_max"], s["sell_max"]) if s["sell_max"] else s["buy_max"]

    return (
        f"🚨 *АРБИТРАЖ: {s['buy_exchange']} → {s['sell_exchange']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📥 *КУПИТЬ USDT на {s['buy_exchange']}*\n"
        f"   Продавец: {s['buy_nick']}\n"
        f"   Цена: `{s['buy_price']} KZT`\n"
        f"   Лимит: `{fmt(s['buy_min'])} — {fmt(s['buy_max'])} KZT`\n"
        f"   🏦 Банки: {buy_banks_str}\n"
        f"   ✅ Сделок: {s['buy_trades']} | Рейтинг: {s['buy_comp']}%\n\n"
        f"📤 *ПРОДАТЬ USDT на {s['sell_exchange']}*\n"
        f"   Покупатель: {s['sell_nick']}\n"
        f"   Цена: `{s['sell_price']} KZT`\n"
        f"   Лимит: `{fmt(s['sell_min'])} — {fmt(s['sell_max'])} KZT`\n"
        f"   🏦 Банки: {sell_banks_str}\n"
        f"   ✅ Сделок: {s['sell_trades']} | Рейтинг: {s['sell_comp']}%\n\n"
        f"💼 *Рабочий диапазон:*\n"
        f"   `{fmt(work_min)} — {fmt(work_max)} KZT`\n\n"
        f"💰 *Чистая маржа: {s['net']}%*\n"
        f"💵 Прибыль со 100 USDT: ~{fmt(profit_100)} KZT\n"
        f"💵 Прибыль с 500 USDT: ~{fmt(profit_500)} KZT\n"
        f"💵 Прибыль с 1000 USDT: ~{fmt(profit_1000)} KZT\n\n"
        f"⚠️ Проверь имя плательщика!\n"
        f"⚠️ Жди реального зачисления!\n\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
    )


HELP_TEXT = """
🤖 *MULTI EXCHANGE ARB BOT*
━━━━━━━━━━━━━━━━━━━━━━

Площадки: Binance, Bybit, OKX, Bitget, Gate.io

Команды:
/start — запустить мониторинг
/scan — сканировать прямо сейчас
/rates — текущие курсы со всех бирж
/help — помощь

Бот мониторит каждые 5 минут.
Сигнал когда маржа ≥0.5%.
"""


async def handle_command(session, text, chat_id):
    global CHAT_ID
    CHAT_ID = chat_id
    cmd = text.strip().lower().split()[0]

    if cmd == "/start":
        await send_message(session,
            "✅ *Multi Exchange Arb Bot запущен!*\n\n"
            "Площадки: Binance, Bybit, OKX, Bitget, Gate.io\n"
            f"Сигнал когда маржа ≥{MIN_MARGIN}%.\n\n"
            f"Продавцы: {SELLER_MIN_TRADES}+ сделок, {SELLER_MIN_COMPLETION}%+\n"
            f"Покупатели: {BUYER_MIN_TRADES}+ сделок, {BUYER_MIN_COMPLETION}%+\n\n"
            "📊 Напиши /rates для текущих курсов."
        )

    elif cmd == "/rates":
        await send_message(session, "📊 Получаю курсы со всех бирж...")
        tasks = await asyncio.gather(
            binance_fetch(session, "BUY"),
            binance_fetch(session, "SELL"),
            bybit_fetch(session, "1"),
            bybit_fetch(session, "0"),
            okx_fetch(session, "sell"),
            okx_fetch(session, "buy"),
            bitget_fetch(session, "BUY"),
            bitget_fetch(session, "SELL"),
            gate_fetch(session, "buy"),
            gate_fetch(session, "sell"),
            return_exceptions=True
        )

        def safe(v):
            return v if not isinstance(v, Exception) and v is not None else None

        sources = {
            "Binance":  (safe(tasks[0]), safe(tasks[1])),
            "Bybit":    (safe(tasks[2]), safe(tasks[3])),
            "OKX":      (safe(tasks[4]), safe(tasks[5])),
            "Bitget":   (safe(tasks[6]), safe(tasks[7])),
            "Gate.io":  (safe(tasks[8]), safe(tasks[9])),
        }

        msg = f"📊 *КУРСЫ USDT/KZT — {datetime.now().strftime('%H:%M:%S')}*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for name, (buy_d, sell_d) in sources.items():
            buy_str = f"`{buy_d[0]} KZT`" if buy_d else "—"
            sell_str = f"`{sell_d[0]} KZT`" if sell_d else "—"
            msg += f"*{name}:* 📥{buy_str} 📤{sell_str}\n"

        msg += "\n📈 *Лучшие пары:*\n"
        all_buys  = [v[0] for v in sources.values() if v[0]]
        all_sells = [v[1] for v in sources.values() if v[1]]
        best_combos = []
        for bd in all_buys:
            for sd in all_sells:
                if bd[7] == sd[7]: continue
                net = round(((sd[0] - bd[0]) / bd[0]) * 100 - 0.3, 2)
                best_combos.append((net, bd[7], sd[7]))
        best_combos.sort(reverse=True)
        for net, bex, sex in best_combos[:5]:
            icon = "🟢" if net >= MIN_MARGIN else "🔴"
            msg += f"   {icon} {bex}→{sex}: `{net}%`\n"

        msg += f"\n_Порог сигнала: {MIN_MARGIN}%_"
        await send_message(session, msg)

    elif cmd == "/scan":
        await send_message(session, "🔍 Сканирую все биржи...")
        result = await scan(session)
        signals = result[0]
        if not signals:
            buy_s, sell_s = result[1], result[2]
            active = [d[7] for d in buy_s] + [d[7] for d in sell_s]
            await send_message(session,
                f"😔 Нет сигналов (маржа < {MIN_MARGIN}%).\n\n"
                f"Активные биржи: {', '.join(set(active)) or 'нет данных'}\n\n"
                "Напиши /rates для текущих курсов."
            )
        else:
            for s in signals[:3]:
                await send_message(session, format_signal(s))

    elif cmd == "/help":
        await send_message(session, HELP_TEXT)


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


async def monitor_loop(session):
    await asyncio.sleep(30)
    while True:
        if CHAT_ID:
            try:
                result = await scan(session)
                signals = result[0]
                if signals:
                    for s in signals[:3]:
                        await send_message(session, format_signal(s))
                    logger.info(f"Signals sent: {len(signals)}, best: {signals[0]['net']}%")
                else:
                    buy_s = result[1]
                    logger.info(f"No signals. Active: {[d[7] for d in buy_s]}")
            except Exception as e:
                logger.error(f"Monitor error: {e}")
        await asyncio.sleep(300)


async def main():
    if not TOKEN:
        logger.error("ARB_BOT_TOKEN не установлен!")
        return
    logger.info(f"Multi Exchange Arb Bot запущен | порог {MIN_MARGIN}%")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(
            polling_loop(session),
            monitor_loop(session)
        )


if __name__ == "__main__":
    asyncio.run(main())
