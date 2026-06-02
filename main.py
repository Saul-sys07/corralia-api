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
from app.routers import auth, mapa, movimientos, clientes, ventas, almacen, finanzas, checador, vacunas, usuarios


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

# ── Configuracion ─────────────────────────────────────────────────────────────
@app.get("/configuracion/precio")
def get_precio(usuario=Depends(verificar_token)):
    row = fetch_one("SELECT valor FROM configuracion WHERE clave = 'precio_kg'")
    return {"precio": float(row["valor"]) if row else 48.00}

@app.post("/configuracion/precio")
def actualizar_precio(precio: float, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO configuracion (clave, valor) VALUES ('precio_kg', %s)
           ON DUPLICATE KEY UPDATE valor = %s""",
        (str(precio), str(precio))
    )
    return {"ok": True}

@app.get("/configuracion/corrales")
def get_corrales(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, tipo, zona, capacidad_max,
               IFNULL(area_m2, largo * ancho) AS area_m2
        FROM chiqueros ORDER BY zona, nombre
    """)

@app.get("/configuracion/pie-de-cria")
def get_pie_de_cria(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT l.id, l.id_chiquero, l.estado_pie_cria, l.fecha_monta,
               l.fecha_parto_estimada, l.poblacion_actual, c.nombre AS corral
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.tipo_animal = 'Pie de Cría' AND l.poblacion_actual > 0
        ORDER BY c.nombre
    """)

class PieCriaUpdate(BaseModel):
    lote_id: int
    estado: str
    fecha_monta: str | None = None

@app.post("/configuracion/pie-de-cria")
def actualizar_pie_de_cria(data: PieCriaUpdate, usuario=Depends(verificar_token)):
    from datetime import timedelta
    fecha_parto = None
    fecha_monta = None
    if data.fecha_monta:
        fecha_monta = datetime.strptime(data.fecha_monta, "%Y-%m-%d").date()
        fecha_parto = fecha_monta + timedelta(days=114)
    execute(
        """UPDATE lotes SET estado_pie_cria = %s,
           fecha_monta = %s, fecha_parto_estimada = %s
           WHERE id = %s""",
        (data.estado, fecha_monta, fecha_parto, data.lote_id)
    )
    enviar_telegram(
        f"🐷 MONTA REGISTRADA\n"
        f"👤 {usuario['nombre']}\n"
        f"📅 Fecha monta: {data.fecha_monta}\n"
        f"📅 Parto estimado: {fecha_parto}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    ) if data.fecha_monta else None
    return {"ok": True}

class AnimalRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    cantidad: int

@app.post("/configuracion/registrar-animales")
def registrar_animales(data: AnimalRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (data.id_chiquero, data.tipo_animal, data.cantidad)
    )
    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'ENTRADA', %s, %s, %s)""",
        (data.id_chiquero, data.tipo_animal, data.cantidad,
         usuario["nombre"], f"Registro inicial: {data.cantidad} {data.tipo_animal}", hora_mexico())
    )
    return {"ok": True}

class CorralRequest(BaseModel):
    nombre: str
    tipo: str
    zona: str
    largo: float | None = None
    ancho: float | None = None
    capacidad_max: int

@app.post("/configuracion/corrales")
def crear_corral(data: CorralRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO chiqueros (nombre, tipo, zona, largo, ancho, capacidad_max)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (data.nombre, data.tipo, data.zona, data.largo, data.ancho, data.capacidad_max)
    )
    return {"ok": True}

class CorralEditRequest(BaseModel):
    nombre: str
    tipo: str
    zona: str
    capacidad_max: int
    largo: float | None = None
    ancho: float | None = None

@app.put("/configuracion/corrales/{corral_id}")
def editar_corral(corral_id: int, data: CorralEditRequest, usuario=Depends(verificar_token)):
    execute(
        """UPDATE chiqueros SET nombre=%s, tipo=%s, zona=%s,
           capacidad_max=%s, largo=%s, ancho=%s
           WHERE id=%s""",
        (data.nombre, data.tipo, data.zona, data.capacidad_max,
         data.largo, data.ancho, corral_id)
    )
    return {"ok": True}

class NuclearRequest(BaseModel):
    confirmacion: str

@app.post("/configuracion/nuclear")
def reset_nuclear(data: NuclearRequest, usuario=Depends(verificar_token)):
    if data.confirmacion != "BORRAR TODO":
        raise HTTPException(status_code=400, detail="Confirmación incorrecta")
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo el admin puede hacer esto")
    execute("DELETE FROM asistencia")
    execute("DELETE FROM historial_movimientos")
    execute("DELETE FROM vacunaciones")
    execute("DELETE FROM ventas")
    execute("DELETE FROM finanzas")
    execute("DELETE FROM almacen")
    execute("DELETE FROM clientes")
    execute("DELETE FROM notificaciones")
    execute("""UPDATE lotes SET poblacion_actual = 0,
               estado_pie_cria = NULL, fecha_monta = NULL,
               fecha_parto_estimada = NULL""")
    execute("""UPDATE usuarios SET primer_acceso = 1, pin = pin_temporal
               WHERE rol != 'admin' AND pin_temporal IS NOT NULL""")
    return {"ok": True, "mensaje": "Sistema limpiado — listo para datos reales"}

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

# ── Notificaciones ─────────────────────────────────────────────────────────────
@app.get("/notificaciones")
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
        fecha_monta = lote['fecha_monta']
        if not fecha_monta:
            continue
        if isinstance(fecha_monta, str):
            fecha_monta = datetime.strptime(fecha_monta, "%Y-%m-%d").date()
        elif hasattr(fecha_monta, 'date'):
            fecha_monta = fecha_monta.date()

        dia_21 = fecha_monta + timedelta(days=21)
        dia_107 = fecha_monta + timedelta(days=107)

        for fecha_prog, tipo, mensaje in [
            (dia_21, 'verificar_preñez', f"🔍 Verificar preñez — {lote['corral']} (día 21 de monta)"),
            (dia_107, 'alerta_parto', f"⚠️ Parto próximo — {lote['corral']} (faltan 7 días)")
        ]:
            existente = fetch_one("""
                SELECT id FROM notificaciones
                WHERE id_lote = %s AND tipo = %s
            """, (lote['id'], tipo))
            if not existente and hoy >= fecha_prog:
                execute("""
                    INSERT INTO notificaciones
                    (tipo, mensaje, id_lote, roles_destino, fecha_creacion, fecha_programada)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (tipo, mensaje, lote['id'], 'admin,encargado_general,gestacion',
                      hora_mexico(), fecha_prog))

    notifs = fetch_all("""
        SELECT * FROM notificaciones
        WHERE roles_destino LIKE %s
        AND (visto_por NOT LIKE %s OR visto_por = '')
        AND fecha_programada <= %s
        ORDER BY fecha_creacion DESC
        LIMIT 20
    """, (f"%{usuario['rol']}%", f"%{usuario['nombre']}%", hoy))
    return notifs

@app.post("/notificaciones/{notif_id}/vista")
def marcar_vista(notif_id: int, usuario=Depends(verificar_token)):
    notif = fetch_one("SELECT visto_por FROM notificaciones WHERE id = %s", (notif_id,))
    if notif:
        visto_por = notif['visto_por'] or ''
        if usuario['nombre'] not in visto_por:
            nuevo = f"{visto_por},{usuario['nombre']}".strip(',')
            execute("UPDATE notificaciones SET visto_por = %s WHERE id = %s", (nuevo, notif_id))
    return {"ok": True}

# ── Monta ─────────────────────────────────────────────────────────────────────
class MonitaRequest(BaseModel):
    lote_id: int
    fecha_monta: str
    foto_base64: str | None = None

@app.post("/monta")
def registrar_monta(data: MonitaRequest, usuario=Depends(verificar_token)):
    from datetime import timedelta
    fecha_monta = datetime.strptime(data.fecha_monta, "%Y-%m-%d").date()
    fecha_parto = fecha_monta + timedelta(days=114)
    
    # Subir foto si viene
    foto_url = None
    if data.foto_base64:
        nombre_foto = f"corralia/montas/{data.lote_id}_{fecha_monta}"
        resultado = cloudinary.uploader.upload(
            f"data:image/jpeg;base64,{data.foto_base64}",
            public_id=nombre_foto,
            overwrite=True
        )
        foto_url = resultado["secure_url"]

    execute("""
        UPDATE lotes SET 
            estado_pie_cria = 'Montada',
            fecha_monta = %s,
            fecha_parto_estimada = %s,
            foto_pie_cria = %s
        WHERE id = %s
    """, (fecha_monta, fecha_parto, foto_url, data.lote_id))

    # Obtener nombre del corral
    lote = fetch_one("""
        SELECT c.nombre AS corral FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.id = %s
    """, (data.lote_id,))

    enviar_telegram(
        f"🐷 MONTA REGISTRADA\n"
        f"👤 {usuario['nombre']}\n"
        f"📍 {lote['corral']}\n"
        f"📅 Fecha monta: {fecha_monta}\n"
        f"📅 Parto estimado: {fecha_parto}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )
    return {"ok": True, "fecha_parto": str(fecha_parto)}

class VerificarPreñezRequest(BaseModel):
    lote_id: int
    confirma_preñez: bool

@app.post("/monta/verificar")
def verificar_preñez(data: VerificarPreñezRequest, usuario=Depends(verificar_token)):
    lote = fetch_one("""
        SELECT l.*, c.nombre AS corral FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.id = %s
    """, (data.lote_id,))

    if data.confirma_preñez:
        execute("UPDATE lotes SET estado_pie_cria = 'Gestante' WHERE id = %s", (data.lote_id,))
        enviar_telegram(
            f"✅ PREÑEZ CONFIRMADA\n"
            f"👤 {usuario['nombre']}\n"
            f"📍 {lote['corral']}\n"
            f"📅 Parto estimado: {lote['fecha_parto_estimada']}\n"
            f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
        )
    else:
        execute("""
            UPDATE lotes SET 
                estado_pie_cria = 'Disponible',
                fecha_monta = NULL,
                fecha_parto_estimada = NULL
            WHERE id = %s
        """, (data.lote_id,))
        enviar_telegram(
            f"❌ REGRESÓ A CALOR\n"
            f"👤 {usuario['nombre']}\n"
            f"📍 {lote['corral']}\n"
            f"🐷 Vuelve a estado Disponible\n"
            f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
        )
    return {"ok": True}

# ── Apartados ─────────────────────────────────────────────────────────────────
class ApartadoRequest(BaseModel):
    cliente_id: int
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    anticipo: float
    fecha_compromiso: str
    notas: str = ''

@app.post("/apartados")
def crear_apartado(data: ApartadoRequest, usuario=Depends(verificar_token)):
    execute("""
        INSERT INTO apartados
        (cliente_id, id_chiquero, tipo_animal, cantidad, anticipo, fecha_apartado, fecha_compromiso, estado, usuario_id, notas)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'activo', %s, %s)
    """, (data.cliente_id, data.id_chiquero, data.tipo_animal, data.cantidad,
          data.anticipo, hora_mexico(), data.fecha_compromiso, usuario["nombre"], data.notas))
    
    lote = fetch_one("""
        SELECT c.nombre AS corral FROM chiqueros c WHERE c.id = %s
    """, (data.id_chiquero,))
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

@app.get("/apartados")
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

@app.post("/apartados/{apartado_id}/cancelar")
def cancelar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute("UPDATE apartados SET estado = 'cancelado' WHERE id = %s", (apartado_id,))
    return {"ok": True}

@app.post("/apartados/{apartado_id}/liquidar")
def liquidar_apartado(apartado_id: int, usuario=Depends(verificar_token)):
    execute("UPDATE apartados SET estado = 'liquidado' WHERE id = %s", (apartado_id,))
    return {"ok": True}