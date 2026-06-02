from fastapi import APIRouter, Depends

from database import fetch_all, execute
from app.core.security import verificar_token
from app.core.time import hora_mexico
from app.schemas.vacunas import VacunaRequest


router = APIRouter(tags=["Vacunas"])


@router.get("/vacunas/historial")
def get_historial_vacunas(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT v.fecha, c.nombre AS corral, v.tipo_animal,
               v.vacuna, v.nombre_comercial, v.cantidad, v.notas, v.usuario_id
        FROM vacunaciones v
        JOIN chiqueros c ON c.id = v.id_chiquero
        ORDER BY v.fecha DESC
        LIMIT 50
    """)


@router.post("/vacunas")
def registrar_vacuna(data: VacunaRequest, usuario=Depends(verificar_token)):
    execute(
        """INSERT INTO vacunaciones
           (id_chiquero, tipo_animal, vacuna, nombre_comercial, cantidad, notas, usuario_id, fecha)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            data.id_chiquero,
            data.tipo_animal,
            data.vacuna,
            data.nombre_comercial or None,
            data.cantidad,
            data.notas or None,
            usuario["nombre"],
            hora_mexico(),
        )
    )

    return {"ok": True}