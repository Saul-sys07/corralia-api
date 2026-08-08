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
    SolicitudCorralRequest,
    ComisionTrabajadorUpdate,
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
        (str(precio), str(precio)),
    )

    return {"ok": True}

@router.get("/configuracion/comisiones-trabajador")
def get_comisiones_trabajador(usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede ver comisiones")

    return fetch_all("""
        SELECT
            u.id AS usuario_id,
            u.nombre,
            u.rol,
            IFNULL(ct.comision_kg, 0) AS comision_kg,
            IFNULL(ct.activo, 0) AS activo
        FROM usuarios u
        LEFT JOIN comisiones_trabajador ct ON ct.usuario_id = u.id
        WHERE u.rol != 'admin'
        ORDER BY u.nombre
    """)


@router.put("/configuracion/comisiones-trabajador/{usuario_id}")
def actualizar_comision_trabajador(
    usuario_id: int,
    data: ComisionTrabajadorUpdate,
    usuario=Depends(verificar_token),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede editar comisiones")

    if data.comision_kg < 0:
        raise HTTPException(
            status_code=400,
            detail="La comisión no puede ser negativa",
        )

    trabajador = fetch_one(
        "SELECT id, nombre FROM usuarios WHERE id = %s",
        (usuario_id,),
    )

    if not trabajador:
        raise HTTPException(status_code=404, detail="Trabajador no encontrado")

    execute(
        """
        INSERT INTO comisiones_trabajador
        (usuario_id, comision_kg, activo, fecha_actualizacion)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            comision_kg = VALUES(comision_kg),
            activo = VALUES(activo),
            fecha_actualizacion = VALUES(fecha_actualizacion)
        """,
        (
            usuario_id,
            data.comision_kg,
            1 if data.activo else 0,
            hora_mexico(),
        ),
    )

    return {
        "ok": True,
        "mensaje": f"Comisión actualizada para {trabajador['nombre']}",
    }

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
    if usuario["rol"] not in ["admin", "encargado_general"]:
        raise HTTPException(status_code=403, detail="No autorizado")

    es_admin = usuario["rol"] == "admin"

    tipo = data.tipo or "Comunal"
    capacidad = data.capacidad_max if data.capacidad_max is not None else 0
    largo = data.largo if data.largo is not None else None
    ancho = data.ancho if data.ancho is not None else None

    if not data.nombre or not data.zona:
        raise HTTPException(
            status_code=400,
            detail="Captura nombre y zona del corral"
        )

    if es_admin and capacidad <= 0:
        raise HTTPException(
            status_code=400,
            detail="Captura capacidad del corral"
        )

    execute(
        """INSERT INTO chiqueros (nombre, tipo, zona, largo, ancho, capacidad_max)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            data.nombre,
            tipo,
            data.zona,
            largo,
            ancho,
            capacidad,
        ),
    )

    return {"ok": True}

@router.post("/configuracion/corrales/solicitudes")
def solicitar_corral(data: SolicitudCorralRequest, usuario=Depends(verificar_token)):
    if usuario["rol"] not in ["admin", "encargado_general"]:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not data.nombre or not data.zona:
        raise HTTPException(
            status_code=400,
            detail="Captura nombre y zona del corral"
        )

    execute(
        """INSERT INTO solicitudes_corrales
           (nombre, zona, tipo, estado, usuario_id, fecha_solicitud, notas)
           VALUES (%s, %s, %s, 'pendiente', %s, %s, %s)""",
        (
            data.nombre,
            data.zona,
            data.tipo or "Comunal",
            usuario["nombre"],
            hora_mexico(),
            data.notas,
        ),
    )

    enviar_telegram(
        f"⏳ SOLICITUD DE NUEVO CORRAL\n"
        f"👤 Solicitado por: {usuario['nombre']}\n"
        f"🏠 Nombre: {data.nombre}\n"
        f"📍 Zona: {data.zona}\n"
        f"🏷️ Tipo: {data.tipo or 'Comunal'}\n"
        f"📝 Notas: {data.notas or 'Sin notas'}\n"
        f"🕐 {hora_mexico().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"✅ Entra a Corralia → Corrales para confirmar o rechazar."
    )

    return {
        "ok": True,
        "mensaje": "Solicitud enviada, pendiente de confirmación por admin"
    }


@router.get("/configuracion/corrales/solicitudes")
def get_solicitudes_corrales(usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        return []

    return fetch_all("""
        SELECT id, nombre, zona, tipo, estado, usuario_id,
               fecha_solicitud, notas
        FROM solicitudes_corrales
        WHERE estado = 'pendiente'
        ORDER BY fecha_solicitud DESC
    """)


@router.post("/configuracion/corrales/solicitudes/{solicitud_id}/confirmar")
def confirmar_solicitud_corral(
    solicitud_id: int,
    usuario=Depends(verificar_token),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede confirmar")

    solicitud = fetch_one(
        """
        SELECT *
        FROM solicitudes_corrales
        WHERE id = %s
        AND estado = 'pendiente'
        LIMIT 1
        """,
        (solicitud_id,),
    )

    if not solicitud:
        raise HTTPException(
            status_code=404,
            detail="Solicitud no encontrada o ya procesada"
        )

    corral_id = execute(
        """INSERT INTO chiqueros
           (nombre, tipo, zona, largo, ancho, capacidad_max)
           VALUES (%s, %s, %s, NULL, NULL, 0)""",
        (
            solicitud["nombre"],
            solicitud["tipo"] or "Comunal",
            solicitud["zona"],
        ),
    )

    execute(
        """UPDATE solicitudes_corrales
           SET estado = 'confirmado',
               confirmado_por = %s,
               fecha_confirmacion = %s,
               corral_id = %s
           WHERE id = %s""",
        (
            usuario["nombre"],
            hora_mexico(),
            corral_id,
            solicitud_id,
        ),
    )

    return {"ok": True, "mensaje": "Corral confirmado y creado"}


@router.post("/configuracion/corrales/solicitudes/{solicitud_id}/rechazar")
def rechazar_solicitud_corral(
    solicitud_id: int,
    usuario=Depends(verificar_token),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede rechazar")

    execute(
        """UPDATE solicitudes_corrales
           SET estado = 'rechazado',
               confirmado_por = %s,
               fecha_confirmacion = %s
           WHERE id = %s
           AND estado = 'pendiente'""",
        (
            usuario["nombre"],
            hora_mexico(),
            solicitud_id,
        ),
    )

    return {"ok": True}


@router.put("/configuracion/corrales/{corral_id}")
def editar_corral(
    corral_id: int, data: CorralEditRequest, usuario=Depends(verificar_token)
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
        ),
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
def actualizar_pie_de_cria(data: PieCriaUpdate, usuario=Depends(verificar_token)):
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
        ),
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
        ),
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
        ),
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
