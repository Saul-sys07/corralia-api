from fastapi import APIRouter, Depends

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.apartados import ApartadoRequest


router = APIRouter(tags=["Apartados"])


@router.post("/apartados")
def crear_apartado(data: ApartadoRequest, usuario=Depends(verificar_token)):
    execute("""
        INSERT INTO apartados
        (cliente_id, id_chiquero, tipo_animal, cantidad, anticipo,
         fecha_apartado, fecha_compromiso, estado, usuario_id, notas)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'activo', %s, %s)
    """, (
        data.cliente_id,
        data.id_chiquero,
        data.tipo_animal,
        data.cantidad,
        data.anticipo,
        hora_mexico(),
        data.fecha_compromiso,
        usuario["nombre"],
        data.notas,
    ))

    lote = fetch_one("""
        SELECT c.nombre AS corral
        FROM chiqueros c
        WHERE c.id = %s
    """, (data.id_chiquero,))

    cliente = fetch_one(
        "SELECT nombre FROM clientes WHERE id = %s",
        (data.cliente_id,)
    )

    enviar_telegram(
        f"📋 APARTADO\n"
        f"👤 {usuario['nombre']}\n"
        f"🐷 {data.cantidad} {data.tipo_animal} — {lote['corral']}\n"
        f"💵 Anticipo: ${data.anticipo:,.2f}\n"
        f"📅 Compromiso: {data.fecha_compromiso}\n"
        f"👥 Cliente: {cliente['nombre']}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    return {"ok": True}


@router.get("/apartados")
def get_apartados(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT a.*, c.nombre AS cliente_nombre, c.tipo AS cliente_tipo,
               ch.nombre AS corral_nombre
        FROM apartados a
        JOIN clientes c ON c.id = a.cliente_id
        JOIN chiqueros ch ON ch.id = a.id_chiquero
        WHERE a.estado = 'activo'
        ORDER BY a.fecha_compromiso ASC
    """)


@router.post("/apartados/{apartado_id}/cancelar")
def cancelar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute(
        "UPDATE apartados SET estado = 'cancelado' WHERE id = %s",
        (apartado_id,)
    )

    return {"ok": True}


@router.post("/apartados/{apartado_id}/liquidar")
def liquidar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute(
        "UPDATE apartados SET estado = 'liquidado' WHERE id = %s",
        (apartado_id,)
    )

    return {"ok": True}