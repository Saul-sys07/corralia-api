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
from app.routers import auth, mapa, movimientos, clientes, ventas


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

# ── Mapa ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Corralia API v4 corriendo"}

# ── Almacen ───────────────────────────────────────────────────────────────────
@app.get("/almacen/inventario")
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
        ) AND producto NOT LIKE 'Otro:%'
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

@app.get("/almacen/saldo")
def get_saldo(usuario=Depends(verificar_token)):
    dep = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito'")
    sue = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo'")
    alm = fetch_one("SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL")
    ven = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas")
    saldo = float(dep["t"]) + float(ven["t"]) - float(sue["t"]) - float(alm["t"])
    return {"saldo": saldo}

class CompraItem(BaseModel):
    producto: str
    cantidad: float
    unidad: str
    costo: float
    categoria: str

class CompraRequest(BaseModel):
    items: list[CompraItem]
    descuento: float = 0.0

@app.post("/almacen/compra")
def registrar_compra(data: CompraRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()
    for item in data.items:
        execute(
            """INSERT INTO almacen
               (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
               VALUES ('entrada', %s, %s, %s, %s, %s, %s, %s, %s)""",
            (item.categoria, item.producto, item.cantidad, item.unidad,
             item.costo, f"Compra — descuento: ${data.descuento:.2f}",
             usuario["nombre"], fecha)
        )
    total = sum(i.costo for i in data.items)
    enviar_telegram(
        f"🏚️ COMPRA ALMACÉN\n"
        f"👤 {usuario['nombre']}\n"
        f"📦 {len(data.items)} productos\n"
        f"💵 ${total:,.2f}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
    )
    return {"ok": True}

class RevolturaRequest(BaseModel):
    maiz: float
    salvado: float
    soya: float
    sal: float
    melaza: float

@app.post("/almacen/revoltura")
def hacer_revoltura(data: RevolturaRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()
    kg_revoltura = (data.maiz * 40) + (data.salvado * 25) + (data.soya * 40) + data.sal
    notas = f"Revoltura: {data.maiz:.0f}bt maíz + {data.salvado:.0f}bt salvado + {data.soya:.0f}bt soya + {data.sal:.0f}kg sal + {data.melaza:.0f}L melaza"
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
                (prod, cant, unid, notas, usuario["nombre"], fecha)
            )
    execute(
        """INSERT INTO almacen
           (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
           VALUES ('entrada', 'revoltura', 'Revoltura lista', %s, 'kg', NULL, %s, %s, %s)""",
        (kg_revoltura, notas, usuario["nombre"], fecha)
    )
    return {"ok": True, "kg_revoltura": kg_revoltura}

# ── Finanzas ──────────────────────────────────────────────────────────────────
@app.get("/finanzas/resumen")
def get_resumen_finanzas(usuario=Depends(verificar_token)):
    dep = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='deposito'")
    sue = fetch_one("SELECT IFNULL(SUM(monto),0) AS t FROM finanzas WHERE tipo='sueldo'")
    ven = fetch_one("SELECT IFNULL(SUM(total_rancho),0) AS t FROM ventas")
    alm = fetch_one("SELECT IFNULL(SUM(costo),0) AS t FROM almacen WHERE tipo='entrada' AND costo IS NOT NULL")
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
        "utilidad": total_ven - total_alm - total_sue
    }

@app.get("/finanzas/depositos")
def get_depositos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT fecha, monto, notas FROM finanzas
        WHERE tipo='deposito' ORDER BY fecha DESC LIMIT 10
    """)

@app.get("/finanzas/nomina")
def get_nomina(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    from datetime import timedelta
    dias_desde_domingo = (hoy.weekday() + 1) % 7
    if dias_desde_domingo == 0:
        dias_desde_domingo = 7
    domingo_inicio = hoy - timedelta(days=dias_desde_domingo)
    domingo_fin = domingo_inicio + timedelta(days=6)
    return fetch_all("""
        SELECT u.id, u.nombre, u.sueldo_diario,
               COUNT(DISTINCT DATE(a.fecha_entrada)) AS dias_trabajados
        FROM usuarios u
        LEFT JOIN asistencia a ON a.usuario_id = u.id
            AND DATE(a.fecha_entrada) BETWEEN %s AND %s
        WHERE u.activo = 1 AND u.rol != 'admin'
        GROUP BY u.id ORDER BY u.nombre
    """, (domingo_inicio, domingo_fin))

class DepositoRequest(BaseModel):
    monto: float
    notas: str = ''

@app.post("/finanzas/deposito")
def registrar_deposito(data: DepositoRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO finanzas (tipo, concepto, monto, notas, usuario_id, fecha)
           VALUES ('deposito', 'Depósito papá', %s, %s, %s, %s)""",
        (data.monto, data.notas, usuario["nombre"], hora_mexico())
    )
    return {"ok": True}

class SueldoItem(BaseModel):
    nombre: str
    monto: float
    dias: int

class NominaRequest(BaseModel):
    items: list[SueldoItem]
    semana: str

@app.post("/finanzas/nomina")
def registrar_nomina(data: NominaRequest, usuario=Depends(verificar_token)):
    fecha = hora_mexico()
    for item in data.items:
        if item.monto > 0:
            execute(
                """INSERT INTO finanzas (tipo, concepto, monto, notas, usuario_id, fecha)
                   VALUES ('sueldo', %s, %s, %s, %s, %s)""",
                (f"Sueldo {item.nombre}", item.monto,
                 f"{item.dias} días — semana {data.semana}",
                 usuario["nombre"], fecha)
            )
    return {"ok": True}

@app.get("/finanzas/sueldos")
def get_sueldos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, rol, sueldo_diario FROM usuarios
        WHERE activo = 1 AND rol != 'admin' ORDER BY nombre
    """)

class SueldoConfig(BaseModel):
    usuario_id: int
    sueldo_diario: float

@app.post("/finanzas/sueldos")
def actualizar_sueldo(data: SueldoConfig, usuario=Depends(verificar_token)):
    execute(
        "UPDATE usuarios SET sueldo_diario = %s WHERE id = %s",
        (data.sueldo_diario, data.usuario_id)
    )
    return {"ok": True}

# ── Checador ──────────────────────────────────────────────────────────────────
@app.get("/checador/estado")
def get_estado_checador(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    entrada = fetch_one("""
        SELECT id, fecha_entrada FROM asistencia
        WHERE usuario_id = %s AND DATE(fecha_entrada) = %s
        ORDER BY fecha_entrada DESC LIMIT 1
    """, (usuario["id"], hoy))
    salida = None
    if entrada:
        salida = fetch_one("""
            SELECT fecha_salida FROM asistencia
            WHERE id = %s AND fecha_salida IS NOT NULL
        """, (entrada["id"],))
    return {
        "checo_entrada": entrada is not None,
        "checo_salida": salida is not None,
        "id_asistencia": entrada["id"] if entrada else None
    }

@app.post("/checador/entrada")
def registrar_entrada(usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO asistencia (usuario_id, nombre, fecha_entrada)
           VALUES (%s, %s, %s)""",
        (usuario["id"], usuario["nombre"], hora_mexico())
    )
    return {"ok": True}

@app.post("/checador/salida")
def registrar_salida(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    execute(
        """UPDATE asistencia SET fecha_salida = %s
           WHERE usuario_id = %s AND DATE(fecha_entrada) = %s
           AND fecha_salida IS NULL""",
        (hora_mexico(), usuario["id"], hoy)
    )
    return {"ok": True}

@app.get("/checador/historial")
def get_historial_asistencias(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT a.id, a.usuario_id, a.nombre,
               a.fecha_entrada, a.fecha_salida,
               a.foto_entrada, a.foto_salida
        FROM asistencia a
        ORDER BY a.fecha_entrada DESC
        LIMIT 100
    """)

class FotoChecadorRequest(BaseModel):
    foto_base64: str
    tipo: str

@app.post("/checador/foto")
def subir_foto_checador(data: FotoChecadorRequest, usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    nombre_foto = f"corralia/checador/{usuario['nombre']}_{data.tipo}_{hoy}"
    resultado = cloudinary.uploader.upload(
        f"data:image/jpeg;base64,{data.foto_base64}",
        public_id=nombre_foto,
        overwrite=True
    )
    url = resultado["secure_url"]
    if data.tipo == 'entrada':
        execute(
            """UPDATE asistencia SET foto_entrada = %s
               WHERE usuario_id = %s AND DATE(fecha_entrada) = %s""",
            (url, usuario["id"], hoy)
        )
    else:
        execute(
            """UPDATE asistencia SET foto_salida = %s
               WHERE usuario_id = %s AND DATE(fecha_entrada) = %s""",
            (url, usuario["id"], hoy)
        )
    return {"ok": True, "url": url}

# ── Vacunas ───────────────────────────────────────────────────────────────────
@app.get("/vacunas/historial")
def get_historial_vacunas(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT v.fecha, c.nombre AS corral, v.tipo_animal,
               v.vacuna, v.nombre_comercial, v.cantidad, v.notas, v.usuario_id
        FROM vacunaciones v
        JOIN chiqueros c ON c.id = v.id_chiquero
        ORDER BY v.fecha DESC LIMIT 50
    """)

class VacunaRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    vacuna: str
    nombre_comercial: str = ''
    cantidad: int
    notas: str = ''

@app.post("/vacunas")
def registrar_vacuna(data: VacunaRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO vacunaciones
           (id_chiquero, tipo_animal, vacuna, nombre_comercial, cantidad, notas, usuario_id, fecha)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (data.id_chiquero, data.tipo_animal, data.vacuna,
         data.nombre_comercial or None, data.cantidad,
         data.notas or None, usuario["nombre"], hora_mexico())
    )
    return {"ok": True}

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

# ── Usuarios ──────────────────────────────────────────────────────────────────
@app.get("/usuarios")
def get_usuarios(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, rol, activo, ultimo_acceso
        FROM usuarios ORDER BY nombre
    """)

class UsuarioRequest(BaseModel):
    nombre: str
    rol: str
    pin_temporal: str

@app.post("/usuarios")
def crear_usuario(data: UsuarioRequest, usuario=Depends(verificar_token)):
    existente = fetch_one("SELECT id FROM usuarios WHERE nombre = %s", (data.nombre,))
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese nombre")
    execute(
        """INSERT INTO usuarios (nombre, pin, pin_temporal, rol, primer_acceso)
           VALUES (%s, %s, %s, %s, 1)""",
        (data.nombre, data.pin_temporal, data.pin_temporal, data.rol)
    )
    return {"ok": True}

@app.post("/usuarios/toggle")
def toggle_usuario(usuario_id: int, usuario=Depends(verificar_token)):
    execute(
        "UPDATE usuarios SET activo = NOT activo WHERE id = %s",
        (usuario_id,)
    )
    return {"ok": True}

class ActivarRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str

@app.post("/usuarios/activar")
def activar_usuario(data: ActivarRequest):
    existente = fetch_one(
        "SELECT id FROM usuarios WHERE pin = %s AND id != %s",
        (data.nuevo_pin, data.usuario_id)
    )
    if existente:
        raise HTTPException(status_code=400, detail="Ese PIN ya lo usa otra persona")
    execute(
        "UPDATE usuarios SET pin = %s, pin_temporal = NULL, primer_acceso = 0 WHERE id = %s",
        (data.nuevo_pin, data.usuario_id)
    )
    return {"ok": True}

class ResetPinRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str

@app.post("/usuarios/reset-pin")
def reset_pin(data: ResetPinRequest, usuario=Depends(verificar_token)):
    existente = fetch_one(
        "SELECT id FROM usuarios WHERE pin = %s AND id != %s",
        (data.nuevo_pin, data.usuario_id)
    )
    if existente:
        raise HTTPException(status_code=400, detail="Ese PIN ya lo usa otra persona")
    execute(
        "UPDATE usuarios SET pin = %s, pin_temporal = %s, primer_acceso = 1 WHERE id = %s",
        (data.nuevo_pin, data.nuevo_pin, data.usuario_id)
    )
    return {"ok": True}

class FotoTicketRequest(BaseModel):
    foto_base64: str
    compra_notas: str = ''

@app.post("/almacen/foto-ticket")
def subir_foto_ticket(data: FotoTicketRequest, usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    nombre_foto = f"corralia/tickets/{usuario['nombre']}_{hoy}_{hora_mexico().strftime('%H%M%S')}"
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
        (url, usuario["nombre"], hora_mexico())
    )
    return {"ok": True, "url": url}

@app.get("/almacen/tickets")
def get_tickets(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT notas AS url, usuario_id, fecha
        FROM almacen
        WHERE categoria = 'Evidencia' AND producto = 'Foto ticket'
        ORDER BY fecha DESC
        LIMIT 50
    """)

# ── Raciones ──────────────────────────────────────────────────────────────────
@app.get("/almacen/raciones")
def get_raciones(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT r.id, r.id_chiquero, c.nombre AS corral, c.zona,
               r.producto, r.cantidad, r.unidad, r.ultima_actualizacion
        FROM raciones r
        JOIN chiqueros c ON c.id = r.id_chiquero
        ORDER BY c.zona, c.nombre
    """)

class RacionRequest(BaseModel):
    id_chiquero: int
    producto: str
    cantidad: float
    unidad: str

@app.post("/almacen/raciones")
def guardar_racion(data: RacionRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO raciones (id_chiquero, producto, cantidad, unidad, ultima_actualizacion)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE cantidad=%s, unidad=%s, ultima_actualizacion=%s""",
        (data.id_chiquero, data.producto, data.cantidad, data.unidad, hora_mexico(),
         data.cantidad, data.unidad, hora_mexico())
    )
    return {"ok": True}

class SalidaAlimentoRequest(BaseModel):
    id_chiquero: int
    producto: str
    cantidad: float
    unidad: str
    turno: str

@app.post("/almacen/salida-alimento")
def registrar_salida_alimento(data: SalidaAlimentoRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO almacen
           (tipo, categoria, producto, cantidad, unidad, costo, notas, usuario_id, fecha)
           VALUES ('salida', 'Alimento', %s, %s, %s, NULL, %s, %s, %s)""",
        (data.producto, data.cantidad, data.unidad,
         f"Alimentación {data.turno} — corral {data.id_chiquero}",
         usuario["nombre"], hora_mexico())
    )
    return {"ok": True}

@app.get("/almacen/alimento-hoy")
def get_alimento_hoy(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()
    return fetch_all("""
        SELECT notas, COUNT(*) as turnos
        FROM almacen
        WHERE tipo = 'salida' AND categoria = 'Alimento'
        AND DATE(fecha) = %s
        GROUP BY notas
    """, (hoy,))

@app.get("/almacen/gastos")
def get_gastos(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo = 'entrada' AND (
            producto IN ('Gasolina camioneta', 'Gasolina bomba', 'Medicamento/Vacuna', 'Material construcción')
            OR producto LIKE 'Otro:%'
        )
        ORDER BY fecha DESC
        LIMIT 100
    """)

@app.get("/almacen/historial-alimento")
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
        WHERE a.tipo = 'salida' AND a.categoria = 'Alimento'
        AND a.fecha >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY DATE(a.fecha), a.notas, a.producto, a.unidad, c.nombre
        ORDER BY DATE(a.fecha) DESC
    """)

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

# ── Resumen Semanal ───────────────────────────────────────────────────────────
@app.get("/finanzas/semana")
def get_resumen_semana(fecha: str = None, usuario=Depends(verificar_token)):
    from datetime import timedelta
    if fecha:
        dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    else:
        dia = hora_mexico().date()
    
    # Calcular lunes y domingo de la semana
    dias_desde_domingo = (dia.weekday() + 1) % 7
    if dias_desde_domingo == 0:
        dias_desde_domingo = 7
    domingo_inicio = dia - timedelta(days=dias_desde_domingo)






    
    domingo_fin = domingo_inicio + timedelta(days=6)
    lunes = domingo_inicio
    domingo = domingo_fin

    # Ingresos
    depositos = fetch_all("""
        SELECT monto, notas, fecha FROM finanzas 
        WHERE tipo='deposito' AND DATE(fecha) BETWEEN %s AND %s
        ORDER BY fecha DESC
    """, (lunes, domingo))
    
    ventas = fetch_all("""
        SELECT v.total_rancho, v.tipo_animal, v.cantidad, v.fecha,
               c.nombre AS cliente
        FROM ventas v
        JOIN clientes c ON c.id = v.cliente_id
        WHERE DATE(v.fecha) BETWEEN %s AND %s
        ORDER BY v.fecha DESC
    """, (lunes, domingo))

    # Gastos
    nomina = fetch_all("""
        SELECT concepto, monto, notas, fecha FROM finanzas
        WHERE tipo='sueldo' AND DATE(fecha) BETWEEN %s AND %s
        ORDER BY fecha DESC
    """, (lunes, domingo))

    alimento = fetch_one("""
        SELECT IFNULL(SUM(cantidad), 0) AS total_kg,
               COUNT(*) AS num_registros
        FROM almacen
        WHERE tipo='salida' AND categoria='Alimento'
        AND DATE(fecha) BETWEEN %s AND %s
    """, (lunes, domingo))

    gastos_otros = fetch_all("""
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo='entrada' AND DATE(fecha) BETWEEN %s AND %s
        AND (
            producto IN ('Gasolina camioneta', 'Gasolina bomba', 'Medicamento/Vacuna', 'Material construcción')
            OR producto LIKE 'Otro:%'
        )
        ORDER BY fecha DESC
    """, (lunes, domingo))

    compras_alimento = fetch_all("""
        SELECT producto, cantidad, unidad, costo, notas, usuario_id, fecha
        FROM almacen
        WHERE tipo='entrada' AND DATE(fecha) BETWEEN %s AND %s
        AND categoria IN ('Ingredientes revoltura', 'Pellet')
        ORDER BY fecha DESC
    """, (lunes, domingo))

    # Totales
    total_depositos = sum(float(d['monto']) for d in depositos)
    total_ventas = sum(float(v['total_rancho']) for v in ventas)
    total_nomina = sum(float(n['monto']) for n in nomina)
    total_gastos_otros = sum(float(g['costo'] or 0) for g in gastos_otros)
    total_compras = sum(float(c['costo'] or 0) for c in compras_alimento)

    return {
        "semana": {"inicio": str(lunes), "fin": str(domingo)},
        "ingresos": {
            "depositos": depositos,
            "ventas": ventas,
            "total_depositos": total_depositos,
            "total_ventas": total_ventas,
            "total": total_depositos + total_ventas
        },
        "gastos": {
            "nomina": nomina,
            "alimento_kg": float(alimento['total_kg']),
            "compras_alimento": compras_alimento,
            "otros": gastos_otros,
            "total_nomina": total_nomina,
            "total_compras": total_compras,
            "total_otros": total_gastos_otros,
            "total": total_nomina + total_compras + total_gastos_otros
        },
        "sobrante": (total_depositos + total_ventas) - (total_nomina + total_compras + total_gastos_otros)
    }