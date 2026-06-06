from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from database import fetch_one, fetch_all
from app.core.security import verificar_token
from app.core.time import hora_mexico

router = APIRouter(tags=["Reportes"])


@router.get("/reportes/mensual")
def get_reporte_mensual(mes: int, anio: int, usuario=Depends(verificar_token)):
    inventario = fetch_all("""
        SELECT l.tipo_animal, SUM(l.poblacion_actual) AS total
        FROM lotes l
        WHERE l.poblacion_actual > 0
        GROUP BY l.tipo_animal
        ORDER BY l.tipo_animal
    """)

    movimientos = fetch_all(
        """
        SELECT tipo_evento, SUM(cantidad) AS total
        FROM historial_movimientos
        WHERE MONTH(fecha) = %s
        AND YEAR(fecha) = %s
        GROUP BY tipo_evento
    """,
        (mes, anio),
    )

    dep = fetch_one(
        """
        SELECT IFNULL(SUM(monto),0) AS t
        FROM finanzas
        WHERE tipo='deposito'
        AND MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes, anio),
    )

    ven = fetch_one(
        """
        SELECT IFNULL(SUM(total_rancho),0) AS t
        FROM ventas
        WHERE MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes, anio),
    )

    alm = fetch_one(
        """
        SELECT IFNULL(SUM(costo),0) AS t
        FROM almacen
        WHERE tipo='entrada'
        AND costo IS NOT NULL
        AND MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes, anio),
    )

    sue = fetch_one(
        """
        SELECT IFNULL(SUM(monto),0) AS t
        FROM finanzas
        WHERE tipo='sueldo'
        AND MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes, anio),
    )

    mes_ant = mes - 1 if mes > 1 else 12
    anio_ant = anio if mes > 1 else anio - 1

    ven_ant = fetch_one(
        """
        SELECT IFNULL(SUM(total_rancho),0) AS t
        FROM ventas
        WHERE MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes_ant, anio_ant),
    )

    alm_ant = fetch_one(
        """
        SELECT IFNULL(SUM(costo),0) AS t
        FROM almacen
        WHERE tipo='entrada'
        AND costo IS NOT NULL
        AND MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes_ant, anio_ant),
    )

    muertes_ant = fetch_one(
        """
        SELECT IFNULL(SUM(cantidad),0) AS t
        FROM historial_movimientos
        WHERE tipo_evento='MUERTE'
        AND MONTH(fecha)=%s
        AND YEAR(fecha)=%s
    """,
        (mes_ant, anio_ant),
    )

    total_ven = float(ven["t"])
    total_alm = float(alm["t"])
    total_sue = float(sue["t"])
    total_dep = float(dep["t"])

    return {
        "inventario": inventario,
        "movimientos": {m["tipo_evento"]: int(m["total"]) for m in movimientos},
        "finanzas": {
            "depositos": total_dep,
            "ventas": total_ven,
            "almacen": total_alm,
            "sueldos": total_sue,
            "utilidad": total_ven - total_alm - total_sue,
            "saldo": total_dep + total_ven - total_alm - total_sue,
        },
        "anterior": {
            "ventas": float(ven_ant["t"]),
            "almacen": float(alm_ant["t"]),
            "muertes": int(muertes_ant["t"]),
        },
    }


@router.get("/reportes/ica")
def get_ica(
    fecha_inicio: str = None, fecha_fin: str = None, usuario=Depends(verificar_token)
):
    hoy = hora_mexico().date()

    fi = (
        datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        if fecha_inicio
        else hoy - timedelta(days=30)
    )

    ff = datetime.strptime(fecha_fin, "%Y-%m-%d").date() if fecha_fin else hoy

    alimento = fetch_all(
        """
        SELECT c.nombre AS corral, c.zona, SUM(a.cantidad) AS kg_alimento
        FROM almacen a
        LEFT JOIN chiqueros c ON c.id = CAST(
            SUBSTRING_INDEX(a.notas, 'corral ', -1) AS UNSIGNED
        )
        WHERE a.tipo = 'salida'
        AND a.categoria = 'Alimento'
        AND DATE(a.fecha) BETWEEN %s AND %s
        AND c.zona = 'Crecimiento'
        AND c.nombre IS NOT NULL
        GROUP BY c.nombre, c.zona
    """,
        (fi, ff),
    )

    ventas = fetch_all(
        """
        SELECT c.nombre AS corral,
               SUM(v.peso_kg) AS kg_vendidos,
               COUNT(v.id) AS num_ventas
        FROM ventas v
        JOIN historial_movimientos h
            ON h.tipo_evento = 'VENTA'
            AND h.id_chiquero_destino = v.id
        JOIN chiqueros c ON c.id = h.id_chiquero_destino
        WHERE DATE(v.fecha) BETWEEN %s AND %s
        AND c.zona = 'Crecimiento'
        GROUP BY c.nombre
    """,
        (fi, ff),
    )

    ventas_dict = {
        v["corral"]: {"kg": float(v["kg_vendidos"]), "num": int(v["num_ventas"])}
        for v in ventas
    }

    resultado = []

    for a in alimento:
        corral = a["corral"]
        kg_alimento = float(a["kg_alimento"])

        venta = ventas_dict.get(corral, {"kg": 0, "num": 0})
        kg_vendidos = venta["kg"]

        ica = round(kg_alimento / kg_vendidos, 2) if kg_vendidos > 0 else None

        resultado.append(
            {
                "corral": corral,
                "zona": a["zona"],
                "kg_alimento": kg_alimento,
                "kg_vendidos": kg_vendidos,
                "num_ventas": venta["num"],
                "ica": ica,
                "fecha_inicio": str(fi),
                "fecha_fin": str(ff),
            }
        )

    return resultado
