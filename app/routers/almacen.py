import cloudinary.uploader

from fastapi import APIRouter, Depends

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.almacen import (
    CompraRequest,
    RevolturaRequest,
    FotoTicketRequest,
    RacionRequest,
    SalidaAlimentoRequest,
)


router = APIRouter(tags=["Almacén"])


@router.get("/almacen/inventario")
def get_inventario(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT producto, unidad,
               SUM(CASE WHEN tipo='entrada' THEN cantidad ELSE -cantidad END) AS stock,
               SUM(CASE WHEN tipo='entrada' AND costo IS NOT NULL THEN costo ELSE 0 END) AS total_invertido
        FROM almacen
        WHERE producto NOT IN (
            'Gasolina camioneta', 'Gasolina bomba',
            'Medicamento/Vacuna', 'Material construcción',
            'Foto ticket'
        )
        AND producto NOT LIKE 'Otro:%'
        GROUP BY producto, unidad
        HAVING stock > 0
        ORDER BY
            CASE producto
                WHEN 'Revoltura lista' THEN 0
                WHEN 'Maíz molido' THEN 1
                WHEN 'Salvado' THEN 2
                WHEN 'Soya' THEN 3
                WHEN 'Sal/Omega/Minerales' THEN 4
                WHEN 'Melaza' THEN 5
                ELSE 6
            END
    """)


@router.get("/almacen/saldo")
def get_saldo(usuario=Depends(verificar_token)):
    dep = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito'")
    sue = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo'")
    alm = fetch_one("SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL")
    ven = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas")

    saldo = float(dep["t"]) + float(ven["t"]) - float(sue["t"]) - float(alm["t"])

    return {"saldo": saldo}


@router.post("/almacen/compra")
def registrar_compra(data: CompraRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()

    for item in data.items:
        execute(
            """INSERT INTO almacen
               (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
               VALUES ('entrada', %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                item.categoria,
                item.producto,
                item.cantidad,
                item.unidad,
                item.costo,
                f"Compra — descuento: ${data.descuento:.2f}",
                usuario["nombre"],
                fecha,
            )
        )

    total = sum(i.costo for i in data.items)

    enviar_telegram(
        f"🏚️ COMPRA ALMACÉN\n"
        f"👤 {usuario['nombre']}\n"
        f"📦 {len(data.items)} productos\n"
        f"💵 ${total:,.2f}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )

    if data.descuento > 0:
        execute(
            """INSERT INTO almacen
               (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
               VALUES ('entrada', 'Descuento', 'Descuento en compra', 0, 'pieza', %s, %s, %s, %s)""",
            (
                -data.descuento,
                "Descuento aplicado a compra",
                usuario["nombre"],
                fecha,
            )
        )

    return {"ok": True}


@router.post("/almacen/revoltura")
def hacer_revoltura(data: RevolturaRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()

    kg_revoltura = (
        (data.maiz * 40)
        + (data.salvado * 25)
        + (data.soya * 40)
        + data.sal
    )

    notas = (
        f"Revoltura: {data.maiz:.0f}bt maíz + "
        f"{data.salvado:.0f}bt salvado + "
        f"{data.soya:.0f}bt soya + "
        f"{data.sal:.0f}kg sal + "
        f"{data.melaza:.0f}L melaza"
    )

    ingredientes = [
        ("Maíz molido", data.maiz, "bulto"),
        ("Salvado", data.salvado, "bulto"),
        ("Soya", data.soya, "bulto"),
        ("Sal/Omega/Minerales", data.sal, "kg"),
        ("Melaza", data.melaza, "litro"),
    ]

    for prod, cant, unid in ingredientes:
        if cant > 0:
            execute(
                """INSERT INTO almacen
                   (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
                   VALUES ('salida', 'Ingredientes revoltura', %s, %s, %s, NULL, %s, %s, %s)""",
                (
                    prod,
                    cant,
                    unid,
                    notas,
                    usuario["nombre"],
                    fecha,
                )
            )

    execute(
        """INSERT INTO almacen
           (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
           VALUES ('entrada', 'revoltura', 'Revoltura lista', %s, 'kg', NULL, %s, %s, %s)""",
        (
            kg_revoltura,
            notas,
            usuario["nombre"],
            fecha,
        )
    )

    return {"ok": True, "kg_revoltura": kg_revoltura}


@router.post("/almacen/foto-ticket")
def subir_foto_ticket(data: FotoTicketRequest, usuario=Depends(verificar_token)):
    nombre_foto = (
        f"corralia/tickets/{usuario['nombre']}_"
        f"{hora_mexico().date()}_"
        f"{hora_mexico().strftime('%H%M%S')}"
    )

    resultado = cloudinary.uploader.upload(
        f"data:image/jpeg;base64,{data.foto_base64}",
        public_id=nombre_foto,
        overwrite=False
    )

    url = resultado["secure_url"]

    execute(
        """INSERT INTO almacen
           (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
           VALUES ('entrada', 'Evidencia', 'Foto ticket', 0, 'pieza', NULL, %s, %s, %s)""",
        (
            url,
            usuario["nombre"],
            hora_mexico(),
        )
    )

    return {"ok": True, "url": url}


@router.get("/almacen/tickets")
def get_tickets(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT notas AS url, usuario_id, fecha
        FROM almacen
        WHERE categoria = 'Evidencia'
        AND producto = 'Foto ticket'
        ORDER BY fecha DESC
        LIMIT 50
    """)


@router.get("/almacen/raciones")
def get_raciones(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT r.id, r.id_chiquero, c.nombre AS corral, c.zona,
               r.producto, r.cantidad, r.unidad, r.ultima_actualizacion
        FROM raciones r
        JOIN chiqueros c ON c.id = r.id_chiquero
        ORDER BY c.zona, c.nombre
    """)


@router.post("/almacen/raciones")
def guardar_racion(data: RacionRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO raciones
           (id_chiquero, producto, cantidad, unidad, ultima_actualizacion)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE cantidad=%s, unidad=%s, ultima_actualizacion=%s""",
        (
            data.id_chiquero,
            data.producto,
            data.cantidad,
            data.unidad,
            hora_mexico(),
            data.cantidad,
            data.unidad,
            hora_mexico(),
        )
    )

    return {"ok": True}


@router.post("/almacen/salida-alimento")
def registrar_salida_alimento(
    data: SalidaAlimentoRequest,
    usuario=Depends(verificar_token)
):
    execute(
        """INSERT INTO almacen
           (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
           VALUES ('salida', 'Alimento', %s, %s, %s, NULL, %s, %s, %s)""",
        (
            data.producto,
            data.cantidad,
            data.unidad,
            f"Alimentación {data.turno} — corral {data.id_chiquero}",
            usuario["nombre"],
            hora_mexico(),
        )
    )

    return {"ok": True}


@router.get("/almacen/alimento-hoy")
def get_alimento_hoy(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    return fetch_all("""
        SELECT notas, COUNT(*) as turnos
        FROM almacen
        WHERE tipo = 'salida'
        AND categoria = 'Alimento'
        AND DATE(fecha) = %s
        GROUP BY notas
    """, (hoy,))


@router.get("/almacen/gastos")
def get_gastos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo = 'entrada'
        AND (
            producto IN (
                'Gasolina camioneta',
                'Gasolina bomba',
                'Medicamento/Vacuna',
                'Material construcción'
            )
            OR producto LIKE 'Otro:%'
        )
        ORDER BY fecha DESC
        LIMIT 100
    """)


@router.get("/almacen/historial-alimento")
def get_historial_alimento(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT DATE(a.fecha) AS dia, a.notas, a.producto,
               SUM(a.cantidad) AS total_cantidad, a.unidad,
               MAX(a.fecha) AS ultima_fecha,
               c.nombre AS corral_nombre
        FROM almacen a
        LEFT JOIN chiqueros c ON c.id = CAST(
            SUBSTRING_INDEX(a.notas, 'corral ', -1) AS UNSIGNED
        )
        WHERE a.tipo = 'salida'
        AND a.categoria = 'Alimento'
        AND a.fecha >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY DATE(a.fecha), a.notas, a.producto, a.unidad, c.nombre
        ORDER BY DATE(a.fecha) DESC
    """)