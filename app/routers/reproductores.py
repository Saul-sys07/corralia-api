from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from database import fetch_all, fetch_one, execute
from app.core.security import verificar_token
from app.core.time import hora_mexico
from app.core.telegram import enviar_telegram
from app.schemas.reproductores import (
    ReproductorRequest,
    MontaRequest,
    ResultadoMontaRequest,
)

router = APIRouter(tags=["Reproductores"])


@router.get("/reproductores")
def get_reproductores(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT r.id, r.identificador, r.arete, r.tipo, r.raza_linea,
               r.id_chiquero, c.nombre AS corral, c.zona,
               r.estado, r.fecha_nacimiento, r.origen, r.notas,
               r.activo, r.fecha_creacion
        FROM reproductores r
        JOIN chiqueros c ON c.id = r.id_chiquero
        WHERE r.activo = 1
        ORDER BY r.tipo, r.identificador
    """)


@router.post("/reproductores")
def crear_reproductor(data: ReproductorRequest, usuario=Depends(verificar_token)):
    if usuario["rol"] not in ["admin", "encargado_general", "gestacion"]:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not data.identificador or not data.tipo or not data.id_chiquero:
        raise HTTPException(
            status_code=400,
            detail="Captura identificador, tipo y corral"
        )

    if data.tipo not in ["Pie de Cría", "Semental"]:
        raise HTTPException(
            status_code=400,
            detail="Solo se registran Pie de Cría y Semental"
        )

    if data.arete:
        existe = fetch_one(
            "SELECT id FROM reproductores WHERE arete=%s AND activo=1 LIMIT 1",
            (data.arete,),
        )
        if existe:
            raise HTTPException(
                status_code=400,
                detail="Ya existe un reproductor con ese arete"
            )

    execute(
        """INSERT INTO reproductores
           (identificador, arete, tipo, raza_linea, id_chiquero, estado,
            fecha_nacimiento, origen, notas, creado_por, fecha_creacion, activo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)""",
        (
            data.identificador,
            data.arete or None,
            data.tipo,
            data.raza_linea,
            data.id_chiquero,
            data.estado or "Activo",
            data.fecha_nacimiento or None,
            data.origen,
            data.notas,
            usuario["nombre"],
            hora_mexico(),
        ),
    )

    return {"ok": True, "mensaje": "Reproductor registrado"}


@router.put("/reproductores/{reproductor_id}")
def editar_reproductor(
    reproductor_id: int,
    data: ReproductorRequest,
    usuario=Depends(verificar_token),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede editar")

    if data.arete:
        existe = fetch_one(
            """SELECT id FROM reproductores
               WHERE arete=%s AND id != %s AND activo=1
               LIMIT 1""",
            (data.arete, reproductor_id),
        )
        if existe:
            raise HTTPException(
                status_code=400,
                detail="Ya existe otro reproductor con ese arete"
            )

    execute(
        """UPDATE reproductores
           SET identificador=%s, arete=%s, tipo=%s, raza_linea=%s,
               id_chiquero=%s, estado=%s, fecha_nacimiento=%s,
               origen=%s, notas=%s
           WHERE id=%s""",
        (
            data.identificador,
            data.arete or None,
            data.tipo,
            data.raza_linea,
            data.id_chiquero,
            data.estado,
            data.fecha_nacimiento or None,
            data.origen,
            data.notas,
            reproductor_id,
        ),
    )

    return {"ok": True}


@router.post("/reproductores/{reproductor_id}/baja")
def baja_reproductor(reproductor_id: int, usuario=Depends(verificar_token)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede dar de baja")

    execute(
        """UPDATE reproductores
           SET activo=0, estado='Baja'
           WHERE id=%s""",
        (reproductor_id,),
    )

    return {"ok": True}


@router.get("/reproductores/montas")
def get_montas(usuario=Depends(verificar_token)):
    return fetch_all("""
        SELECT m.id, m.fecha_monta, m.fecha_parto_estimada, m.estado,
               m.resultado, m.nacidos_total, m.nacidos_vivos,
               m.nacidos_muertos, m.destetados, m.notas,
               p.identificador AS puerca_identificador,
               p.arete AS puerca_arete,
               p.raza_linea AS puerca_raza,
               s.identificador AS semental_identificador,
               s.arete AS semental_arete,
               s.raza_linea AS semental_raza
        FROM montas m
        JOIN reproductores p ON p.id = m.reproductora_id
        JOIN reproductores s ON s.id = m.semental_id
        ORDER BY m.fecha_monta DESC
        LIMIT 100
    """)


@router.post("/reproductores/montas")
def registrar_monta(data: MontaRequest, usuario=Depends(verificar_token)):
    if usuario["rol"] not in ["admin", "encargado_general", "gestacion"]:
        raise HTTPException(status_code=403, detail="No autorizado")
    puerca = fetch_one(
        """SELECT id, identificador, arete, raza_linea
           FROM reproductores
           WHERE id=%s AND tipo='Pie de Cría' AND activo=1""",
        (data.reproductora_id,),
    )

    semental = fetch_one(
        """SELECT id, identificador, arete, raza_linea
           FROM reproductores
           WHERE id=%s AND tipo='Semental' AND activo=1""",
        (data.semental_id,),
    )

    if not puerca:
        raise HTTPException(status_code=400, detail="Selecciona una Pie de Cría válida")

    if not semental:
        raise HTTPException(status_code=400, detail="Selecciona un Semental válido")

    fecha_monta = datetime.strptime(data.fecha_monta, "%Y-%m-%d").date()
    fecha_parto = fecha_monta + timedelta(days=114)

    execute(
        """INSERT INTO montas
           (reproductora_id, semental_id, fecha_monta,
            fecha_parto_estimada, estado, notas, registrado_por, fecha_registro)
           VALUES (%s, %s, %s, %s, 'Pendiente', %s, %s, %s)""",
        (
            data.reproductora_id,
            data.semental_id,
            fecha_monta,
            fecha_parto,
            data.notas,
            usuario["nombre"],
            hora_mexico(),
        ),
    )

    enviar_telegram(
        f"🐷 MONTA REGISTRADA\n"
        f"👤 Registró: {usuario['nombre']}\n"
        f"🐖 Puerca: {puerca['arete'] or puerca['identificador']}\n"
        f"🐗 Semental: {semental['arete'] or semental['identificador']}\n"
        f"🧬 Cruza: {puerca['raza_linea'] or 'Desconocida'} × {semental['raza_linea'] or 'Desconocida'}\n"
        f"📅 Monta: {fecha_monta}\n"
        f"📅 Parto estimado: {fecha_parto}"
    )

    return {
        "ok": True,
        "mensaje": "Monta registrada",
        "fecha_parto_estimada": str(fecha_parto),
    }


@router.post("/reproductores/montas/{monta_id}/resultado")
def registrar_resultado_monta(
    monta_id: int,
    data: ResultadoMontaRequest,
    usuario=Depends(verificar_token),
):
    if usuario["rol"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Solo admin puede registrar o corregir el resultado"
        )

    execute(
        """UPDATE montas
           SET estado=%s,
               resultado=%s,
               nacidos_total=%s,
               nacidos_vivos=%s,
               nacidos_muertos=%s,
               destetados=%s,
               notas=%s
           WHERE id=%s""",
        (
            "Cerrada",
            data.resultado,
            data.nacidos_total,
            data.nacidos_vivos,
            data.nacidos_muertos,
            data.destetados,
            data.notas,
            monta_id,
        ),
    )

    return {"ok": True}