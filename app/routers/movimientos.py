from fastapi import APIRouter, Depends, HTTPException

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.movimientos import (
    MuerteRequest,
    TrasladoRequest,
    EtapaRequest,
    PartoRequest,
)


router = APIRouter(tags=["Movimientos"])


@router.post("/muerte")
def registrar_muerte(data: MuerteRequest, usuario=Depends(verificar_token)):
    if data.cantidad <= 0:
        raise HTTPException(
            status_code=400,
            detail="La cantidad debe ser mayor a 0"
        )

    lote = fetch_one("""
        SELECT id, poblacion_actual
        FROM lotes
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND poblacion_actual > 0
        LIMIT 1
    """, (data.id_chiquero, data.tipo_animal))

    if not lote:
        raise HTTPException(
            status_code=400,
            detail=f"No hay {data.tipo_animal} disponibles en ese corral"
        )

    poblacion_actual = int(lote["poblacion_actual"])

    if poblacion_actual < data.cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay suficientes {data.tipo_animal} para registrar la muerte. "
                f"Disponibles: {poblacion_actual}, intento de muerte: {data.cantidad}"
            )
        )

    execute(
        """UPDATE lotes
           SET poblacion_actual = poblacion_actual - %s
           WHERE id = %s""",
        (data.cantidad, lote["id"])
    )

    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'MUERTE', %s, %s, %s)""",
        (
            data.id_chiquero,
            data.tipo_animal,
            data.cantidad,
            usuario["nombre"],
            f"Causa: {data.causa}",
            hora_mexico(),
        )
    )

    enviar_telegram(
        f"💀 MUERTE\n"
        f"👤 {usuario['nombre']}\n"
        f"🐖 {data.cantidad} {data.tipo_animal}\n"
        f"📋 Causa: {data.causa}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    return {"ok": True}


@router.post("/traslado")
def registrar_traslado(data: TrasladoRequest, usuario=Depends(verificar_token)):
    tipo_destino = data.nueva_etapa or data.tipo_animal

    if data.cantidad <= 0:
        raise HTTPException(
            status_code=400,
            detail="La cantidad debe ser mayor a 0"
        )

    lote_origen = fetch_one("""
        SELECT id, poblacion_actual
        FROM lotes
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND poblacion_actual > 0
        LIMIT 1
    """, (data.id_origen, data.tipo_animal))

    if not lote_origen:
        raise HTTPException(
            status_code=400,
            detail=f"No hay {data.tipo_animal} disponibles en el corral origen"
        )

    poblacion_origen = int(lote_origen["poblacion_actual"])

    if poblacion_origen < data.cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay suficientes {data.tipo_animal} en el corral origen. "
                f"Disponibles: {poblacion_origen}, intento de traslado: {data.cantidad}"
            )
        )

    execute(
        """UPDATE lotes
           SET poblacion_actual = poblacion_actual - %s
           WHERE id = %s""",
        (data.cantidad, lote_origen["id"])
    )

    execute(
        """INSERT INTO lotes
           (id_chiquero, tipo_animal, poblacion_actual, fecha_entrada, estado_pie_cria)
           VALUES (%s, %s, %s, %s, IF(%s = 'Pie de Cría', 'Disponible', NULL))
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (
            data.id_destino,
            tipo_destino,
            data.cantidad,
            hora_mexico(),
            tipo_destino,
        )
    )

    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_origen, id_chiquero_destino, tipo_animal, cantidad,
            tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, %s, 'TRASPASO', %s, %s, %s)""",
        (
            data.id_origen,
            data.id_destino,
            data.tipo_animal,
            data.cantidad,
            usuario["nombre"],
            f"Avance de etapa: {data.tipo_animal} → {tipo_destino}"
            if data.nueva_etapa
            else f"Traspaso de {data.cantidad} {data.tipo_animal}",
            hora_mexico(),
        )
    )

    corral_origen = fetch_one(
        "SELECT nombre, zona FROM chiqueros WHERE id = %s",
        (data.id_origen,)
    )

    corral_destino = fetch_one(
        "SELECT nombre, zona FROM chiqueros WHERE id = %s",
        (data.id_destino,)
    )

    enviar_telegram(
        f"🔄 TRASPASO\n"
        f"👤 {usuario['nombre']}\n"
        f"🐖 {data.cantidad} {data.tipo_animal}\n"
        f"📍 {corral_origen['zona']} {corral_origen['nombre']} → "
        f"{corral_destino['zona']} {corral_destino['nombre']}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    return {"ok": True}


@router.get("/corrales-destino")
def get_corrales_destino(
    tipo_animal: str,
    excluir_id: int,
    usuario=Depends(verificar_token)
):
    return fetch_all("""
        SELECT c.id, c.nombre, c.zona, c.tipo, c.capacidad_max,
               IFNULL(SUM(l.poblacion_actual), 0) AS poblacion_actual
        FROM chiqueros c
        LEFT JOIN lotes l ON c.id = l.id_chiquero AND l.poblacion_actual > 0
        WHERE c.id != %s
        GROUP BY c.id
        ORDER BY c.zona, CAST(REGEXP_SUBSTR(c.nombre, '[0-9]+') AS UNSIGNED), c.nombre
    """, (excluir_id,))


@router.post("/etapa")
def cambiar_etapa(data: EtapaRequest, usuario=Depends(verificar_token)):
    if data.cantidad <= 0:
        raise HTTPException(
            status_code=400,
            detail="La cantidad debe ser mayor a 0"
        )

    lote_origen = fetch_one("""
        SELECT id, poblacion_actual
        FROM lotes
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND poblacion_actual > 0
        LIMIT 1
    """, (data.id_chiquero, data.tipo_animal))

    if not lote_origen:
        raise HTTPException(
            status_code=400,
            detail=f"No hay {data.tipo_animal} disponibles en ese corral"
        )

    poblacion_origen = int(lote_origen["poblacion_actual"])

    if poblacion_origen < data.cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay suficientes {data.tipo_animal} para cambiar de etapa. "
                f"Disponibles: {poblacion_origen}, intento de cambio: {data.cantidad}"
            )
        )

    execute(
        """UPDATE lotes
           SET poblacion_actual = poblacion_actual - %s
           WHERE id = %s""",
        (data.cantidad, lote_origen["id"])
    )

    execute(
        """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual, fecha_entrada)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (
            data.id_chiquero,
            data.nueva_etapa,
            data.cantidad,
            hora_mexico(),
        )
    )

    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'CAMBIO_ESTADO', %s, %s, %s)""",
        (
            data.id_chiquero,
            data.nueva_etapa,
            data.cantidad,
            usuario["nombre"],
            f"Cambio de etapa: {data.tipo_animal} → {data.nueva_etapa} sin traspaso fisico",
            hora_mexico(),
        )
    )

    return {"ok": True}


@router.post("/parto")
def registrar_parto(data: PartoRequest, usuario=Depends(verificar_token)):
    if data.crias_vivas > 0:
        execute(
            """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
               VALUES (%s, 'Crías', %s)
               ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
            (data.id_chiquero, data.crias_vivas)
        )

        execute(
            """INSERT INTO historial_movimientos
               (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
               VALUES (%s, 'Crías', %s, 'PARTO', %s, %s, %s)""",
            (
                data.id_chiquero,
                data.crias_vivas,
                usuario["nombre"],
                f"Parto: {data.crias_vivas} crías vivas",
                hora_mexico(),
            )
        )

    if data.no_logradas > 0:
        execute(
            """INSERT INTO historial_movimientos
               (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
               VALUES (%s, 'Crías', %s, 'MUERTE', %s, %s, %s)""",
            (
                data.id_chiquero,
                data.no_logradas,
                usuario["nombre"],
                f"Parto: {data.no_logradas} no logradas",
                hora_mexico(),
            )
        )

    execute(
        """UPDATE lotes SET estado_pie_cria = 'Parida'
           WHERE id_chiquero = %s AND tipo_animal = 'Pie de Cría'""",
        (data.id_chiquero,)
    )

    enviar_telegram(
        f"🍼 PARTO\n"
        f"👤 {usuario['nombre']}\n"
        f"✅ {data.crias_vivas} crías vivas\n"
        f"❌ {data.no_logradas} no logradas\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    return {"ok": True}


@router.get("/historial/movimientos")
def get_historial_movimientos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT h.tipo_evento, h.tipo_animal, h.cantidad, h.notas,
               h.id_usuario, h.fecha,
               CONCAT(co.zona, ' ', co.nombre) AS corral_origen,
               CONCAT(cd.zona, ' ', cd.nombre) AS corral_destino
        FROM historial_movimientos h
        LEFT JOIN chiqueros co ON co.id = h.id_chiquero_origen
        LEFT JOIN chiqueros cd ON cd.id = h.id_chiquero_destino
        ORDER BY h.fecha DESC
        LIMIT 100
    """)