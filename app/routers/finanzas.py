from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from app.core.telegram import enviar_telegram

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.time import hora_mexico
from app.schemas.finanzas import (
    DepositoRequest,
    NominaRequest,
    SueldoConfig,
)

router = APIRouter(tags=["Finanzas"])


@router.get("/finanzas/resumen")
def get_resumen_finanzas(usuario=Depends(verificar_token)):
    dep = fetch_one(
    "SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito' AND estado='confirmado'"
    )
    sue = fetch_one(
        "SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo'"
    )
    ven = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas")
    alm = fetch_one(
        "SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL"
    )

    total_dep = float(dep["t"])
    total_sue = float(sue["t"])
    total_ven = float(ven["t"])
    total_alm = float(alm["t"])

    return {
        "depositos": total_dep,
        "ventas": total_ven,
        "sueldos": total_sue,
        "almacen": total_alm,
        "saldo": total_dep + total_ven - total_sue - total_alm,
        "utilidad": total_ven - total_alm - total_sue,
    }


@router.get("/finanzas/depositos")
def get_depositos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, fecha, monto, notas, usuario_id, entrego, metodo, estado
        FROM finanzas
        WHERE tipo='deposito'
        AND estado='confirmado'
        ORDER BY fecha DESC
        LIMIT 10
    """)

@router.get("/finanzas/depositos/pendientes")
def get_depositos_pendientes(usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        return []

    return fetch_all("""
        SELECT id, fecha, monto, notas, usuario_id, entrego, metodo, estado
        FROM finanzas
        WHERE tipo='deposito'
        AND estado='pendiente'
        ORDER BY fecha DESC
    """)


@router.post("/finanzas/depositos/{deposito_id}/confirmar")
def confirmar_deposito(deposito_id: int, usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        return {"ok": False, "mensaje": "No autorizado"}

    execute(
        """UPDATE finanzas
           SET estado='confirmado',
               confirmado_por=%s,
               fecha_confirmacion=%s
           WHERE id=%s
           AND tipo='deposito'
           AND estado='pendiente'""",
        (
            usuario["nombre"],
            hora_mexico(),
            deposito_id,
        ),
    )

    return {"ok": True}

@router.post("/finanzas/depositos/{deposito_id}/rechazar")
def rechazar_deposito(deposito_id: int, usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        return {"ok": False, "mensaje": "No autorizado"}

    execute(
        """UPDATE finanzas
           SET estado='rechazado',
               confirmado_por=%s,
               fecha_confirmacion=%s
           WHERE id=%s
           AND tipo='deposito'
           AND estado='pendiente'""",
        (
            usuario["nombre"],
            hora_mexico(),
            deposito_id,
        ),
    )

    return {"ok": True}

@router.get("/finanzas/nomina")
def get_nomina(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    dias_desde_domingo = (hoy.weekday() + 1) % 7
    if dias_desde_domingo == 0:
        dias_desde_domingo = 7

    domingo_inicio = hoy - timedelta(days=dias_desde_domingo)
    domingo_fin = domingo_inicio + timedelta(days=6)

    return fetch_all(
        """
        SELECT u.id, u.nombre, u.sueldo_diario,
               COUNT(DISTINCT DATE(a.fecha_entrada)) AS dias_trabajados
        FROM usuarios u
        LEFT JOIN asistencia a ON a.usuario_id = u.id
            AND DATE(a.fecha_entrada) BETWEEN %s AND %s
        WHERE u.activo = 1
        AND u.rol != 'admin'
        GROUP BY u.id
        ORDER BY u.nombre
    """,
        (domingo_inicio, domingo_fin),
    )


@router.post("/finanzas/deposito")
def registrar_deposito(data: DepositoRequest, usuario=Depends(verificar_token)):
    es_admin = usuario["rol"] == "admin"

    estado = "confirmado" if es_admin else "pendiente"
    confirmado_por = usuario["nombre"] if es_admin else None
    fecha_confirmacion = hora_mexico() if es_admin else None

    concepto = "Depósito papá" if es_admin else "Dinero recibido pendiente"

    execute(
        """INSERT INTO finanzas
           (tipo, concepto, monto, notas, usuario_id, fecha,
            estado, entrego, metodo, confirmado_por, fecha_confirmacion)
           VALUES ('deposito', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            concepto,
            data.monto,
            data.notas,
            usuario["nombre"],
            hora_mexico(),
            estado,
            data.entrego,
            data.metodo,
            confirmado_por,
            fecha_confirmacion,
        ),
    )

    if estado == "pendiente":
        enviar_telegram(
        f"⏳ DINERO RECIBIDO PENDIENTE\n"
        f"👤 Registrado por: {usuario['nombre']}\n"
        f"💵 Monto: ${data.monto:,.2f}\n"
        f"🙋 Entregado por: {data.entrego or 'No especificado'}\n"
        f"💳 Método: {data.metodo or 'No especificado'}\n"
        f"📝 Notas: {data.notas or 'Sin notas'}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"✅ Entra a Corralia → Depósitos para confirmar o rechazar."
    )
    

    return {
        "ok": True,
        "estado": estado,
        "mensaje": (
            "Depósito registrado y confirmado"
            if es_admin
            else "Dinero recibido registrado, pendiente de confirmación"
        ),
    }


@router.post("/finanzas/nomina")
def registrar_nomina(data: NominaRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()

    for item in data.items:
        if item.monto > 0:
            execute(
                """INSERT INTO finanzas (tipo, concepto, monto, notas, usuario_id, fecha)
                   VALUES ('sueldo', %s, %s, %s, %s, %s)""",
                (
                    f"Sueldo {item.nombre}",
                    item.monto,
                    f"{item.dias} días — semana {data.semana}",
                    usuario["nombre"],
                    fecha,
                ),
            )

    return {"ok": True}


@router.get("/finanzas/sueldos")
def get_sueldos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, rol, sueldo_diario
        FROM usuarios
        WHERE activo = 1
        AND rol != 'admin'
        ORDER BY nombre
    """)


@router.post("/finanzas/sueldos")
def actualizar_sueldo(data: SueldoConfig, usuario=Depends(verificar_token)):
    execute(
        "UPDATE usuarios SET sueldo_diario = %s WHERE id = %s",
        (data.sueldo_diario, data.usuario_id),
    )

    return {"ok": True}


@router.get("/finanzas/semana")
def get_resumen_semana(fecha: str = None, usuario=Depends(verificar_token)):
    if fecha:
        dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    else:
        dia = hora_mexico().date()

    dias_desde_domingo = (dia.weekday() + 1) % 7
    if dias_desde_domingo == 0:
        dias_desde_domingo = 7

    domingo_inicio = dia - timedelta(days=dias_desde_domingo)
    domingo_fin = domingo_inicio + timedelta(days=6)

    lunes = domingo_inicio
    domingo = domingo_fin

    dep_ant = fetch_one(
    "SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito' AND estado='confirmado' AND DATE(fecha) < %s",
    (domingo_inicio,),
)

    ven_ant = fetch_one(
        "SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas WHERE DATE(fecha) < %s",
        (domingo_inicio,),
    )

    nom_ant = fetch_one(
        "SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo' AND DATE(fecha) < %s",
        (domingo_inicio,),
    )

    gas_ant = fetch_one(
        "SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL AND DATE(fecha) < %s",
        (domingo_inicio,),
    )

    sobrante_anterior = (
        float(dep_ant["t"])
        + float(ven_ant["t"])
        - float(nom_ant["t"])
        - float(gas_ant["t"])
    )

    sobrante_anterior = max(sobrante_anterior, 0)

    depositos = fetch_all(
    """
    SELECT monto, notas, fecha, usuario_id, entrego, metodo
    FROM finanzas
    WHERE tipo='deposito'
    AND estado='confirmado'
    AND DATE(fecha) BETWEEN %s AND %s
    ORDER BY fecha DESC
""",
    (lunes, domingo),
)

    ventas = fetch_all(
        """
        SELECT v.total_rancho, v.tipo_animal, v.cantidad, v.fecha,
               c.nombre AS cliente
        FROM ventas v
        JOIN clientes c ON c.id = v.cliente_id
        WHERE DATE(v.fecha) BETWEEN %s AND %s
        ORDER BY v.fecha DESC
    """,
        (lunes, domingo),
    )

    nomina = fetch_all(
        """
        SELECT concepto, monto, notas, fecha
        FROM finanzas
        WHERE tipo='sueldo'
        AND DATE(fecha) BETWEEN %s AND %s
        ORDER BY fecha DESC
    """,
        (lunes, domingo),
    )

    alimento = fetch_one(
        """
        SELECT IFNULL(SUM(cantidad), 0) AS total_kg,
               COUNT(*) AS num_registros
        FROM almacen
        WHERE tipo='salida'
        AND categoria='Alimento'
        AND DATE(fecha) BETWEEN %s AND %s
    """,
        (lunes, domingo),
    )

    gastos_otros = fetch_all(
        """
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo='entrada'
        AND DATE(fecha) BETWEEN %s AND %s
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
    """,
        (lunes, domingo),
    )

    compras_alimento = fetch_all(
        """
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo='entrada'
        AND DATE(fecha) BETWEEN %s AND %s
        AND categoria IN ('Ingredientes revoltura', 'Pellet', 'Descuento')
        ORDER BY fecha DESC
    """,
        (lunes, domingo),
    )

    total_depositos = sum(float(d["monto"]) for d in depositos)
    total_ventas = sum(float(v["total_rancho"]) for v in ventas)
    total_nomina = sum(float(n["monto"]) for n in nomina)
    total_gastos_otros = sum(float(g["costo"] or 0) for g in gastos_otros)
    total_compras = sum(float(c["costo"] or 0) for c in compras_alimento)

    return {
        "semana": {
            "inicio": str(lunes),
            "fin": str(domingo),
        },
        "ingresos": {
            "depositos": depositos,
            "ventas": ventas,
            "sobrante_anterior": sobrante_anterior,
            "total_depositos": total_depositos,
            "total_ventas": total_ventas,
            "total": total_depositos + total_ventas + sobrante_anterior,
        },
        "gastos": {
            "nomina": nomina,
            "alimento_kg": float(alimento["total_kg"]),
            "compras_alimento": compras_alimento,
            "otros": gastos_otros,
            "total_nomina": total_nomina,
            "total_compras": total_compras,
            "total_otros": total_gastos_otros,
            "total": total_nomina + total_compras + total_gastos_otros,
        },
        "resumen": {
            "saldo_semana": (
                total_depositos
                + total_ventas
                + sobrante_anterior
                - total_nomina
                - total_compras
                - total_gastos_otros
            )
        },
    }
