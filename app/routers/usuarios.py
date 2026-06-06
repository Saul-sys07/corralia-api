from fastapi import APIRouter, Depends, HTTPException

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.schemas.usuarios import (
    UsuarioRequest,
    ActivarRequest,
    ResetPinRequest,
)

router = APIRouter(tags=["Usuarios"])


@router.get("/usuarios")
def get_usuarios(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT id, nombre, rol, activo, ultimo_acceso
        FROM usuarios
        ORDER BY nombre
    """)


@router.post("/usuarios")
def crear_usuario(data: UsuarioRequest, usuario=Depends(verificar_token)):
    existente = fetch_one("SELECT id FROM usuarios WHERE nombre = %s", (data.nombre,))

    if existente:
        raise HTTPException(
            status_code=400, detail="Ya existe un usuario con ese nombre"
        )

    execute(
        """INSERT INTO usuarios (nombre, pin, pin_temporal, rol, primer_acceso)
           VALUES (%s, %s, %s, %s, 1)""",
        (
            data.nombre,
            data.pin_temporal,
            data.pin_temporal,
            data.rol,
        ),
    )

    return {"ok": True}


@router.post("/usuarios/toggle")
def toggle_usuario(usuario_id: int, usuario=Depends(verificar_token)):
    execute("UPDATE usuarios SET activo = NOT activo WHERE id = %s", (usuario_id,))

    return {"ok": True}


@router.post("/usuarios/activar")
def activar_usuario(data: ActivarRequest):
    existente = fetch_one(
        "SELECT id FROM usuarios WHERE pin = %s AND id != %s",
        (
            data.nuevo_pin,
            data.usuario_id,
        ),
    )

    if existente:
        raise HTTPException(status_code=400, detail="Ese PIN ya lo usa otra persona")

    execute(
        """UPDATE usuarios
           SET pin = %s, pin_temporal = NULL, primer_acceso = 0
           WHERE id = %s""",
        (
            data.nuevo_pin,
            data.usuario_id,
        ),
    )

    return {"ok": True}


@router.post("/usuarios/reset-pin")
def reset_pin(data: ResetPinRequest, usuario=Depends(verificar_token)):
    existente = fetch_one(
        "SELECT id FROM usuarios WHERE pin = %s AND id != %s",
        (
            data.nuevo_pin,
            data.usuario_id,
        ),
    )

    if existente:
        raise HTTPException(status_code=400, detail="Ese PIN ya lo usa otra persona")

    execute(
        """UPDATE usuarios
           SET pin = %s, pin_temporal = %s, primer_acceso = 1
           WHERE id = %s""",
        (
            data.nuevo_pin,
            data.nuevo_pin,
            data.usuario_id,
        ),
    )

    return {"ok": True}
