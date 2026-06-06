from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.schemas.clientes import ClienteRequest

router = APIRouter(tags=["Clientes"])


@router.get("/clientes")
def get_clientes(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.*, u.nombre AS vendedor
        FROM clientes c
        JOIN usuarios u ON u.id = c.usuario_id
        WHERE c.activo = 1
        ORDER BY c.nombre
    """)


@router.get("/clientes/lista")
def get_clientes_lista(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.id, c.nombre, c.telefono, c.tipo, u.nombre AS vendedor,
               COUNT(v.id) AS num_compras,
               IFNULL(SUM(v.total_rancho), 0) AS total_comprado
        FROM clientes c
        JOIN usuarios u ON u.id = c.usuario_id
        LEFT JOIN ventas v ON v.cliente_id = c.id
        WHERE c.activo = 1
        GROUP BY c.id
        ORDER BY c.nombre
    """)


@router.post("/clientes")
def crear_cliente(data: ClienteRequest, usuario=Depends(verificar_token)):
    existente = fetch_one(
        "SELECT id FROM clientes WHERE telefono = %s", (data.telefono,)
    )

    if existente:
        raise HTTPException(
            status_code=400, detail="Ya existe un cliente con ese teléfono"
        )

    execute(
        "INSERT INTO clientes (nombre, telefono, tipo, usuario_id) VALUES (%s, %s, %s, %s)",
        (data.nombre, data.telefono, data.tipo, data.usuario_id),
    )

    return {"ok": True}


@router.post("/clientes/actualizar-ciclo")
def actualizar_ciclo_clientes(usuario=Depends(verificar_token)):
    hace_un_anio = datetime.now() - timedelta(days=365)

    execute(
        """
        UPDATE clientes SET tipo = 'Disponible'
        WHERE tipo = 'Retenido'
        AND (ultimo_pedido IS NULL OR ultimo_pedido < %s)
    """,
        (hace_un_anio,),
    )

    return {"ok": True}
