import os
import asyncio
import logging
from flask import Flask, request, jsonify
from telegram import Bot
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

BOT_TOKEN = "8755477782:AAFrnbNhCqy8XfBpRd9TlzIzvL_ydRXIL78"
CHAT_ID   = "1035061255"
SECRET    = "goldattack2025"

bot = Bot(token=BOT_TOKEN)

@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.args.get("secret")
    if secret != SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data    = request.get_json(silent=True) or {}
    message = data.get("message", "⚡ Signal XAUUSD")
    logger.info(f"Signal reçu : {message}")
    asyncio.run(send_alert(message))
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Goldattack Bot running"}), 200

async def send_alert(message: str):
    try:
        is_bull   = "Bullish" in message or "bullish" in message
        direction = "🟢 BULLISH" if is_bull else "🔴 BEARISH"
        emoji     = "📈" if is_bull else "📉"

        # Message texte formaté
        await bot.send_message(
            chat_id=CHAT_ID,
            text=(
                f"┌─────────────────────┐\n"
                f"│  {emoji}  *XAU/USD SIGNAL*  {emoji}  │\n"
                f"├─────────────────────┤\n"
                f"│  {direction}\n"
                f"│  {message}\n"
                f"├─────────────────────┤\n"
                f"│  ⚡ FVG dans zone OTE\n"
                f"│  📐 Fibo 61.8% – 88.6%\n"
                f"└─────────────────────┘"
            ),
            parse_mode=ParseMode.MARKDOWN
        )

        # 2ème message pour forcer la notification sonore sur iPhone
        await bot.send_message(
            chat_id=CHAT_ID,
            text="🔔 *ENTRE SUR LE CHART MAINTENANT*",
            parse_mode=ParseMode.MARKDOWN
        )

        logger.info("Alerte envoyée avec succès")

    except Exception as e:
        logger.error(f"Erreur : {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
