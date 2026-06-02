from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.telegram import enviar_telegram
from app.core.time import hora_mexico
from app.schemas.configuracion import (
    PieCriaUpdate,
    AnimalRequest,
    CorralRequest,
    CorralEditRequest,
    NuclearRequest,
)


router = APIRouter(tags=["Configuración"])


@router.get("/configuracion/precio")
def get_precio(usuario=Depends(verificar_token)):
    row = fetch_one("SELECT valor FROM configuracion WHERE clave = 'precio_kg'")
    return {"precio": float(row["valor"]) if row else 48.00}


@router.post("/configuracion/precio")
def actualizar_precio(precio: float, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO configuracion (clave, valor)
           VALUES ('precio_kg', %s)
           ON DUPLICATE KEY UPDATE valor = %s""",
        (str(precio), str(precio))
    )

    return {"ok": True}


@router.get("/configuracion/corrales")
def get_corrales(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, tipo, zona, capacidad_max,
               IFNULL(area_m2, largo * ancho) AS area_m2
        FROM chiqueros
        ORDER BY zona, nombre
    """)


@router.post("/configuracion/corrales")
def crear_corral(data: CorralRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO chiqueros (nombre, tipo, zona, largo, ancho, capacidad_max)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            data.nombre,
            data.tipo,
            data.zona,
            data.largo,
            data.ancho,
            data.capacidad_max,
        )
    )

    return {"ok": True}


@router.put("/configuracion/corrales/{corral_id}")
def editar_corral(
    corral_id: int,
    data: CorralEditRequest,
    usuario=Depends(verificar_token)
):
    execute(
        """UPDATE chiqueros SET nombre=%s, tipo=%s, zona=%s,
           capacidad_max=%s, largo=%s, ancho=%s
           WHERE id=%s""",
        (
            data.nombre,
            data.tipo,
            data.zona,
            data.capacidad_max,
            data.largo,
            data.ancho,
            corral_id,
        )
    )

    return {"ok": True}


@router.get("/configuracion/pie-de-cria")
def get_pie_de_cria(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT l.id, l.id_chiquero, l.estado_pie_cria, l.fecha_monta,
               l.fecha_parto_estimada, l.poblacion_actual, c.nombre AS corral
        FROM lotes l
        JOIN chiqueros c ON c.id = l.id_chiquero
        WHERE l.tipo_animal = 'Pie de Cría'
        AND l.poblacion_actual > 0
        ORDER BY c.nombre
    """)


@router.post("/configuracion/pie-de-cria")
def actualizar_pie_de_cria(
    data: PieCriaUpdate,
    usuario=Depends(verificar_token)
):
    fecha_parto = None
    fecha_monta = None

    if data.fecha_monta:
        fecha_monta = datetime.strptime(data.fecha_monta, "%Y-%m-%d").date()
        fecha_parto = fecha_monta + timedelta(days=114)

    execute(
        """UPDATE lotes SET estado_pie_cria = %s,
           fecha_monta = %s, fecha_parto_estimada = %s
           WHERE id = %s""",
        (
            data.estado,
            fecha_monta,
            fecha_parto,
            data.lote_id,
        )
    )

    if data.fecha_monta:
        enviar_telegram(
            f"🐷 MONTA REGISTRADA\n"
            f"👤 {usuario['nombre']}\n"
            f"📅 Fecha monta: {data.fecha_monta}\n"
            f"📅 Parto estimado: {fecha_parto}\n"
            f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}"
        )

    return {"ok": True}


@router.post("/configuracion/registrar-animales")
def registrar_animales(data: AnimalRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO lotes (id_chiquero, tipo_animal, poblacion_actual)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE poblacion_actual = poblacion_actual + VALUES(poblacion_actual)""",
        (
            data.id_chiquero,
            data.tipo_animal,
            data.cantidad,
        )
    )

    execute(
        """INSERT INTO historial_movimientos
           (id_chiquero_destino, tipo_animal, cantidad, tipo_evento, id_usuario, notas, fecha)
           VALUES (%s, %s, %s, 'ENTRADA', %s, %s, %s)""",
        (
            data.id_chiquero,
            data.tipo_animal,
            data.cantidad,
            usuario["nombre"],
            f"Registro inicial: {data.cantidad} {data.tipo_animal}",
            hora_mexico(),
        )
    )

    return {"ok": True}


@router.post("/configuracion/nuclear")
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

    execute("""
        UPDATE lotes SET poblacion_actual = 0,
        estado_pie_cria = NULL,
        fecha_monta = NULL,
        fecha_parto_estimada = NULL
    """)

    execute("""
        UPDATE usuarios SET primer_acceso = 1, pin = pin_temporal
        WHERE rol != 'admin'
        AND pin_temporal IS NOT NULL
    """)

    return {"ok": True, "mensaje": "Sistema limpiado — listo para datos reales"}