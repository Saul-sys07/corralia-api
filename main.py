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
from app.routers import auth, mapa, movimientos, clientes, ventas, almacen, finanzas, checador, vacunas, usuarios, configuracion, notificaciones, monta, apartados, reportes


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
app.include_router(configuracion.router)
app.include_router(notificaciones.router)
app.include_router(monta.router)
app.include_router(apartados.router)
app.include_router(reportes.router)

@app.get("/")
def root():
    return {"status": "Corralia API v4 corriendo"}
