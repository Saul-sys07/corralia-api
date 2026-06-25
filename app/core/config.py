# app/core/config.py

import os
from dotenv import load_dotenv

load_dotenv()


SECRET_KEY = os.getenv("SECRET_KEY")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RANCHO_LAT = float(os.getenv("RANCHO_LAT", "19.845154"))
RANCHO_LNG = float(os.getenv("RANCHO_LNG", "-99.906298"))
RADIO_METROS = int(os.getenv("RADIO_METROS", "500"))

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://corralia-react.vercel.app",
    "https://corralia-react-h0e10gno8-saul-sys07s-projects.vercel.app",
]
