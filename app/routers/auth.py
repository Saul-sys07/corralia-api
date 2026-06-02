import math

from fastapi import APIRouter, HTTPException

from database import fetch_one, execute
from app.core.config import RANCHO_LAT, RANCHO_LNG, RADIO_METROS
from app.core.security import crear_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.auth import LoginRequest


router = APIRouter(tags=["Auth"])


def verificar_alertas_preñez():
    from datetime import datetime, timedelta
    from database import fetch_all

    hoy = hora_mexico().date()

    lotes = fetch_all("""
        SELECT l.id, l.fecha_monta, c.nombre AS corral
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.tipo_animal = 'Pie de Cría'
        AND l.poblacion_actual > 0
        AND l.fecha_monta IS NOT NULL
        AND l.estado_pie_cria NOT IN ('Vacía', 'Parida')
    """)

    for lote in lotes:
        fecha_monta = lote["fecha_monta"]

        if hasattr(fecha_monta, "date"):
            fecha_monta = fecha_monta.date()
        elif isinstance(fecha_monta, str):
            fecha_monta = datetime.strptime(fecha_monta, "%Y-%m-%d").date()

        dia_21 = fecha_monta + timedelta(days=21)
        dia_107 = fecha_monta + timedelta(days=107)

        if hoy == dia_21:
            ya = fetch_one(
                "SELECT id FROM notificaciones WHERE id_lote=%s AND tipo='verificar_preñez'",
                (lote["id"],)
            )
            if not ya:
                enviar_telegram(
                    f"🔍 VERIFICAR PREÑEZ\n"
                    f"📍 {lote['corral']}\n"
                    f"📅 Han pasado 21 días de la monta"
                )

        if hoy == dia_107:
            ya = fetch_one(
                "SELECT id FROM notificaciones WHERE id_lote=%s AND tipo='alerta_parto'",
                (lote["id"],)
            )
            if not ya:
                enviar_telegram(
                    f"⚠️ PARTO PRÓXIMO\n"
                    f"📍 {lote['corral']}\n"
                    f"📅 Faltan 7 días para el parto estimado"
                )


@router.post("/login")
def login(data: LoginRequest):
    usuario = fetch_one(
        "SELECT * FROM usuarios WHERE pin = %s AND activo = 1",
        (data.pin,)
    )

    if not usuario:
        raise HTTPException(status_code=401, detail="PIN incorrecto")

    roles_campo = [
        "parideras",
        "crecimiento",
        "gestacion",
        "ayudante_general",
        "encargado_general",
    ]

    if usuario["rol"] in roles_campo:
        if data.lat is not None and data.lng is not None:
            dlat = math.radians(data.lat - RANCHO_LAT)
            dlng = math.radians(data.lng - RANCHO_LNG)

            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(RANCHO_LAT))
                * math.cos(math.radians(data.lat))
                * math.sin(dlng / 2) ** 2
            )

            distancia = 6371000 * 2 * math.asin(math.sqrt(a))

            if distancia > RADIO_METROS:
                hora = hora_mexico().strftime("%d/%m/%Y %H:%M")
                enviar_telegram(
                    f"⚠️ ALERTA CORRALIA\n"
                    f"👤 {usuario['nombre']} ({usuario['rol']})\n"
                    f"📍 Está a {int(distancia)}m del rancho\n"
                    f"🕐 {hora}\n"
                    f"💸 Multa aplicable: $50"
                )
        else:
            hora = hora_mexico().strftime("%d/%m/%Y %H:%M")
            enviar_telegram(
                f"⚠️ ALERTA CORRALIA\n"
                f"👤 {usuario['nombre']} ({usuario['rol']})\n"
                f"📍 No compartió ubicación\n"
                f"🕐 {hora}\n"
                f"💸 Multa aplicable: $50"
            )

    verificar_alertas_preñez()

    execute(
        "UPDATE usuarios SET ultimo_acceso = %s WHERE id = %s",
        (hora_mexico(), usuario["id"])
    )

    return {
        "token": crear_token(usuario),
        "usuario": {
            "id": usuario["id"],
            "nombre": usuario["nombre"],
            "rol": usuario["rol"],
            "primer_acceso": bool(usuario["primer_acceso"]),
        },
    }