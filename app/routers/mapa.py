from fastapi import APIRouter, Depends

from database import fetch_all
from app.core.security import verificar_token

router = APIRouter(tags=["Mapa"])


@router.get("/mapa")
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
               ) AS estado_pie_cria,
               MAX(CASE WHEN l.tipo_animal = 'Pie de Cría' THEN l.id END) AS lote_id,
               MAX(CASE WHEN l.tipo_animal = 'Pie de Cría' THEN l.foto_pie_cria END) AS foto_pie_cria
        FROM chiqueros c
        LEFT JOIN lotes l ON c.id = l.id_chiquero AND l.poblacion_actual > 0
        GROUP BY c.id
        ORDER BY c.zona, CAST(REGEXP_SUBSTR(c.nombre, '[0-9]+') AS UNSIGNED), c.nombre
    """)


@router.get("/corrales/{id_chiquero}/historial")
def get_historial_corral(id_chiquero: int, usuario=Depends(verificar_token)):
    return fetch_all(
        """
        SELECT 
            h.tipo_evento,
            h.tipo_animal,
            h.cantidad,
            h.notas,
            h.id_usuario,
            h.fecha,
            CONCAT(co.zona, ' ', co.nombre) AS corral_origen,
            CONCAT(cd.zona, ' ', cd.nombre) AS corral_destino,
            CASE
                WHEN h.id_chiquero_origen = %s THEN 'SALIDA'
                WHEN h.id_chiquero_destino = %s THEN 'ENTRADA'
                ELSE 'MOVIMIENTO'
            END AS direccion
        FROM historial_movimientos h
        LEFT JOIN chiqueros co ON co.id = h.id_chiquero_origen
        LEFT JOIN chiqueros cd ON cd.id = h.id_chiquero_destino
        WHERE h.id_chiquero_origen = %s
           OR h.id_chiquero_destino = %s
        ORDER BY h.fecha DESC
        LIMIT 15
        """,
        (id_chiquero, id_chiquero, id_chiquero, id_chiquero),
    )