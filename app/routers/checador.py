import cloudinary.uploader

from fastapi import APIRouter, Depends

from database import fetch_one, fetch_all, execute
from app.core.security import verificar_token
from app.core.time import hora_mexico
from app.schemas.checador import FotoChecadorRequest

router = APIRouter(tags=["Checador"])


@router.get("/checador/estado")
def get_estado_checador(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    entrada = fetch_one(
        """
        SELECT id, fecha_entrada
        FROM asistencia
        WHERE usuario_id = %s
        AND DATE(fecha_entrada) = %s
        ORDER BY fecha_entrada DESC
        LIMIT 1
    """,
        (usuario["id"], hoy),
    )

    salida = None

    if entrada:
        salida = fetch_one(
            """
            SELECT fecha_salida
            FROM asistencia
            WHERE id = %s
            AND fecha_salida IS NOT NULL
        """,
            (entrada["id"],),
        )

    return {
        "checo_entrada": entrada is not None,
        "checo_salida": salida is not None,
        "id_asistencia": entrada["id"] if entrada else None,
    }


@router.post("/checador/entrada")
def registrar_entrada(usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO asistencia (usuario_id, nombre, fecha_entrada)
           VALUES (%s, %s, %s)""",
        (
            usuario["id"],
            usuario["nombre"],
            hora_mexico(),
        ),
    )

    return {"ok": True}


@router.post("/checador/salida")
def registrar_salida(usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    execute(
        """UPDATE asistencia SET fecha_salida = %s
           WHERE usuario_id = %s
           AND DATE(fecha_entrada) = %s
           AND fecha_salida IS NULL""",
        (
            hora_mexico(),
            usuario["id"],
            hoy,
        ),
    )

    return {"ok": True}


@router.get("/checador/historial")
def get_historial_asistencias(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT a.id, a.usuario_id, a.nombre,
               a.fecha_entrada, a.fecha_salida,
               a.foto_entrada, a.foto_salida
        FROM asistencia a
        ORDER BY a.fecha_entrada DESC
        LIMIT 100
    """)


@router.post("/checador/foto")
def subir_foto_checador(data: FotoChecadorRequest, usuario=Depends(verificar_token)):
    hoy = hora_mexico().date()

    nombre_foto = f"corralia/checador/{usuario['nombre']}_{data.tipo}_{hoy}"

    resultado = cloudinary.uploader.upload(
        f"data:image/jpeg;base64,{data.foto_base64}",
        public_id=nombre_foto,
        overwrite=True,
    )

    url = resultado["secure_url"]

    if data.tipo == "entrada":
        execute(
            """UPDATE asistencia SET foto_entrada = %s
               WHERE usuario_id = %s
               AND DATE(fecha_entrada) = %s""",
            (
                url,
                usuario["id"],
                hoy,
            ),
        )
    else:
        execute(
            """UPDATE asistencia SET foto_salida = %s
               WHERE usuario_id = %s
               AND DATE(fecha_entrada) = %s""",
            (
                url,
                usuario["id"],
                hoy,
            ),
        )

    return {"ok": True, "url": url}
