from fastapi import APIRouter, Depends, HTTPException
from database import fetch_one, fetch_all, execute, execute_transaction
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.ventas import VentaRequest

router = APIRouter(tags=["Ventas"])


@router.get("/precio-dia")
def get_precio_dia(usuario=Depends(verificar_token)):
    row = fetch_one("SELECT valor FROM configuracion WHERE clave = 'precio_kg'")
    return {"precio": float(row["valor"]) if row else 48.00}


@router.post("/venta")
def registrar_venta(data: VentaRequest, usuario=Depends(verificar_token)):
    if data.cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")

    lote_origen = fetch_one(
        """
        SELECT id, poblacion_actual
        FROM lotes
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND poblacion_actual > 0
        LIMIT 1
    """,
        (data.id_chiquero, data.tipo_animal),
    )

    if not lote_origen:
        raise HTTPException(
            status_code=400,
            detail=f"No hay {data.tipo_animal} disponibles en ese corral",
        )

    poblacion_origen = int(lote_origen["poblacion_actual"])

    apartados_row = fetch_one(
        """
        SELECT IFNULL(SUM(cantidad), 0) AS cantidad_apartada
        FROM apartados
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND estado = 'activo'
    """,
        (data.id_chiquero, data.tipo_animal),
    )

    cantidad_apartada = int(apartados_row["cantidad_apartada"] or 0)
    disponible_venta = poblacion_origen - cantidad_apartada

    if disponible_venta < data.cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay suficientes {data.tipo_animal} disponibles para venta. "
                f"Existencia física: {poblacion_origen}, "
                f"apartados activos: {cantidad_apartada}, "
                f"disponibles para venta: {disponible_venta}, "
                f"intento de venta: {data.cantidad}"
            ),
        )

    es_beyin = usuario["nombre"].strip().lower() == "beyin"
    precio_minimo_beyin = 45

    if (
        es_beyin
        and not data.es_destete
        and data.tipo_animal != "Desecho"
        and data.precio_kg < precio_minimo_beyin
    ):

        raise HTTPException(
            status_code=400,
            detail=f"Beyin no puede vender por debajo de ${precio_minimo_beyin}/kg",
        )

    if data.tipo_animal == "Desecho" and data.precio_cabeza <= 0:
        raise HTTPException(
            status_code=400, detail="Captura un precio pactado válido para Desecho"
        )

    fecha = hora_mexico()
    comision_kg = 0 if data.tipo_animal in ["Destete", "Desecho"] else data.comision_kg
    total_comision = (
        0 if data.tipo_animal in ["Destete", "Desecho"] else data.total_comision
    )
    precio_final = (
        data.precio_cabeza
        if data.es_destete or data.tipo_animal == "Desecho"
        else data.precio_kg
    )

    execute_transaction(
        [
            (
                """UPDATE lotes
           SET poblacion_actual = poblacion_actual - %s
           WHERE id = %s""",
                (data.cantidad, lote_origen["id"]),
            ),
            (
                """INSERT INTO ventas
           (cliente_id, usuario_id, tipo_animal, cantidad, peso_kg, precio_kg,
            comision_kg, total_rancho, total_comision, foto_bascula)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')""",
                (
                    data.cliente_id,
                    usuario["id"],
                    data.tipo_animal,
                    data.cantidad,
                    data.peso_kg,
                    precio_final,
                    comision_kg,
                    data.total_rancho,
                    total_comision,
                ),
            ),
            (
                """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'VENTA', %s, %s, %s)""",
                (
                    data.id_chiquero,
                    data.tipo_animal,
                    data.cantidad,
                    usuario["nombre"],
                    f"Venta — ${data.total_rancho:,.2f}",
                    fecha,
                ),
            ),
        ]
    )

    cliente_actual = fetch_one(
        "SELECT tipo FROM clientes WHERE id = %s", (data.cliente_id,)
    )

    if cliente_actual:
        if cliente_actual["tipo"] in ("Nuevo", "Recuperado"):
            execute(
                "UPDATE clientes SET tipo = 'Retenido' WHERE id = %s",
                (data.cliente_id,),
            )

    execute(
        "UPDATE clientes SET ultimo_pedido = %s WHERE id = %s",
        (hora_mexico(), data.cliente_id),
    )

    enviar_telegram(
        f"💰 VENTA\n"
        f"👤 {usuario['nombre']}\n"
        f"🐖 {data.cantidad} {data.tipo_animal} — {data.peso_kg}kg\n"
        f"💵 ${data.total_rancho:,.2f}\n"
        f"🕐 {fecha.strftime('%d/%m/%Y %H:%M')}"
    )

    return {
        "ok": True,
        "mensaje": f"Venta registrada — ${data.total_rancho:,.2f}",
    }


@router.get("/ventas/historial")
def get_historial_ventas(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT v.fecha, c.nombre AS cliente, c.tipo AS tipo_cliente,
               u.nombre AS registrado_por,
               uc.nombre AS vendedor_cliente,
               v.tipo_animal, v.cantidad,
               v.peso_kg, v.precio_kg, v.total_rancho, v.total_comision
        FROM ventas v
        JOIN clientes c ON c.id = v.cliente_id
        JOIN usuarios u ON u.id = v.usuario_id
        JOIN usuarios uc ON uc.id = c.usuario_id
        ORDER BY v.fecha DESC
        LIMIT 100
    """)


@router.get("/ventas/comisiones")
def get_comisiones(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT 
            u.nombre AS vendedor,
            COUNT(v.id) AS num_ventas,
            IFNULL(SUM(v.total_comision), 0) AS total_comision,
            IFNULL(SUM(v.peso_kg), 0) AS kg_vendidos
        FROM ventas v
        JOIN clientes c ON c.id = v.cliente_id
        JOIN usuarios u ON u.id = c.usuario_id
        GROUP BY c.usuario_id, u.nombre
        ORDER BY total_comision DESC
    """)
