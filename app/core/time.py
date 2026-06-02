# app/core/time.py

from datetime import datetime
from zoneinfo import ZoneInfo


def hora_mexico():
    return datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)