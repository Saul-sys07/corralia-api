# app/core/telegram.py

import requests as req
from app.core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def enviar_telegram(mensaje: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje},
            timeout=5
        )
    except Exception:
        pass