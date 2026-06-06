from pydantic import BaseModel


class VentaRequest(BaseModel):
    cliente_id: int
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    peso_kg: float
    precio_kg: float
    precio_cabeza: float
    comision_kg: float
    total_rancho: float
    total_comision: float
    es_destete: bool
