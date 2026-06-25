from pydantic import BaseModel
from typing import Optional


class ReproductorRequest(BaseModel):
    identificador: str
    arete: Optional[str] = None
    tipo: str
    raza_linea: Optional[str] = None
    id_chiquero: int
    estado: str = "Activo"
    fecha_nacimiento: Optional[str] = None
    origen: Optional[str] = None
    notas: Optional[str] = None


class MontaRequest(BaseModel):
    reproductora_id: int
    semental_id: int
    fecha_monta: str
    notas: Optional[str] = None


class ResultadoMontaRequest(BaseModel):
    resultado: str
    nacidos_total: Optional[int] = None
    nacidos_vivos: Optional[int] = None
    nacidos_muertos: Optional[int] = None
    destetados: Optional[int] = None
    notas: Optional[str] = None