import os
import asyncio
import logging
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.ext import Application, CommandHandler
from telegram.constants import ParseMode
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN     = "8755477782:AAFrnbNhCqy8XfBpRd9TlzIzvL_ydRXIL78"
CHAT_ID       = "1035061255"
SECRET        = "goldattack2025"
ANTHROPIC_KEY = "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"
PARIS_TZ      = ZoneInfo("Europe/Paris")

bot    = Bot(token=BOT_TOKEN)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# Stockage des événements déjà vus (pour détecter les nouvelles annonces)
seen_events = set()
last_events_check = []

PAIRS = {
    "xauusd": {"name": "XAU/USD", "type": "metal"},
    "btcusd": {"name": "BTC/USD", "type": "crypto", "symbol": "BTCUSDT"},
    "eurusd": {"name": "EUR/USD", "type": "forex",  "symbol": "EUR", "base": "USD"},
    "gbpusd": {"name": "GBP/USD", "type": "forex",  "symbol": "GBP", "base": "USD"},
    "eurgbp": {"name": "EUR/GBP", "type": "forex",  "symbol": "EUR", "base": "GBP"},
    "gbpjpy": {"name": "GBP/JPY", "type": "forex",  "symbol": "GBP", "base": "JPY"},
}

# ── Prix ─────────────────────────────────────────────────────────────────────

async def get_price(pair_key: str) -> float:
    info = PAIRS.get(pair_key, {})
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if info.get("type") == "crypto":
                r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={info['symbol']}")
                return float(r.json()["price"])
            elif info.get("type") == "metal":
                r = await client.get("https://open.er-api.com/v6/latest/XAU")
                data = r.json()
                if "rates" in data:
                    return round(data["rates"]["USD"], 2)
            else:
                r = await client.get(f"https://open.er-api.com/v6/latest/{info['symbol']}")
                data = r.json()
                if "rates" in data:
                    return round(data["rates"][info["base"]], 5)
    except Exception as e:
        logger.error(f"Price error {pair_key}: {e}")
    return 0.0

async def get_all_prices() -> dict:
    prices = {}
    for key in PAIRS:
        prices[key] = await get_price(key)
    return prices

# ── Calendrier ForexFactory ───────────────────────────────────────────────────

async def get_events(day_offset=0) -> list:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
            if r.status_code != 200:
                return []
            data = r.json()
            target = (datetime.now(PARIS_TZ) + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            events = []
            for e in data:
                edate    = e.get("date", "")[:10]
                currency = e.get("currency", "")
                impact   = e.get("impact", "")
                if edate != target:
                    continue
                if impact not in ["High", "Medium"]:
                    continue
                if currency not in ["USD", "EUR", "GBP", "JPY", "CHF"]:
                    continue
                events.append({
                    "id":       f"{edate}_{e.get('title','')}_{currency}",
                    "time":     e.get("date", "")[11:16],
                    "currency": currency,
                    "title":    e.get("title", ""),
                    "impact":   impact,
                    "forecast": e.get("forecast", "N/A"),
                    "previous": e.get("previous", "N/A"),
                    "actual":   e.get("actual", ""),
                })
            return events
    except Exception as e:
        logger.error(f"ForexFactory error: {e}")
        return []

async def get_week_events() -> list:
    all_events = []
    for offset in range(5):
        events = await get_events(day_offset=offset)
        all_events.extend(events)
    return all_events

def format_events(events: list) -> str:
    if not events:
        return "Aucune annonce majeure"
    lines = []
    for e in events:
        imp = "🔴" if e["impact"] == "High" else "🟡"
        lines.append(f"{imp} {e['time']} [{e['currency']}] {e['title']}")
    return "\n".join(lines)

# ── Fibonacci ─────────────────────────────────────────────────────────────────

def calc_fibo(high: float, low: float) -> dict:
    r = high - low
    return {
        "61.8": round(high - r * 0.618, 5),
        "70.5": round(high - r * 0.705, 5),
        "79.0": round(high - r * 0.79,  5),
        "88.6": round(high - r * 0.886, 5),
    }

# ── Claude helper ─────────────────────────────────────────────────────────────

def ask_claude(prompt: str, max_tokens=700) -> str:
    try:
        msg = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        return f"Analyse indisponible ({e})"

# ── BRIEFING 8h ───────────────────────────────────────────────────────────────

async def morning_briefing():
    try:
        events     = await get_events()
        events_str = format_events(events)
        prices     = await get_all_prices()
        today      = datetime.now(PARIS_TZ).strftime("%A %d %B %Y").upper()

        prices_str = "\n".join([
            f"XAU/USD : {prices.get('xauusd', 'N/A')}",
            f"BTC/USD : {prices.get('btcusd', 'N/A'):,.0f}" if prices.get('btcusd') else "BTC/USD : N/A",
            f"EUR/USD : {prices.get('eurusd', 'N/A')}",
            f"GBP/USD : {prices.get('gbpusd', 'N/A')}",
        ])

        analysis = ask_claude(f"""Tu es un analyste ICT/SMC expert. Ton style : direct, percutant, donne envie de lire.
Date : {today}
Prix d'ouverture : {prices_str}
Annonces du jour : {events_str}

Donne le briefing du matin. Structure :
1. UNE PHRASE D'ACCROCHE sur le contexte macro du jour (donne le ton)
2. BIAIS PAR PAIRE (emoji + HAUSSIER/BAISSIER/NEUTRE + 1 raison courte) :
   XAU/USD | BTC/USD | EUR/USD | GBP/USD | EUR/GBP | GBP/JPY
3. L'ANNONCE À NE PAS RATER aujourd'hui (si applicable)
4. CONSEIL DU JOUR en 1 ligne

Sois concis, percutant. Markdown Telegram.""")

        text = (
            f"🌅 *BRIEFING — {today}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 *AGENDA DU JOUR*\n{events_str}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{analysis}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"_08:00 — GoldAttack Bot_"
        )
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
        logger.info("Briefing 8h envoyé")
    except Exception as e:
        logger.error(f"Briefing error: {e}")

# ── DEBRIEFING 23h (du soir) ──────────────────────────────────────────────────

async def evening_debrief():
    try:
        events = await get_events()
        prices = await get_all_prices()
        today  = datetime.now(PARIS_TZ).strftime("%A %d %B").upper()

        prices_str = "\n".join([
            f"XAU/USD : {prices.get('xauusd', 'N/A')}",
            f"BTC/USD : {prices.get('btcusd', 'N/A'):,.0f}" if prices.get('btcusd') else "BTC/USD : N/A",
            f"EUR/USD : {prices.get('eurusd', 'N/A')}",
            f"GBP/USD : {prices.get('gbpusd', 'N/A')}",
        ])

        analysis = ask_claude(f"""Tu es un analyste ICT/SMC. Style : storytelling, clair, donne envie de lire.
Journée du : {today}
Prix de clôture : {prices_str}
Annonces du jour : {format_events(events)}

Fais le DÉBRIEF de la journée :
1. CE QUI S'EST PASSÉ aujourd'hui sur les marchés (2-3 phrases narratives)
2. PAIRE DU JOUR : celle qui a eu le plus de mouvement et pourquoi
3. CE QU'ON RETIENT : 2 leçons ou observations importantes
4. PRÉPARATION pour demain : biais et niveaux à surveiller

Style journaliste financier, percutant. Markdown Telegram.""")

        text = (
            f"🌙 *DÉBRIEF — {today}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{analysis}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"_23:00 — GoldAttack Bot_"
        )
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
        logger.info("Débrief soir envoyé")
    except Exception as e:
        logger.error(f"Evening debrief error: {e}")

# ── DÉBRIEF HEBDOMADAIRE (vendredi 23h) ──────────────────────────────────────

async def weekly_debrief():
    try:
        week_events = await get_week_events()
        prices      = await get_all_prices()
        week_num    = datetime.now(PARIS_TZ).isocalendar()[1]

        prices_str = "\n".join([
            f"XAU/USD : {prices.get('xauusd', 'N/A')}",
            f"BTC/USD : {prices.get('btcusd', 'N/A'):,.0f}" if prices.get('btcusd') else "BTC/USD : N/A",
            f"EUR/USD : {prices.get('eurusd', 'N/A')}",
            f"GBP/USD : {prices.get('gbpusd', 'N/A')}",
        ])

        next_week_events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get("https://nfs.faireconomy.media/ff_calendar_nextweek.json")
                if r.status_code == 200:
                    data = r.json()
                    for e in data:
                        if e.get("impact") == "High" and e.get("currency") in ["USD", "EUR", "GBP"]:
                            next_week_events.append(
                                f"• {e.get('date','')[5:10]} [{e.get('currency','')}] {e.get('title','')}"
                            )
        except:
            pass

        next_week_str = "\n".join(next_week_events[:10]) if next_week_events else "Calendrier semaine prochaine non disponible"

        analysis = ask_claude(f"""Tu es un analyste macro ICT/SMC senior. Style : synthèse hebdo professionnelle et engageante.
Semaine {week_num}
Clôtures : {prices_str}
Événements de la semaine : {format_events(week_events)}
Événements semaine prochaine : {next_week_str}

DÉBRIEF HEBDOMADAIRE :
1. RÉSUMÉ DE LA SEMAINE : ce qui a défini les marchés (2-3 phrases narratives)
2. CLASSEMENT DES PAIRES : du plus fort au plus faible cette semaine
3. ZONES CLÉS À SURVEILLER la semaine prochaine pour XAU/USD, BTC, EUR/USD, GBP/USD
4. ÉVÉNEMENTS MAJEURS SEMAINE PROCHAINE : les 3 à ne pas manquer
5. BIAIS SEMAINE PROCHAINE par paire (haussier/baissier/neutre + 1 raison)
6. MOT DE FIN : une phrase de motivation ou de sagesse pour le trader

Style magazine financier, structuré et engageant. Markdown Telegram.""", max_tokens=1200)

        text = (
            f"📋 *DÉBRIEF SEMAINE {week_num}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🗓 *AGENDA SEMAINE PROCHAINE*\n"
            f"{next_week_str}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{analysis}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"_Vendredi 23:00 — GoldAttack Bot_\n"
            f"_Bon week-end 💪_"
        )
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
        logger.info("Débrief hebdo envoyé")
    except Exception as e:
        logger.error(f"Weekly debrief error: {e}")

# ── SURVEILLANCE ANNONCES IMPRÉVUES ──────────────────────────────────────────

async def check_unexpected_events():
    global seen_events, last_events_check
    try:
        events = await get_events()
        current_ids = {e["id"] for e in events}

        if not seen_events:
            seen_events = current_ids
            last_events_check = events
            return

        new_ids = current_ids - seen_events
        if new_ids:
            new_events = [e for e in events if e["id"] in new_ids]
            for event in new_events:
                imp = "🔴 URGENTE" if event["impact"] == "High" else "🟡 IMPORTANTE"
                text = (
                    f"⚡ *ANNONCE IMPRÉVUE — {imp}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕐 {event['time']} [{event['currency']}]\n"
                    f"📌 *{event['title']}*\n"
                    f"Prévision : {event['forecast']}\n"
                    f"Précédent : {event['previous']}\n\n"
                    f"⚠️ _Cette annonce n'était pas au programme — restez vigilant_"
                )
                await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
            seen_events = current_ids

        # Vérifie les résultats d'annonces passées
        now = datetime.now(PARIS_TZ).strftime("%H:%M")
        for event in events:
            if event.get("actual") and event["actual"] != "":
                result_id = f"result_{event['id']}"
                if result_id not in seen_events:
                    seen_events.add(result_id)
                    await post_event_result(event)

    except Exception as e:
        logger.error(f"Check events error: {e}")

async def post_event_result(event: dict):
    try:
        actual   = event.get("actual", "N/A")
        forecast = event.get("forecast", "N/A")
        previous = event.get("previous", "N/A")

        try:
            a = float(actual.replace("%","").replace("K","000").replace("M","000000"))
            f = float(forecast.replace("%","").replace("K","000").replace("M","000000"))
            beat = a >= f
        except:
            beat = None

        analysis = ask_claude(f"""Annonce : {event['title']} [{event['currency']}]
Résultat : {actual} | Prévision : {forecast} | Précédent : {previous}

En 3 lignes maximum :
1. Ce qui a été publié et si c'est au-dessus ou en dessous des attentes
2. Impact probable immédiat sur les marchés (XAU, forex, BTC)
3. Ce que le trader doit faire maintenant (surveiller, attendre, ou opportunité)

Sois direct et utile. Markdown Telegram.""", max_tokens=300)

        emoji = "✅" if beat else ("❌" if beat is False else "📊")
        text = (
            f"{emoji} *RÉSULTAT — {event['title']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Résultat : *{actual}*\n"
            f"Prévision : {forecast} | Précédent : {previous}\n\n"
            f"{analysis}"
        )
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=None)
    except Exception as e:
        logger.error(f"Event result error: {e}")

# ── ANALYSE PAIRE À LA DEMANDE ────────────────────────────────────────────────

async def analyze_pair(pair_key: str) -> str:
    info   = PAIRS.get(pair_key)
    price  = await get_price(pair_key)
    events = await get_events()
    today  = datetime.now(PARIS_TZ).strftime("%A %d %B %Y")

    high = round(price * 1.005, 5) if price > 0 else 0
    low  = round(price * 0.995, 5) if price > 0 else 0
    fibo = calc_fibo(high, low) if high > 0 else {}

    fibo_str = ""
    if fibo:
        fibo_str = (
            f"Range : {low} — {high}\n"
            f"61.8% : {fibo['61.8']}\n"
            f"70.5% : {fibo['70.5']}\n"
            f"79.0% : {fibo['79.0']}\n"
            f"88.6% : {fibo['88.6']}"
        )

    analysis = ask_claude(f"""Analyste ICT/SMC expert. Date : {today}
Paire : {info['name']} | Prix : {price}
Annonces du jour : {format_events(events)}
Fibonacci daily : {fibo_str}

Analyse COURTE et PRÉCISE :
1. BIAIS DAILY : HAUSSIER / BAISSIER / NEUTRE — 1 phrase
2. SUPPORT / RÉSISTANCE clés (2 niveaux chacun)
3. ZONE OTE : niveau optimal d'entrée
4. RISQUE DU JOUR : ce qui peut invalider le biais

Direct, précis, utile. Markdown Telegram.""")

    price_str = f"{price:,.2f}" if price > 0 else "N/A"
    return (
        f"📊 *{info['name']} — Analyse*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Prix : *{price_str}*\n\n"
        f"📅 *ANNONCES DU JOUR*\n{format_events(events)}\n\n"
        f"📐 *FIBONACCI DAILY*\n{fibo_str}\n\n"
        f"🧠 *ANALYSE*\n{analysis}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"_{datetime.now(PARIS_TZ).strftime('%H:%M')} — GoldAttack_"
    )

# ── COMMANDES TELEGRAM ────────────────────────────────────────────────────────

async def handle_pair(update, context, pair_key):
    await update.message.reply_text("⏳ Analyse en cours...")
    text = await analyze_pair(pair_key)
    await update.message.reply_text(text, parse_mode=None)

async def cmd_start(update, context):
    await update.message.reply_text(
        "👋 *GoldAttack Bot*\n\n"
        "📊 *Analyses à la demande :*\n"
        "/xauusd — Or\n"
        "/btcusd — Bitcoin\n"
        "/eurusd — EUR/USD\n"
        "/gbpusd — GBP/USD\n"
        "/eurgbp — EUR/GBP\n"
        "/gbpjpy — GBP/JPY\n\n"
        "🤖 *Automatique :*\n"
        "🌅 08:00 — Briefing + biais du jour\n"
        "🌙 23:00 — Débrief quotidien\n"
        "📋 Vendredi 23:00 — Débrief hebdo\n"
        "⚡ Alertes annonces imprévues\n"
        "📊 Résultats après chaque annonce",
        parse_mode=None
    )

async def cmd_xauusd(u, c): await handle_pair(u, c, "xauusd")
async def cmd_btcusd(u, c): await handle_pair(u, c, "btcusd")
async def cmd_eurusd(u, c): await handle_pair(u, c, "eurusd")
async def cmd_gbpusd(u, c): await handle_pair(u, c, "gbpusd")
async def cmd_eurgbp(u, c): await handle_pair(u, c, "eurgbp")
async def cmd_gbpjpy(u, c): await handle_pair(u, c, "gbpjpy")

# ── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start",  cmd_start))
    tg_app.add_handler(CommandHandler("xauusd", cmd_xauusd))
    tg_app.add_handler(CommandHandler("btcusd", cmd_btcusd))
    tg_app.add_handler(CommandHandler("eurusd", cmd_eurusd))
    tg_app.add_handler(CommandHandler("gbpusd", cmd_gbpusd))
    tg_app.add_handler(CommandHandler("eurgbp", cmd_eurgbp))
    tg_app.add_handler(CommandHandler("gbpjpy", cmd_gbpjpy))

    scheduler = AsyncIOScheduler(timezone=PARIS_TZ)

    # Briefing 8h lun-ven
    scheduler.add_job(morning_briefing, "cron", day_of_week="mon-fri", hour=8,  minute=0)

    # Débrief soir 23h lun-jeu
    scheduler.add_job(evening_debrief,  "cron", day_of_week="mon-thu", hour=23, minute=0)

    # Débrief hebdo vendredi 23h
    scheduler.add_job(weekly_debrief,   "cron", day_of_week="fri",     hour=23, minute=0)

    # Surveillance annonces toutes les 5 min
    scheduler.add_job(check_unexpected_events, "interval", minutes=5)

    scheduler.start()
    logger.info("Scheduler démarré")

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    logger.info("GoldAttack Bot actif 24/7")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
