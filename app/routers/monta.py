from datetime import datetime, timedelta

import cloudinary.uploader
from fastapi import APIRouter, Depends

from database import fetch_one, execute
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.monta import MontaRequest, VerificarPreñezRequest


router = APIRouter(tags=["Monta"])


@router.post("/monta")
def registrar_monta(data: MontaRequest, usuario=Depends(verificar_token)):
    fecha_monta = datetime.strptime(data.fecha_monta, "%Y-%m-%d").date()
    fecha_parto = fecha_monta + timedelta(days=114)

    foto_url = None

    if data.foto_base64:
        nombre_foto = f"corralia/montas/{data.lote_id}_{fecha_monta}"

        resultado = cloudinary.uploader.upload(
            f"data:image/jpeg;base64,{data.foto_base64}",
            public_id=nombre_foto,
            overwrite=True,
        )

        foto_url = resultado["secure_url"]

    execute("""
        UPDATE lotes SET
            estado_pie_cria = 'Montada',
            fecha_monta = %s,
            fecha_parto_estimada = %s,
            foto_pie_cria = %s
        WHERE id = %s
    """, (
        fecha_monta,
        fecha_parto,
        foto_url,
        data.lote_id,
    ))

    lote = fetch_one("""
        SELECT c.nombre AS corral
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.id = %s
    """, (data.lote_id,))

    enviar_telegram(
        f"🐷 MONTA REGISTRADA\n"
        f"👤 {usuario['nombre']}\n"
        f"📍 {lote['corral']}\n"
        f"📅 Fecha monta: {fecha_monta}\n"
        f"📅 Parto estimado: {fecha_parto}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    return {"ok": True, "fecha_parto": str(fecha_parto)}


@router.post("/monta/verificar")
def verificar_preñez(
    data: VerificarPreñezRequest,
    usuario=Depends(verificar_token)
):
    lote = fetch_one("""
        SELECT l.*, c.nombre AS corral
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.id = %s
    """, (data.lote_id,))

    if data.confirma_preñez:
        execute(
            "UPDATE lotes SET estado_pie_cria = 'Gestante' WHERE id = %s",
            (data.lote_id,)
        )

        enviar_telegram(
            f"✅ PREÑEZ CONFIRMADA\n"
            f"👤 {usuario['nombre']}\n"
            f"📍 {lote['corral']}\n"
            f"📅 Parto estimado: {lote['fecha_parto_estimada']}\n"
            f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
        )

    else:
        execute("""
            UPDATE lotes SET
                estado_pie_cria = 'Disponible',
                fecha_monta = NULL,
                fecha_parto_estimada = NULL
            WHERE id = %s
        """, (data.lote_id,))

        enviar_telegram(
            f"❌ REGRESÓ A CALOR\n"
            f"👤 {usuario['nombre']}\n"
            f"📍 {lote['corral']}\n"
            f"🐷 Vuelve a estado Disponible\n"
            f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
        )

    return {"ok": True}