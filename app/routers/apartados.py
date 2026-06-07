from fastapi import APIRouter, Depends, HTTPException

from database import fetch_one, fetch_all, execute, execute_transaction
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.apartados import ApartadoRequest, LiquidarApartadoRequest

router = APIRouter(tags=["Apartados"])


@router.post("/apartados")
def crear_apartado(data: ApartadoRequest, usuario=Depends(verificar_token)):
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
    disponible_apartar = poblacion_origen - cantidad_apartada

    if disponible_apartar < data.cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No puedes apartar {data.cantidad} {data.tipo_animal}. "
                f"Existencia física: {poblacion_origen}, "
                f"apartados activos: {cantidad_apartada}, "
                f"disponibles para apartar: {disponible_apartar}"
            ),
        )

    execute(
        """
        INSERT INTO apartados
        (cliente_id, id_chiquero, tipo_animal, cantidad, anticipo,
         fecha_apartado, fecha_compromiso, estado, usuario_id, notas)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'activo', %s, %s)
    """,
        (
            data.cliente_id,
            data.id_chiquero,
            data.tipo_animal,
            data.cantidad,
            data.anticipo,
            hora_mexico(),
            data.fecha_compromiso,
            usuario["nombre"],
            data.notas,
        ),
    )

    lote = fetch_one(
        """
        SELECT c.nombre AS corral
        FROM chiqueros c
        WHERE c.id = %s
    """,
        (data.id_chiquero,),
    )

    cliente = fetch_one("SELECT nombre FROM clientes WHERE id = %s", (data.cliente_id,))

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
               CONCAT(ch.zona, ' ', ch.nombre) AS corral_nombre
        FROM apartados a
        JOIN clientes c ON c.id = a.cliente_id
        JOIN chiqueros ch ON ch.id = a.id_chiquero
        WHERE a.estado = 'activo'
        ORDER BY a.fecha_compromiso ASC
    """)


@router.post("/apartados/{apartado_id}/cancelar")
def cancelar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute("UPDATE apartados SET estado = 'cancelado' WHERE id = %s", (apartado_id,))

    return {"ok": True}


@router.post("/apartados/{apartado_id}/liquidar-venta")
def liquidar_apartado_venta(
    apartado_id: int,
    data: LiquidarApartadoRequest,
    usuario=Depends(verificar_token),
):
    apartado = fetch_one(
        """
        SELECT a.*, c.nombre AS cliente_nombre, c.tipo AS cliente_tipo,
               c.descuento_kg, ch.nombre AS corral_nombre
        FROM apartados a
        JOIN clientes c ON c.id = a.cliente_id
        JOIN chiqueros ch ON ch.id = a.id_chiquero
        WHERE a.id = %s
        LIMIT 1
        """,
        (apartado_id,),
    )

    if not apartado:
        raise HTTPException(
            status_code=404,
            detail="Apartado no encontrado",
        )

    if apartado["estado"] != "activo":
        raise HTTPException(
            status_code=400,
            detail=f"Este apartado ya está {apartado['estado']}",
        )

    tipo_animal = apartado["tipo_animal"]
    cantidad = int(apartado["cantidad"])
    anticipo = float(apartado["anticipo"] or 0)

    lote_origen = fetch_one(
        """
        SELECT id, poblacion_actual
        FROM lotes
        WHERE id_chiquero = %s
        AND tipo_animal = %s
        AND poblacion_actual > 0
        LIMIT 1
        """,
        (apartado["id_chiquero"], tipo_animal),
    )

    if not lote_origen:
        raise HTTPException(
            status_code=400,
            detail=f"No hay {tipo_animal} disponibles en ese corral",
        )

    poblacion_origen = int(lote_origen["poblacion_actual"])

    if poblacion_origen < cantidad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay suficientes {tipo_animal} para liquidar el apartado. "
                f"Existencia física: {poblacion_origen}, apartado: {cantidad}"
            ),
        )

    venta_por_cabeza = tipo_animal in ["Destete", "Desecho"]

    if venta_por_cabeza:
        if data.precio_cabeza <= 0:
            raise HTTPException(
                status_code=400,
                detail="Captura un precio pactado válido",
            )

        peso_kg = 0
        precio_final = data.precio_cabeza
        comision_kg = 0
        total_comision = 0
        total_venta = data.precio_cabeza * cantidad
        total_rancho = total_venta
    else:
        if data.peso_kg <= 0:
            raise HTTPException(
                status_code=400,
                detail="Captura un peso válido",
            )

        if data.precio_kg <= 0:
            raise HTTPException(
                status_code=400,
                detail="Captura un precio por kg válido",
            )

        es_beyin = usuario["nombre"].strip().lower() == "beyin"
        precio_minimo_beyin = 45

        if es_beyin and data.precio_kg < precio_minimo_beyin:
            raise HTTPException(
                status_code=400,
                detail=f"Beyin no puede vender por debajo de ${precio_minimo_beyin}/kg",
            )

        descuento_kg = float(apartado["descuento_kg"] or 0)
        precio_neto = data.precio_kg - descuento_kg
        comision_kg = data.comision_kg
        peso_kg = data.peso_kg

        total_venta = peso_kg * precio_neto
        total_comision = comision_kg * peso_kg
        total_rancho = total_venta - total_comision
        precio_final = data.precio_kg

    restante = total_rancho - anticipo

    if total_rancho <= 0:
        raise HTTPException(
            status_code=400,
            detail="El total de la venta debe ser mayor a 0",
        )

    fecha = hora_mexico()

    execute_transaction(
        [
            (
                """UPDATE lotes
                   SET poblacion_actual = poblacion_actual - %s
                   WHERE id = %s""",
                (cantidad, lote_origen["id"]),
            ),
            (
                """INSERT INTO ventas
                   (cliente_id, usuario_id, tipo_animal, cantidad, peso_kg, precio_kg,
                    comision_kg, total_rancho, total_comision, foto_bascula)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')""",
                (
                    apartado["cliente_id"],
                    usuario["id"],
                    tipo_animal,
                    cantidad,
                    peso_kg,
                    precio_final,
                    comision_kg,
                    total_rancho,
                    total_comision,
                ),
            ),
            (
                """UPDATE apartados
                   SET estado = 'liquidado',
                       venta_id = LAST_INSERT_ID()
                   WHERE id = %s""",
                (apartado_id,),
            ),
            (
                """INSERT INTO historial_movimientos
                   (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
                   VALUES (%s, %s, %s, 'VENTA', %s, %s, %s)""",
                (
                    apartado["id_chiquero"],
                    tipo_animal,
                    cantidad,
                    usuario["nombre"],
                    f"Liquidación de apartado — Total ${total_rancho:,.2f}, anticipo ${anticipo:,.2f}, restante ${restante:,.2f}",
                    fecha,
                ),
            ),
            (
                "UPDATE clientes SET ultimo_pedido = %s WHERE id = %s",
                (fecha, apartado["cliente_id"]),
            ),
        ]
    )

    enviar_telegram(
        f"💰 LIQUIDACIÓN DE APARTADO\n"
        f"👤 {usuario['nombre']}\n"
        f"👥 Cliente: {apartado['cliente_nombre']}\n"
        f"🐖 {cantidad} {tipo_animal} — {apartado['corral_nombre']}\n"
        f"💵 Total rancho: ${total_rancho:,.2f}\n"
        f"💰 Anticipo: ${anticipo:,.2f}\n"
        f"🧾 Restante: ${restante:,.2f}\n"
        f"🕐 {fecha.strftime('%d/%m/%Y %H:%M')}"
    )

    return {
        "ok": True,
        "mensaje": "Apartado liquidado y venta registrada",
        "total_rancho": total_rancho,
        "anticipo": anticipo,
        "restante": restante,
    }

@router.post("/apartados/{apartado_id}/liquidar")
def liquidar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute("UPDATE apartados SET estado = 'liquidado' WHERE id = %s", (apartado_id,))

    return {"ok": True}
