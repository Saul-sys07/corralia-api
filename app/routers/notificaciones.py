from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.time import hora_mexico


router = APIRouter(tags=["Notificaciones"])


@router.get("/notificaciones")
def get_notificaciones(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    lotes_activos = fetch_all("""
        SELECT l.id, l.id_chiquero, l.fecha_monta, l.fecha_parto_estimada,
               c.nombre AS corral, c.zona
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.tipo_animal = 'Pie de Cría'
        AND l.poblacion_actual > 0
        AND l.fecha_monta IS NOT NULL
        AND l.estado_pie_cria NOT IN ('Vacía', 'Parida')
    """)

    for lote in lotes_activos:
        fecha_monta = lote["fecha_monta"]

        if not fecha_monta:
            continue

        if isinstance(fecha_monta, str):
            fecha_monta = datetime.strptime(fecha_monta, "%Y-%m-%d").date()
        elif hasattr(fecha_monta, "date"):
            fecha_monta = fecha_monta.date()

        dia_21 = fecha_monta + timedelta(days=21)
        dia_107 = fecha_monta + timedelta(days=107)

        fechas_programadas = [
            (
                dia_21,
                "verificar_preñez",
                f"🔍 Verificar preñez — {lote['corral']} (día 21 de monta)",
            ),
            (
                dia_107,
                "alerta_parto",
                f"⚠️ Parto próximo — {lote['corral']} (faltan 7 días)",
            ),
        ]

        for fecha_prog, tipo, mensaje in fechas_programadas:
            existente = fetch_one("""
                SELECT id FROM notificaciones
                WHERE id_lote = %s
                AND tipo = %s
            """, (lote["id"], tipo))

            if not existente and hoy >= fecha_prog:
                execute("""
                    INSERT INTO notificaciones
                    (tipo, mensaje, id_lote, roles_destino, fecha_creacion, fecha_programada)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    tipo,
                    mensaje,
                    lote["id"],
                    "admin,encargado_general,gestacion",
                    hora_mexico(),
                    fecha_prog,
                ))

    notificaciones = fetch_all("""
        SELECT *
        FROM notificaciones
        WHERE roles_destino LIKE %s
        AND (visto_por NOT LIKE %s OR visto_por = '')
        AND fecha_programada <= %s
        ORDER BY fecha_creacion DESC
        LIMIT 20
    """, (
        f"%{usuario['rol']}%",
        f"%{usuario['nombre']}%",
        hoy,
    ))

    return notificaciones


@router.post("/notificaciones/{notif_id}/vista")
def marcar_vista(notif_id: int, usuario=Depends(verificar_token)):
    notif = fetch_one(
        "SELECT visto_por FROM notificaciones WHERE id = %s",
        (notif_id,)
    )

    if notif:
        visto_por = notif["visto_por"] or ""

        if usuario["nombre"] not in visto_por:
            nuevo = f"{visto_por},{usuario['nombre']}".strip(",")

            execute(
                "UPDATE notificaciones SET visto_por = %s WHERE id = %s",
                (nuevo, notif_id)
            )

    return {"ok": True}