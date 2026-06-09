import os
import requests


def enviar_telegram(mensaje: str):
    token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("⚠️ Telegram no configurado: falta TOKEN o CHAT_ID")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": mensaje,
            },
            timeout=5,
        )

        if response.status_code != 200:
            print("⚠️ Error Telegram:", response.status_code, response.text)
            return False

        return True

    except Exception as e:
        print("⚠️ Excepción Telegram:", e)
        return False