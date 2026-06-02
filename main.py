from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import math
import cloudinary
import cloudinary.uploader

from database import fetch_one, fetch_all, execute

from app.core.config import (
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CORS_ORIGINS,
    RANCHO_LAT,
    RANCHO_LNG,
    RADIO_METROS,
)

from app.core.time import hora_mexico
from app.core.telegram import enviar_telegram
from app.core.security import crear_token, verificar_token
from app.routers import auth, mapa, movimientos, clientes, ventas, almacen, finanzas, checador, vacunas, usuarios, configuracion, notificaciones, monta, apartados


cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

app = FastAPI(title="Corralia API v4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(mapa.router)
app.include_router(movimientos.router)
app.include_router(clientes.router)
app.include_router(ventas.router)
app.include_router(almacen.router)
app.include_router(finanzas.router)
app.include_router(checador.router)
app.include_router(vacunas.router)
app.include_router(usuarios.router)
app.include_router(configuracion.router)
app.include_router(notificaciones.router)
app.include_router(monta.router)
app.include_router(apartados.router)

@app.get("/")
def root():
    return {"status": "Corralia API v4 corriendo"}

# ── Reportes ──────────────────────────────────────────────────────────────────
@app.get("/reportes/mensual")
def get_reporte_mensual(mes: int, anio: int, usuario=Depends(verificar_token)):
    inventario = fetch_all("""
        SELECT l.tipo_animal, SUM(l.poblacion_actual) AS total
        FROM lotes l WHERE l.poblacion_actual > 0
        GROUP BY l.tipo_animal ORDER BY l.tipo_animal
    """)
    movimientos = fetch_all("""
        SELECT tipo_evento, SUM(cantidad) AS total
        FROM historial_movimientos
        WHERE MONTH(fecha) = %s AND YEAR(fecha) = %s
        GROUP BY tipo_evento
    """, (mes, anio))
    dep = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito' AND MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes, anio))
    ven = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas WHERE MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes, anio))
    alm = fetch_one("SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL AND MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes, anio))
    sue = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo' AND MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes, anio))
    mes_ant = mes - 1 if mes > 1 else 12
    anio_ant = anio if mes > 1 else anio - 1
    ven_ant = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas WHERE MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes_ant, anio_ant))
    alm_ant = fetch_one("SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL AND MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes_ant, anio_ant))
    muertes_ant = fetch_one("SELECT IFNULL(SUM(cantidad),0) AS t FROM historial_movimientos WHERE tipo_evento='MUERTE' AND MONTH(fecha)=%s AND YEAR(fecha)=%s", (mes_ant, anio_ant))
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
            "saldo": total_dep + total_ven - total_alm - total_sue
        },
        "anterior": {
            "ventas": float(ven_ant["t"]),
            "almacen": float(alm_ant["t"]),
            "muertes": int(muertes_ant["t"])
        }
    }

@app.get("/reportes/ica")
def get_ica(fecha_inicio: str = None, fecha_fin: str = None, usuario=Depends(verificar_token)):
    from datetime import timedelta
    hoy = hora_mexico().date()
    fi = datetime.strptime(fecha_inicio, "%Y-%m-%d").date() if fecha_inicio else hoy - timedelta(days=30)
    ff = datetime.strptime(fecha_fin, "%Y-%m-%d").date() if fecha_fin else hoy

    alimento = fetch_all("""
        SELECT c.nombre AS corral, c.zona, SUM(a.cantidad) AS kg_alimento
        FROM almacen a
        LEFT JOIN chiqueros c ON c.id = CAST(
            SUBSTRING_INDEX(a.notas, 'corral ', -1) AS UNSIGNED
        )
        WHERE a.tipo = 'salida' AND a.categoria = 'Alimento'
        AND DATE(a.fecha) BETWEEN %s AND %s
        AND c.zona = 'Crecimiento'
        AND c.nombre IS NOT NULL
        GROUP BY c.nombre, c.zona
    """, (fi, ff))

    ventas = fetch_all("""
        SELECT c.nombre AS corral, SUM(v.peso_kg) AS kg_vendidos, COUNT(v.id) AS num_ventas
        FROM ventas v
        JOIN historial_movimientos h ON h.tipo_evento = 'VENTA' AND h.id_chiquero_destino = v.id
        JOIN chiqueros c ON c.id = h.id_chiquero_destino
        WHERE DATE(v.fecha) BETWEEN %s AND %s
        AND c.zona = 'Crecimiento'
        GROUP BY c.nombre
    """, (fi, ff))

    ventas_dict = {v['corral']: {'kg': float(v['kg_vendidos']), 'num': int(v['num_ventas'])} for v in ventas}

    resultado = []
    for a in alimento:
        corral = a['corral']
        kg_alimento = float(a['kg_alimento'])
        venta = ventas_dict.get(corral, {'kg': 0, 'num': 0})
        kg_vendidos = venta['kg']
        ica = round(kg_alimento / kg_vendidos, 2) if kg_vendidos > 0 else None
        resultado.append({
            'corral': corral,
            'zona': a['zona'],
            'kg_alimento': kg_alimento,
            'kg_vendidos': kg_vendidos,
            'num_ventas': venta['num'],
            'ica': ica,
            'fecha_inicio': str(fi),
            'fecha_fin': str(ff)
        })
    return resultado
