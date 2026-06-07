from pydantic import BaseModel


class ApartadoRequest(BaseModel):
    cliente_id: int
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    anticipo: float
    fecha_compromiso: str
    notas: str = ""


class LiquidarApartadoRequest(BaseModel):
    peso_kg: float = 0
    precio_kg: float = 0
    precio_cabeza: float = 0
    total_rancho: float
    total_comision: float = 0
    comision_kg: float = 0