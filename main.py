from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import jwt
import os
from dotenv import load_dotenv
from database import fetch_one, fetch_all, execute

load_dotenv()

app = FastAPI(title="Corralia API v4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "https://corralia-react.vercel.app",
    "https://corralia-react-h0e10gno8-saul-sys07s-projects.vercel.app"
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY")
security = HTTPBearer()

def hora_mexico():
    return datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)

def crear_token(usuario: dict) -> str:
    payload = {
        "id": usuario["id"],
        "nombre": usuario["nombre"],
        "rol": usuario["rol"],
        "exp": datetime.utcnow() + timedelta(hours=8)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

# ── Login ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    pin: str

@app.post("/login")
def login(data: LoginRequest):
    usuario = fetch_one(
        "SELECT * FROM usuarios WHERE pin = %s AND activo = 1",
        (data.pin,)
    )
    if not usuario:
        raise HTTPException(status_code=401, detail="PIN incorrecto")
    execute("UPDATE usuarios SET ultimo_acceso = %s WHERE id = %s",
            (hora_mexico(), usuario["id"]))
    return {
        "token": crear_token(usuario),
        "usuario": {
            "id": usuario["id"],
            "nombre": usuario["nombre"],
            "rol": usuario["rol"],
            "primer_acceso": bool(usuario["primer_acceso"])
        }
    }

# ── Mapa ──────────────────────────────────────────────────────────────────────
@app.get("/mapa")
def get_mapa(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.id, c.nombre, c.tipo, c.zona, c.capacidad_max,
               IFNULL(c.area_m2, c.largo * c.ancho) AS area_m2,
               IFNULL(SUM(l.poblacion_actual), 0) AS poblacion_actual,
               IFNULL(GROUP_CONCAT(
                   DISTINCT l.tipo_animal ORDER BY l.tipo_animal SEPARATOR ' / '
               ), 'VACIO') AS tipo_animal,
               MAX(l.fecha_parto_estimada) AS fecha_parto,
               GROUP_CONCAT(
                   DISTINCT l.estado_pie_cria ORDER BY l.estado_pie_cria SEPARATOR ', '
               ) AS estado_pie_cria
        FROM chiqueros c
        LEFT JOIN lotes l ON c.id = l.id_chiquero AND l.poblacion_actual > 0
        GROUP BY c.id
        ORDER BY c.zona, c.nombre
    """)

@app.get("/")
def root():
    return {"status": "Corralia API v4 corriendo"}

# ── Muerte ────────────────────────────────────────────────────────────────────
class MuerteRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    causa: str

@app.post("/muerte")
def registrar_muerte(data: MuerteRequest, usuario=Depends(verificar_token)):
    execute(
        """UPDATE lotes SET poblacion_actual = GREATEST(poblacion_actual - %s, 0)
           WHERE id_chiquero = %s AND tipo_animal = %s""",
        (data.cantidad, data.id_chiquero, data.tipo_animal)
    )
    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'MUERTE', %s, %s, %s)""",
        (data.id_chiquero, data.tipo_animal, data.cantidad,
         usuario["nombre"], f"Causa: {data.causa}", hora_mexico())
    )
    return {"ok": True}

# ── Traslado ──────────────────────────────────────────────────────────────────
class TrasladoRequest(BaseModel):
    id_origen: int
    id_destino: int
    tipo_animal: str
    cantidad: int
    nueva_etapa: str | None = None

@app.post("/traslado")
def registrar_traslado(data: TrasladoRequest, usuario=Depends(verificar_token)):
    tipo_destino = data.nueva_etapa or data.tipo_animal
    execute(
        """UPDATE lotes SET poblacion_actual = GREATEST(poblacion_actual - %s, 0)
           WHERE id_chiquero = %s AND tipo_animal = %s""",
        (data.cantidad, data.id_origen, data.tipo_animal)
    )
    execute(
        """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (data.id_destino, tipo_destino, data.cantidad)
    )
    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_origen, id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, %s, 'TRASPASO', %s, %s, %s)""",
        (data.id_origen, data.id_destino, data.tipo_animal, data.cantidad,
         usuario["nombre"],
         f"Avance de etapa: {data.tipo_animal} → {tipo_destino}" if data.nueva_etapa else f"Traspaso de {data.cantidad} {data.tipo_animal}",
         hora_mexico())
    )
    return {"ok": True}

@app.get("/corrales-destino")
def get_corrales_destino(tipo_animal: str, excluir_id: int, usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.id, c.nombre, c.zona, c.tipo, c.capacidad_max,
               IFNULL(SUM(l.poblacion_actual), 0) AS poblacion_actual
        FROM chiqueros c
        LEFT JOIN lotes l ON c.id = l.id_chiquero AND l.poblacion_actual > 0
        WHERE c.id != %s
        GROUP BY c.id
        ORDER BY c.zona, c.nombre
    """, (excluir_id,))

# ── Cambio de Etapa ───────────────────────────────────────────────────────────
class EtapaRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    nueva_etapa: str
    cantidad: int

@app.post("/etapa")
def cambiar_etapa(data: EtapaRequest, usuario=Depends(verificar_token)):
    execute(
        """UPDATE lotes SET poblacion_actual = GREATEST(poblacion_actual - %s, 0)
           WHERE id_chiquero = %s AND tipo_animal = %s""",
        (data.cantidad, data.id_chiquero, data.tipo_animal)
    )
    execute(
        """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (data.id_chiquero, data.nueva_etapa, data.cantidad)
    )
    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'CAMBIO_ESTADO', %s, %s, %s)""",
        (data.id_chiquero, data.nueva_etapa, data.cantidad,
         usuario["nombre"],
         f"Cambio de etapa: {data.tipo_animal} → {data.nueva_etapa} sin traspaso fisico",
         hora_mexico())
    )
    return {"ok": True}

# ── Parto ─────────────────────────────────────────────────────────────────────
class PartoRequest(BaseModel):
    id_chiquero: int
    crias_vivas: int
    no_logradas: int

@app.post("/parto")
def registrar_parto(data: PartoRequest, usuario=Depends(verificar_token)):
    if data.crias_vivas > 0:
        execute(
            """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
               VALUES (%s, 'Crías', %s)
               ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
            (data.id_chiquero, data.crias_vivas)
        )
        execute(
            """INSERT INTO historial_movimientos
               (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
               VALUES (%s, 'Crías', %s, 'PARTO', %s, %s, %s)""",
            (data.id_chiquero, data.crias_vivas, usuario["nombre"],
             f"Parto: {data.crias_vivas} crías vivas", hora_mexico())
        )
    if data.no_logradas > 0:
        execute(
            """INSERT INTO historial_movimientos
               (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
               VALUES (%s, 'Crías', %s, 'MUERTE', %s, %s, %s)""",
            (data.id_chiquero, data.no_logradas, usuario["nombre"],
             f"Parto: {data.no_logradas} no logradas", hora_mexico())
        )
    execute(
        """UPDATE lotes SET estado_pie_cria = 'Parida'
           WHERE id_chiquero = %s AND tipo_animal = 'Pie de Cría'""",
        (data.id_chiquero,)
    )
    return {"ok": True}

# ── Ventas ────────────────────────────────────────────────────────────────────
@app.get("/clientes")
def get_clientes(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.*, u.nombre AS vendedor
        FROM clientes c
        JOIN usuarios u ON u.id = c.usuario_id
        WHERE c.activo = 1 ORDER BY c.nombre
    """)

@app.get("/precio-dia")
def get_precio_dia(usuario=Depends(verificar_token)):
    row = fetch_one("SELECT valor FROM configuracion WHERE clave = 'precio_kg'")
    return {"precio": float(row["valor"]) if row else 48.00}

class VentaRequest(BaseModel):
    cliente_id: int
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    peso_kg: float
    precio_kg: float
    precio_cabeza: float
    comision_kg: float
    total_rancho: float
    total_comision: float
    es_destete: bool

@app.post("/venta")
def registrar_venta(data: VentaRequest, usuario=Depends(verificar_token)):
    execute(
        """UPDATE lotes SET poblacion_actual = GREATEST(poblacion_actual - %s, 0)
           WHERE id_chiquero = %s AND tipo_animal = %s""",
        (data.cantidad, data.id_chiquero, data.tipo_animal)
    )
    precio_final = data.precio_cabeza if data.es_destete else data.precio_kg
    execute(
        """INSERT INTO ventas
           (cliente_id, usuario_id, tipo_animal, cantidad, peso_kg, precio_kg,
            comision_kg, total_rancho, total_comision, foto_bascula)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')""",
        (data.cliente_id, usuario["id"], data.tipo_animal, data.cantidad,
         data.peso_kg, precio_final, data.comision_kg,
         data.total_rancho, data.total_comision)
    )
    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'VENTA', %s, %s, %s)""",
        (data.id_chiquero, data.tipo_animal, data.cantidad,
         usuario["nombre"],
         f"Venta — ${data.total_rancho:,.2f}", hora_mexico())
    )
    # Actualizar ciclo de vida del cliente
    cliente_actual = fetch_one("SELECT tipo FROM clientes WHERE id = %s", (data.cliente_id,))
    if cliente_actual:
        if cliente_actual["tipo"] in ("Nuevo", "Recuperado"):
            execute("UPDATE clientes SET tipo = 'Retenido' WHERE id = %s", (data.cliente_id,))
    execute("UPDATE clientes SET ultimo_pedido = %s WHERE id = %s",
            (hora_mexico(), data.cliente_id))
    return {"ok": True, "mensaje": f"Venta registrada — ${data.total_rancho:,.2f}"}

# ── Almacen ───────────────────────────────────────────────────────────────────
@app.get("/almacen/inventario")
def get_inventario(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT producto, unidad,
               SUM(CASE WHEN tipo='entrada' THEN cantidad ELSE -cantidad END) AS stock,
               SUM(CASE WHEN tipo='entrada' AND costo IS NOT NULL THEN costo ELSE 0 END) AS total_invertido
        FROM almacen
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
    from datetime import date, timedelta
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    return fetch_all("""
        SELECT u.id, u.nombre, u.sueldo_diario,
               COUNT(DISTINCT DATE(a.fecha_entrada)) AS dias_trabajados
        FROM usuarios u
        LEFT JOIN asistencia a ON a.usuario_id = u.id
            AND DATE(a.fecha_entrada) BETWEEN %s AND %s
        WHERE u.activo = 1 AND u.rol != 'admin'
        GROUP BY u.id ORDER BY u.nombre
    """, (lunes, domingo))

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
    from datetime import date
    hoy = date.today()
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
    from datetime import date
    hoy = date.today()
    execute(
        """UPDATE asistencia SET fecha_salida = %s
           WHERE usuario_id = %s AND DATE(fecha_entrada) = %s
           AND fecha_salida IS NULL""",
        (hora_mexico(), usuario["id"], hoy)
    )
    return {"ok": True}

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

# ── Clientes ──────────────────────────────────────────────────────────────────
@app.get("/clientes/lista")
def get_clientes_lista(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT c.id, c.nombre, c.telefono, c.tipo, u.nombre AS vendedor,
               COUNT(v.id) AS num_compras,
               IFNULL(SUM(v.total_rancho), 0) AS total_comprado
        FROM clientes c
        JOIN usuarios u ON u.id = c.usuario_id
        LEFT JOIN ventas v ON v.cliente_id = c.id
        WHERE c.activo = 1
        GROUP BY c.id ORDER BY c.nombre
    """)

class ClienteRequest(BaseModel):
    nombre: str
    telefono: str
    tipo: str
    usuario_id: int

@app.post("/clientes")
def crear_cliente(data: ClienteRequest, usuario=Depends(verificar_token)):
    existente = fetch_one("SELECT id FROM clientes WHERE telefono = %s", (data.telefono,))
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un cliente con ese teléfono")
    execute(
        "INSERT INTO clientes (nombre, telefono, tipo, usuario_id) VALUES (%s, %s, %s, %s)",
        (data.nombre, data.telefono, data.tipo, data.usuario_id)
    )
    return {"ok": True}

@app.post("/clientes/actualizar-ciclo")
def actualizar_ciclo_clientes(usuario=Depends(verificar_token)):
    from datetime import datetime, timedelta
    hace_un_anio = datetime.now() - timedelta(days=365)
    execute("""
        UPDATE clientes SET tipo = 'Disponible'
        WHERE tipo = 'Retenido'
        AND (ultimo_pedido IS NULL OR ultimo_pedido < %s)
    """, (hace_un_anio,))
    return {"ok": True}
# ── Ventas historial ──────────────────────────────────────────────────────────
@app.get("/ventas/historial")
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
        ORDER BY v.fecha DESC LIMIT 100
    """)

@app.get("/ventas/comisiones")
def get_comisiones(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT u.nombre AS vendedor,
               COUNT(v.id) AS num_ventas,
               IFNULL(SUM(v.total_comision), 0) AS total_comision,
               IFNULL(SUM(v.peso_kg), 0) AS kg_vendidos
        FROM ventas v
        JOIN usuarios u ON u.id = v.usuario_id
        GROUP BY v.usuario_id
        ORDER BY total_comision DESC
    """)
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
# ── Estado Pie de Cria ────────────────────────────────────────────────────────
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
    from datetime import datetime, timedelta
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
    return {"ok": True}

# ── Restablecer PIN ───────────────────────────────────────────────────────────
class ResetPinRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str

@app.post("/usuarios/reset-pin")
def reset_pin(data: ResetPinRequest, usuario=Depends(verificar_token)):
    execute(
        "UPDATE usuarios SET pin = %s, pin_temporal = %s, primer_acceso = 1 WHERE id = %s",
        (data.nuevo_pin, data.nuevo_pin, data.usuario_id)
    )
    return {"ok": True}
class ActivarRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str

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
# ── Registrar animales y corrales ─────────────────────────────────────────────
@app.get("/configuracion/tipos-animal")
def get_tipos_animal(usuario=Depends(verificar_token)):
    return {"tipos": ["Semental", "Pie de Cría", "Crías", "Destete", 
                      "Desarrollo", "Engorda", "Herniados", "Desecho"]}

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
    largo: float
    ancho: float
    capacidad_max: int

@app.post("/configuracion/corrales")
def crear_corral(data: CorralRequest, usuario=Depends(verificar_token)):
    area = data.largo * data.ancho
    execute(
        """INSERT INTO chiqueros (nombre, tipo, zona, largo, ancho, area_m2, capacidad_max)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (data.nombre, data.tipo, data.zona, data.largo, data.ancho, area, data.capacidad_max)
    )
    return {"ok": True}
class NuclearRequest(BaseModel):
    confirmacion: str

@app.post("/configuracion/nuclear")
def reset_nuclear(data: NuclearRequest, usuario=Depends(verificar_token)):
    ...
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
    execute("""UPDATE lotes SET poblacion_actual = 0, 
               estado_pie_cria = NULL, fecha_monta = NULL, 
               fecha_parto_estimada = NULL""")
    execute("""UPDATE usuarios SET primer_acceso = 1, pin = pin_temporal 
               WHERE rol != 'admin' AND pin_temporal IS NOT NULL""")
    
    return {"ok": True, "mensaje": "Sistema limpiado — listo para datos reales"}
# ── Historial asistencias ─────────────────────────────────────────────────────
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